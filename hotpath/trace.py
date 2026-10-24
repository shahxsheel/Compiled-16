"""Trace utilities: normalization, param slotting, signatures, splicing."""
import hashlib
import json

REQUIRED = ("action", "selector", "fingerprint", "args")


def _key(s: dict) -> tuple:
    return (s["action"], s["selector"], json.dumps(s.get("args", {}), sort_keys=True))


def renumber(steps: list[dict], start: int = 0) -> list[dict]:
    return [dict(s, step=start + i) for i, s in enumerate(steps)]


def normalize(steps: list[dict]) -> list[dict]:
    """Drop no-op steps (no URL/DOM/focus change) and collapse consecutive duplicates."""
    out = []
    for s in steps:
        if s.get("noop") and s["action"] != "extract_table":
            continue
        if out and _key(out[-1]) == _key(s):
            continue
        out.append(s)
    return renumber(out)


def slot(steps: list[dict], params: dict) -> list[dict]:
    """Replace fill text that equals a param value (case-insensitive) with a named slot."""
    out = []
    for s in steps:
        args = dict(s.get("args", {}))
        if s["action"] == "fill" and "text" in args:
            for name, value in params.items():
                if str(args["text"]).strip().lower() == str(value).strip().lower():
                    args = {"slot": name}
                    break
        out.append(dict(s, args=args))
    return out


def unslot(steps: list[dict], params: dict) -> list[dict]:
    return [dict(s, args={"text": params[s["args"]["slot"]]}) if "slot" in s.get("args", {}) else s for s in steps]


def signature(steps: list[dict]) -> str:
    shape = [[s["action"], s["selector"], s.get("args", {})] for s in steps]
    return hashlib.sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:10]


def is_valid(steps: list[dict]) -> bool:
    return all(all(k in s for k in REQUIRED) for s in steps) and [s["step"] for s in steps] == list(range(len(steps)))


def splice(prefix: list[dict], suffix: list[dict]) -> list[dict]:
    """Steps 0..k-1 from the old trace + the interpreter's new suffix, renumbered and normalized."""
    return normalize(list(prefix) + list(suffix))
