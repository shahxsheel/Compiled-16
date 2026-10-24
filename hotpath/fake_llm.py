"""A scripted stand-in for the model, used by tests and offline demos.

It reads the same observation text the real model sees and returns fixed tool calls:
fill the search/filter -> click submit -> extract_table -> done.
"""
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from hotpath import tasks

LINE_RE = re.compile(r'^\[(\d+)\] (\w+)(?: type=\w+)? "([^"]*)"(?: value="([^"]*)")?')


def _block(name, inp, n):
    return SimpleNamespace(type="tool_use", id=f"toolu_fake_{n}", name=name, input=inp)


class FakeLLM:
    name = "fake"

    def __init__(self):
        self.n = 0
        self.template_id = None
        self.params = {}

    def bind(self, template_id: str, params: dict) -> None:
        self.template_id, self.params = template_id, params

    def _observation(self, messages):
        content = messages[-1]["content"]
        if isinstance(content, list):
            content = "\n".join(
                c["content"] if c.get("type") == "tool_result" else c.get("text", "") for c in content
            )
        return content

    def create(self, system, messages, tools):
        self.n += 1
        obs = self._observation(messages)
        url = re.search(r"^URL: (\S+)", obs, re.M).group(1)
        els = [LINE_RE.match(l) for l in obs.splitlines()]
        els = [m for m in els if m]
        param_name = tasks.TEMPLATES[self.template_id]["param"]
        value = self.params[param_name]
        field = "category" if self.template_id == "top3_in" else "q"
        want_tag = "select" if field == "category" else "input"
        inp = next(m for m in els if m.group(2) == want_tag and m.group(3).lower() in ("category", "search products"))
        submitted = parse_qs(urlparse(url).query).get(field, [""])[0].lower() == value.lower()
        table_data = re.search(r"^Table data: (.*)$", obs, re.M)
        if table_data:
            table = json.loads(table_data.group(1))
            result = tasks.FINALIZERS[self.template_id]([table], self.params)
            call = _block("done", {"result": result}, self.n)
        elif not submitted and (inp.group(4) or "").lower() != value.lower():
            call = _block("fill", {"el": int(inp.group(1)), "text": value}, self.n)
        elif not submitted:
            btn = next(m for m in els if m.group(2) == "button")
            call = _block("click", {"el": int(btn.group(1))}, self.n)
        else:
            tbl = next(m for m in els if m.group(2) == "table")
            call = _block("extract_table", {"el": int(tbl.group(1))}, self.n)
        return SimpleNamespace(
            content=[call], stop_reason="tool_use", usage=SimpleNamespace(input_tokens=900, output_tokens=60)
        )
