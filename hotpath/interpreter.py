"""The interpreter tier: a Claude tool-use loop over Playwright, driven by a compact DOM."""
import json
import time
from dataclasses import dataclass, field

from hotpath import dom, guards, llm as llm_mod, tasks

MAX_TOOL_CALLS = 15

SYSTEM = """You operate a web page through tools to complete a task.
The page is described as a numbered list of interactive elements and tables: [index] tag "label".
Refer to elements only by their [index] from the LATEST listing; indexes are refreshed after every action.
To pick an option in a <select>, use fill with the option text.
Be efficient: fill the search box or filter, click the submit button, call extract_table on the results table,
then call done with the answer in the required JSON shape. Do not repeat actions that already succeeded."""


def tool_defs(template_id: str) -> list[dict]:
    el = {"type": "integer", "description": "Element index from the latest page listing"}
    return [
        {
            "name": "click",
            "description": "Click an element.",
            "input_schema": {"type": "object", "properties": {"el": el}, "required": ["el"], "additionalProperties": False},
        },
        {
            "name": "fill",
            "description": "Type text into an input, or choose an option (by text) in a select.",
            "input_schema": {
                "type": "object",
                "properties": {"el": el, "text": {"type": "string"}},
                "required": ["el", "text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "extract_table",
            "description": "Read a table's rows as JSON objects keyed by column header.",
            "input_schema": {"type": "object", "properties": {"el": el}, "required": ["el"], "additionalProperties": False},
        },
        {
            "name": "done",
            "description": "Finish the task and return the result.",
            "input_schema": {
                "type": "object",
                "properties": {"result": tasks.TEMPLATES[template_id]["schema"]},
                "required": ["result"],
                "additionalProperties": False,
            },
        },
    ]


@dataclass
class InterpResult:
    ok: bool = False
    result: object = None
    trace: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""
    capped: bool = False

    @property
    def cost(self) -> float:
        return llm_mod.cost(self.tokens_in, self.tokens_out)


def observe(page) -> tuple[list[dict], str]:
    els = dom.snapshot(page)
    return els, f"URL: {page.url}\nPage elements:\n{dom.render(els)}"


def describe(step: dict) -> str:
    s = f'{step["step"]}. {step["action"]} {step["fingerprint"]["tag"]} "{step["fingerprint"]["label"]}"'
    if "text" in step.get("args", {}):
        s += f' <- "{step["args"]["text"]}"'
    return s


def run(page, template_id, params, llm=None, emit=lambda *a, **k: None, completed_steps=None) -> InterpResult:
    """Run the agent loop on the page as it is now. With completed_steps, continue a deoptimized run."""
    llm = llm or llm_mod.get_llm()
    llm.bind(template_id, params)
    res = InterpResult()
    first_step = len(completed_steps or [])
    els, obs = observe(page)
    intro = f"Task: {tasks.goal(template_id, params)}\n"
    if completed_steps:
        intro += (
            "Compiled code already completed these steps on this page (do not redo them unless needed):\n"
            + "\n".join(describe(s) for s in completed_steps)
            + "\nFinish the remaining part of the task from the current page.\n"
        )
    messages = [{"role": "user", "content": intro + "\n" + obs}]
    tools = tool_defs(template_id)

    while True:
        if res.llm_calls >= MAX_TOOL_CALLS:
            res.capped, res.error = True, f"cap: {MAX_TOOL_CALLS} LLM calls without done()"
            return res
        resp = llm.create(SYSTEM, messages, tools)
        res.llm_calls += 1
        res.tokens_in += resp.usage.input_tokens
        res.tokens_out += resp.usage.output_tokens
        content = [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else vars(b) for b in resp.content]
        messages.append({"role": "assistant", "content": content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": "Use the tools. Call done when the task is complete."})
            continue
        results = []
        for call in calls:
            res.tool_calls += 1
            if res.tool_calls > MAX_TOOL_CALLS:
                res.capped, res.error = True, f"cap: exceeded {MAX_TOOL_CALLS} tool calls"
                return res
            inp = call.input if isinstance(call.input, dict) else json.loads(call.input)
            emit("tool", f"{call.name} {json.dumps(inp)}")
            if call.name == "done":
                err = tasks.validate(template_id, inp.get("result"))
                if err is None:
                    res.ok, res.result = True, inp["result"]
                    return res
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": f"Invalid result: {err}", "is_error": True})
                continue
            try:
                text = _execute(page, els, call.name, inp, res, first_step)
            except Exception as e:  # report back to the model; it can recover
                text = f"Error: {type(e).__name__}: {str(e).splitlines()[0][:200]}"
            els, obs = observe(page)
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": f"{text}\n{obs}"})
        messages.append({"role": "user", "content": results})


def _execute(page, els, action, inp, res: InterpResult, first_step: int) -> str:
    i = inp["el"]
    if not (0 <= i < len(els)):
        raise IndexError(f"no element [{i}]")
    el = els[i]
    sel = el["selector"]
    step = {"step": first_step + len(res.trace), "action": action, "selector": sel,
            "fingerprint": dom.fingerprint(el), "args": {}}
    if action == "extract_table":
        table = dom.extract(page, sel)
        if table is None:
            raise ValueError("not a table")
        res.tables.append(table)
        step["noop"] = False
        res.trace.append(step)
        return "Table data: " + json.dumps(table)
    before = dom.page_state(page)
    if action == "click":
        page.click(sel, timeout=3000)
        page.wait_for_load_state("load")
    elif action == "fill":
        step["args"]["text"] = inp["text"]
        if el["tag"] == "select":
            label = next((o for o in el.get("options", []) if o.lower() == inp["text"].strip().lower()), inp["text"])
            page.select_option(sel, label=label, timeout=3000)
        else:
            page.fill(sel, inp["text"], timeout=3000)
    else:
        raise ValueError(f"unknown action {action}")
    step["noop"] = dom.page_state(page) == before
    res.trace.append(step)
    return "OK" + (" (no visible change)" if step["noop"] else "")
