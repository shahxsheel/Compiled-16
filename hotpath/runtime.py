"""Runtime: picks a tier for each run, records metrics and traces."""
import time
import uuid

from hotpath import compiler, hotness, interpreter, store, tasks, trace
from hotpath.guards import GuardFailure


def _noop_emit(kind, msg, **data):
    pass


class Runtime:
    """Owns one Playwright browser. Not thread-safe: use from a single thread."""

    def __init__(self, headless: bool = True, llm_factory=None, emit=_noop_emit):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=headless)
        self.llm_factory = llm_factory
        self.emit = emit

    def close(self):
        self.browser.close()
        self._pw.stop()

    def _new_page(self):
        page = self.browser.new_page()
        page.goto(f"{store.base_url()}/shop")
        return page

    def run(self, template_id: str, params: dict | None = None) -> dict:
        params = params or {tasks.TEMPLATES[template_id]["param"]: tasks.TEMPLATES[template_id]["default"]}
        run = {"id": uuid.uuid4().hex[:8], "template": template_id, "params": params, "ts": time.time(),
               "tier": "interpreted", "deopt_step": None, "version": None, "llm_calls": 0,
               "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "ok": False, "result": None, "error": ""}
        self.emit("run_start", f"run {run['id']}: {template_id} {params}", run=run)
        t0 = time.perf_counter()
        page = self._new_page()
        try:
            entry = hotness.compiled(template_id)
            if entry:
                self._run_compiled(page, run, entry)
            else:
                res = self._interpret(page, run)
                if res.ok:
                    self._maybe_compile(run, res)
        finally:
            page.close()
        run["ms"] = round((time.perf_counter() - t0) * 1000)
        run["correct"] = run["ok"] and run["result"] == tasks.ground_truth(template_id, params)
        store.append_run(run)
        self.emit("run_end", f"run {run['id']} {run['tier']} ok={run['ok']} {run['ms']}ms "
                  f"llm_calls={run['llm_calls']} cost=${run['cost']:.4f}", run=run)
        return run

    def _run_compiled(self, page, run, entry):
        run["tier"], run["version"] = "compiled", entry["version"]
        self.emit("tier", f"COMPILED v{entry['version']}: {entry['path']}", tier="compiled")
        mod = compiler.load(entry["path"])
        try:
            run["result"] = mod.run(page, run["params"])
            run["ok"] = True
            run["trace"] = [{k: s[k] for k in ("step", "action", "selector", "args")} for s in entry["steps"]]
        except GuardFailure as g:
            self._deopt(page, run, entry, g)

    def _deopt(self, page, run, entry, g: GuardFailure):
        k = g.step
        run["tier"], run["deopt_step"] = "deopt", k
        self.emit("deopt", f"deoptimizing at step {k}: {g.reason}", tier="deopt", step=k)
        prefix = entry["steps"][:k]
        res = self._interpret(page, run, completed_steps=trace.unslot(prefix, run["params"]))
        if not res.ok:
            self.emit("error", f"deopt interpreter failed: {res.error}")
            return
        suffix = trace.slot(res.trace, run["params"])
        steps = trace.splice(prefix, suffix)
        self.emit("splice", f"spliced steps 0..{k - 1} + {len(suffix)} new step(s) -> {len(steps)} steps")
        run["trace"] = [{k_: s[k_] for k_ in ("step", "action", "selector", "args")} for s in steps]
        run["recompiled_to"] = self._compile(run["template"], steps, trace.signature(steps))

    def _maybe_compile(self, run, res):
        steps, info = hotness.record(run["template"], res.trace, run["params"])
        self.emit("hot", f"{run['template']} signature {info['sig']} seen {info['count']}x "
                  f"({info['successes']} successful runs)")
        if steps is not None:
            self._compile(run["template"], steps, info["sig"])

    def _compile(self, template_id, steps, sig):
        prev = hotness.compiled(template_id)
        version = (prev["version"] if prev else 0) + 1
        path = compiler.compile_trace(template_id, steps, version, sig)
        hotness.set_compiled(template_id, version, str(path), steps, sig)
        self.emit("compiled", f"compiled {template_id} -> {path.name} ({len(steps)} steps)",
                  template=template_id, version=version)
        return version

    def _interpret(self, page, run, completed_steps=None):
        llm = self.llm_factory() if self.llm_factory else None
        res = interpreter.run(page, run["template"], run["params"], llm=llm, emit=self.emit,
                              completed_steps=completed_steps)
        run["llm_calls"] += res.llm_calls
        run["tokens_in"] += res.tokens_in
        run["tokens_out"] += res.tokens_out
        run["cost"] = round(run["cost"] + res.cost, 6)
        if completed_steps is None:
            run["trace"] = [{k: s[k] for k in ("step", "action", "selector", "args")} for s in res.trace]
        run["ok"], run["result"], run["error"] = res.ok, res.result, res.error
        return res
