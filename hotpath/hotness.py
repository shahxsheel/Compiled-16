"""Hotness counting (hot.json) and the registry of compiled versions."""
from hotpath import invariants, store, trace

HOT_N = 2


def _load() -> dict:
    return store.load("hot.json", {"templates": {}, "compiled": {}})


def record(template_id: str, raw_steps: list[dict], params: dict, tables: list[dict] | None = None,
           result=None) -> tuple[list[dict] | None, dict]:
    """Count a successful run, sample its extracted values and note which columns fed the answer.
    Returns (steps to compile or None, info)."""
    hot = _load()
    steps = trace.slot(trace.normalize(raw_steps), params)
    sig = trace.signature(steps)
    t = hot["templates"].setdefault(template_id, {"counts": {}, "traces": {}, "successes": 0})
    invariants.observe(t.setdefault("observed", {}), tables or [])
    t["relevant"] = sorted(set(t.get("relevant", [])) | invariants.provenance(tables or [], result))
    t["counts"][sig] = t["counts"].get(sig, 0) + 1
    t["traces"].setdefault(sig, steps)
    t["successes"] += 1
    store.save("hot.json", hot)
    info = {"sig": sig, "count": t["counts"][sig], "successes": t["successes"], "compile_sig": sig}
    if template_id in hot["compiled"]:
        return None, info
    if t["counts"][sig] >= HOT_N:
        return steps, info
    if t["successes"] >= 3:
        shortest = min(t["traces"], key=lambda s: len(t["traces"][s]))
        info["compile_sig"] = shortest
        return t["traces"][shortest], info
    return None, info


def compiled(template_id: str) -> dict | None:
    return _load()["compiled"].get(template_id)


MAX_VARIANTS = 4


def set_compiled(template_id: str, version: int, path: str, steps: list[dict], sig: str) -> None:
    """Install a new active version; the previous ones stay cached as variants (a polymorphic cache)."""
    hot = _load()
    prev = hot["compiled"].get(template_id)
    variants = []
    if prev:
        variants = [{k: prev[k] for k in ("version", "path", "steps", "sig")}] + prev.get("variants", [])
    hot["compiled"][template_id] = {"version": version, "path": path, "steps": steps, "sig": sig,
                                    "prev_path": prev["path"] if prev else None,
                                    "variants": variants[: MAX_VARIANTS - 1]}
    store.save("hot.json", hot)


def promote(template_id: str, version: int) -> None:
    """Make a cached variant the active version again (e.g. the pipeline switched back to another branch)."""
    hot = _load()
    cur = hot["compiled"][template_id]
    alt = next(v for v in cur.get("variants", []) if v["version"] == version)
    rest = [v for v in cur["variants"] if v["version"] != version]
    hot["compiled"][template_id] = {**alt, "prev_path": cur["path"],
                                    "variants": [{k: cur[k] for k in ("version", "path", "steps", "sig")}] + rest}
    store.save("hot.json", hot)


def learned_invariants(template_id: str) -> dict:
    """Invariants for the columns the answer is actually read from."""
    t = _load()["templates"].get(template_id, {})
    relevant = set(t.get("relevant", []))
    return {c: p for c, p in invariants.infer(t.get("observed", {})).items() if c in relevant}


def backoff(template_id: str, reason: str = "") -> int:
    """A deopt that could not change the trace: skip compiled code for a doubling number of runs (2, 4, ... 16)."""
    hot = _load()
    e = hot["compiled"][template_id]
    e["backoff_reason"] = reason
    e["backoff"] = min(16, max(2, 2 * e.get("backoff", 0)))
    e["backoff_left"] = e["backoff"]
    store.save("hot.json", hot)
    return e["backoff"]


def take_backoff(template_id: str) -> bool:
    """True (and consume one) if this run should skip compiled code."""
    hot = _load()
    e = hot["compiled"].get(template_id)
    if not e or e.get("backoff_left", 0) <= 0:
        return False
    e["backoff_left"] -= 1
    store.save("hot.json", hot)
    return True


def clear_backoff(template_id: str) -> None:
    hot = _load()
    e = hot["compiled"].get(template_id)
    if e and (e.get("backoff") or e.get("backoff_left")):
        e["backoff"] = e["backoff_left"] = 0
        store.save("hot.json", hot)


def invalidate(template_id: str) -> None:
    """Drop the compiled version and the hotness counts; values already observed are kept."""
    hot = _load()
    hot["compiled"].pop(template_id, None)
    t = hot["templates"].get(template_id)
    if t:
        t["counts"], t["traces"], t["successes"] = {}, {}, 0
    store.save("hot.json", hot)
