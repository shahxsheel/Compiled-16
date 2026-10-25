"""Runtime: picks a tier for each run, records metrics and traces."""
import os
import time
import uuid

from hotpath import compiler, hotness, interpreter, store, tasks, trace
from hotpath.guards import GuardFailure


def _noop_emit(kind, msg, **data):
    pass


def _same_code(a: list[dict], b: list[dict]) -> bool:
    """Would these traces compile to identical code (selectors, args and guard fingerprints)?"""
    key = lambda s: (s["action"], s["selector"], s.get("args"), s.get("fingerprint"))
    return [key(s) for s in a] == [key(s) for s in b]


class Runtime:
    """Owns one Playwright browser. Not thread-safe: use from a single thread.

    shadow_every=N re-runs the interpreter on every Nth successful compiled run and compares answers
    (a sampled check function); a mismatch flags the run and invalidates the compiled version.
    """

    def __init__(self, headless: bool = True, llm_factory=None, emit=_noop_emit, shadow_every: int | None = None):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=headless)
        self.llm_factory = llm_factory
        self.emit = emit
        self.shadow_every = int(os.environ.get("HOTPATH_SHADOW_EVERY", "0")) if shadow_every is None else shadow_every
        self._compiled_ok = 0

    def close(self):
        self.browser.close()
        self._pw.stop()

    def _new_page(self, template_id: str):
        page = self.browser.new_page()
        page.goto(tasks.start_url(template_id, store.base_url()))
        return page

    def run(self, template_id: str, params: dict | None = None) -> dict:
        params = params or {tasks.TEMPLATES[template_id]["param"]: tasks.TEMPLATES[template_id]["default"]}
        run = {"id": uuid.uuid4().hex[:8], "template": template_id, "params": params, "ts": time.time(),
               "tier": "interpreted", "deopt_step": None, "version": None, "llm_calls": 0,
               "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "ok": False, "result": None, "error": "",
               "flag": None, "shadow": None}
        self.emit("run_start", f"run {run['id']}: {template_id} {params}", run=run)
        t0 = time.perf_counter()
        page = self._new_page(template_id)
        try:
            entry = hotness.compiled(template_id)
            if entry and hotness.take_backoff(template_id):
                run["backoff"] = True
                run["flag"] = f"compiled v{entry['version']} suspended after an unfixable guard failure: {entry.get('backoff_reason')}"
                self.emit("backoff", f"{template_id}: compiled v{entry['version']} is backing off; interpreting")
                self._interpret(page, run)
            elif entry:
                self._run_compiled(page, run, entry)
            else:
                res = self._interpret(page, run)
                if res.ok:
                    self._maybe_compile(run, res)
        finally:
            page.close()
        run["ms"] = round((time.perf_counter() - t0) * 1000)
        if run["tier"] == "compiled" and run["ok"]:
            self._maybe_shadow(run)
        truth = tasks.ground_truth(template_id, params)
        run["correct"] = None if truth is None else (run["ok"] and run["result"] == truth)
        store.append_run(run)
        self.emit("run_end", f"run {run['id']} {run['tier']} ok={run['ok']} {run['ms']}ms "
                  f"llm_calls={run['llm_calls']} cost=${run['cost']:.4f}" + (f" FLAG: {run['flag']}" if run["flag"] else ""),
                  run=run)
        return run

    def _run_compiled(self, page, run, entry):
        run["tier"], run["version"] = "compiled", entry["version"]
        self.emit("tier", f"COMPILED v{entry['version']}: {entry['path']}", tier="compiled")
        mod = compiler.load(entry["path"])
        try:
            run["result"] = mod.run(page, run["params"])
            run["ok"] = True
            run["trace"] = [{k: s[k] for k in ("step", "action", "selector", "args")} for s in entry["steps"]]
            hotness.clear_backoff(run["template"])
        except GuardFailure as g:
            if g.kind == "input":
                self._side_exit(run, entry, g)
            elif g.kind == "structure" and self._try_variants(run, entry, g):
                return
            else:
                self._deopt(page, run, entry, g)

    def _try_variants(self, run, entry, g: GuardFailure) -> bool:
        """Polymorphic cache: before deoptimizing, try the other cached versions on a fresh page ($0)."""
        for alt in entry.get("variants", []):
            page = self._new_page(run["template"])
            try:
                result = compiler.load(alt["path"]).run(page, run["params"])
            except GuardFailure:
                continue
            finally:
                page.close()
            hotness.promote(run["template"], alt["version"])
            run.update(result=result, ok=True, version=alt["version"], switched_from=entry["version"],
                       trace=[{k: s[k] for k in ("step", "action", "selector", "args")} for s in alt["steps"]])
            self.emit("variant", f"v{entry['version']} failed at step {g.step} ({g.reason}); cached v{alt['version']} "
                      f"fits this page: switched without the LLM")
            return True
        return False

    def _side_exit(self, run, entry, g: GuardFailure):
        """The site still matches the trace but this input is elsewhere: interpret from the start, keep the code."""
        run["tier"], run["deopt_step"] = "fallback", g.step
        self.emit("side_exit", f"side exit at step {g.step}: {g.reason}; interpreting from the start, "
                  f"keeping v{entry['version']}", tier="fallback", step=g.step)
        page = self._new_page(run["template"])
        try:
            self._interpret(page, run)
        finally:
            page.close()

    def _deopt(self, page, run, entry, g: GuardFailure):
        k = g.step
        run["tier"], run["deopt_step"] = "deopt", k
        if g.kind == "semantic":
            run["flag"] = f"data drift at step {k}: {g.reason}"
        self.emit("deopt", f"deoptimizing at step {k}: {g.reason}", tier="deopt", step=k)
        prefix = entry["steps"][:k]
        res = self._interpret(page, run, completed_steps=trace.unslot(prefix, run["params"]))
        if not res.ok:
            n = hotness.backoff(run["template"], f"{g.reason}; the interpreter could not finish either")
            run["backed_off"] = n
            run["flag"] = run["flag"] or f"deopt at step {k} failed: {res.error}"
            self.emit("error", f"deopt interpreter failed: {res.error}; interpreting the next {n} runs")
            return
        suffix = trace.slot(res.trace, run["params"])
        steps = trace.splice(prefix, suffix)
        self.emit("splice", f"spliced steps 0..{k - 1} + {len(suffix)} new step(s) -> {len(steps)} steps")
        run["trace"] = [{k_: s[k_] for k_ in ("step", "action", "selector", "args")} for s in steps]
        if _same_code(steps, entry["steps"]):
            # Recompiling would emit the same code and fail the same guard: back off instead (tracing-JIT style).
            n = hotness.backoff(run["template"], g.reason)
            run["backed_off"] = n
            self.emit("backoff", f"trace unchanged after deopt: not recompiling; interpreting the next {n} runs "
                      f"of {run['template']} before retrying v{entry['version']}")
            return
        run["recompiled_to"] = self._compile(run["template"], steps, trace.signature(steps))

    def _maybe_compile(self, run, res):
        steps, info = hotness.record(run["template"], res.trace, run["params"], res.tables, res.result)
        self.emit("hot", f"{run['template']} signature {info['sig']} seen {info['count']}x "
                  f"({info['successes']} successful runs)")
        if steps is not None:
            run["compiled_after"] = self._compile(run["template"], steps, info["compile_sig"])

    def _compile(self, template_id, steps, sig):
        prev = hotness.compiled(template_id)
        version = (prev["version"] if prev else 0) + 1
        learned = {} if os.environ.get("HOTPATH_NO_INVARIANTS") else hotness.learned_invariants(template_id)
        path = compiler.compile_trace(template_id, steps, version, sig, learned)
        hotness.set_compiled(template_id, version, str(path), steps, sig)
        self.emit("compiled", f"compiled {template_id} -> {path.name} ({len(steps)} steps"
                  + (f", learned guards: {', '.join(f'{c} ~ {p}' for c, p in learned.items())}" if learned else "") + ")",
                  template=template_id, version=version)
        return version

    def _maybe_shadow(self, run):
        """Sampled check function: re-derive the answer with the interpreter and compare field by field."""
        self._compiled_ok += 1
        if not self.shadow_every or self._compiled_ok % self.shadow_every:
            return
        page = self._new_page(run["template"])
        t0 = time.perf_counter()
        try:
            llm = self.llm_factory() if self.llm_factory else None
            res = interpreter.run(page, run["template"], run["params"], llm=llm)
        finally:
            page.close()
        match = res.ok and res.result == run["result"]
        run["shadow"] = {"match": match, "interpreted": res.result, "cost": round(res.cost, 6),
                         "llm_calls": res.llm_calls, "ms": round((time.perf_counter() - t0) * 1000)}
        if match:
            self.emit("shadow", f"shadow check ok: interpreter agrees with compiled v{run['version']}")
        else:
            run["flag"] = f"shadow mismatch: compiled {run['result']} vs interpreted {res.result}"
            hotness.invalidate(run["template"])
            self.emit("shadow", f"shadow MISMATCH: compiled {run['result']} vs interpreted {res.result}; "
                      f"invalidated v{run['version']}, {run['template']} goes back to the interpreter")

    def _interpret(self, page, run, completed_steps=None):
        llm = self.llm_factory() if self.llm_factory else None
        res = interpreter.run(page, run["template"], run["params"], llm=llm, emit=self.emit,
                              completed_steps=completed_steps)
        run["model"] = res.model
        run["llm_calls"] += res.llm_calls
        run["tokens_in"] += res.tokens_in
        run["tokens_out"] += res.tokens_out
        run["cost"] = round(run["cost"] + res.cost, 6)
        if completed_steps is None:
            run["trace"] = [{k: s[k] for k in ("step", "action", "selector", "args")} for s in res.trace]
        run["ok"], run["result"], run["error"] = res.ok, res.result, res.error
        return res
