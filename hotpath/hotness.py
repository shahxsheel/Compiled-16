"""Hotness counting (hot.json) and the registry of compiled versions."""
from hotpath import store, trace

HOT_N = 2


def _load() -> dict:
    return store.load("hot.json", {"templates": {}, "compiled": {}})


def record(template_id: str, raw_steps: list[dict], params: dict) -> tuple[list[dict] | None, dict]:
    """Count a successful run. Returns (steps to compile or None, info)."""
    hot = _load()
    steps = trace.slot(trace.normalize(raw_steps), params)
    sig = trace.signature(steps)
    t = hot["templates"].setdefault(template_id, {"counts": {}, "traces": {}, "successes": 0})
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


def set_compiled(template_id: str, version: int, path: str, steps: list[dict], sig: str) -> None:
    hot = _load()
    prev = hot["compiled"].get(template_id)
    hot["compiled"][template_id] = {"version": version, "path": path, "steps": steps, "sig": sig,
                                    "prev_path": prev["path"] if prev else None}
    store.save("hot.json", hot)
