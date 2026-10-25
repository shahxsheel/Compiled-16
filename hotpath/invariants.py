"""Learned value invariants (after Daikon / Auto-Validate): infer per-column patterns from interpreted runs.

Only machine-generated-looking columns get a pattern (every value has a digit and no letters): prices,
counts, ids. A value is tokenized into digit runs, letter runs and literal symbols; values that share
the same token sequence generalize to one regex. Digit runs generalize to \\d+ (small samples must not
pin lengths), except a run right after a "." keeps its exact length (the "2 decimals" of a price).
Free text (names) gets no pattern, so a learned guard can only reject a value whose *shape* changed.
"""
import re

TOKEN_RE = re.compile(r"\d+|[A-Za-z]+|\s+|.")
MIN_VALUES = 2


def _tokens(value: str) -> list[tuple[str, str]]:
    out = []
    for t in TOKEN_RE.findall(value):
        if t.isdigit():
            out.append(("D", str(len(t))))
        elif t.isalpha():
            out.append(("L", ""))
        elif t.isspace():
            out.append(("S", ""))
        else:
            out.append(("=", t))
    return out


def infer_pattern(values: list[str]) -> str | None:
    values = [str(v).strip() for v in values if str(v).strip()]
    if len(values) < MIN_VALUES:
        return None
    if not all(re.search(r"\d", v) and not re.search(r"[A-Za-z]", v) for v in values):
        return None  # free text or mixed: no pattern
    seqs = [_tokens(v) for v in values]
    shape = [[kind if kind != "D" else "D" for kind, _ in s] for s in seqs]
    if any(sh != shape[0] for sh in shape):
        return None  # values disagree on structure: not a single domain pattern
    parts = []
    for i, (kind, lit) in enumerate(seqs[0]):
        if kind == "D":
            lengths = {s[i][1] for s in seqs}
            after_dot = i > 0 and seqs[0][i - 1] == ("=", ".")
            parts.append(rf"\d{{{lengths.pop()}}}" if after_dot and len(lengths) == 1 else r"\d+")
        elif kind == "=":
            if any(s[i] != ("=", lit) for s in seqs):
                return None
            parts.append(re.escape(lit))
        elif kind == "S":
            parts.append(r"\s+")
    return "^" + "".join(parts) + "$"


def infer(observed: dict[str, list[str]]) -> dict[str, str]:
    """Column -> regex for every column with a learnable pattern."""
    out = {}
    for col, values in observed.items():
        p = infer_pattern(values)
        if p:
            out[col] = p
    return out


def observe(observed: dict[str, list[str]], tables: list[dict], cap: int = 200) -> dict[str, list[str]]:
    """Merge the rows of extracted tables into the per-column value sample."""
    for t in tables:
        for row in t.get("rows", []):
            for col, v in row.items():
                vals = observed.setdefault(col, [])
                if len(vals) < cap:
                    vals.append(str(v))
    return observed


def _leaves(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _leaves(x)
    elif isinstance(v, list):
        for x in v:
            yield from _leaves(x)
    elif v is not None:
        yield str(v).strip()


def provenance(tables: list[dict], result) -> set[str]:
    """Columns whose cell values appear in the final answer (where the answer was read from)."""
    leaves = set(_leaves(result))
    cols = set()
    for t in tables:
        for row in t.get("rows", []):
            for col, v in row.items():
                if str(v).strip() in leaves:
                    cols.add(col)
    return cols
