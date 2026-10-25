"""Runtime guards used by compiled traces."""
import re
import time

PRICE_RE = re.compile(r"^\$?\d+(\.\d{2})?$")
EXPECTED_COLUMNS = {"name", "price", "stock"}


class GuardFailure(Exception):
    """kind="structure": the page no longer matches the trace (deopt + splice + recompile).
    kind="semantic": the page matches but its values broke a learned invariant (deopt, answer flagged).
    kind="input": the page is fine but this run's param is not where the trace leads (side exit, keep the code)."""

    def __init__(self, step: int, reason: str, kind: str = "structure"):
        super().__init__(f"step {step}: {reason}")
        self.step = step
        self.reason = reason
        self.kind = kind


def guard_element(page, step: int, selector: str, fingerprint: dict) -> None:
    """Selector must be visible within 1s and its fingerprint must match."""
    from hotpath import dom

    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=1000)
    except Exception:
        raise GuardFailure(step, f"selector {selector} not visible within 1s")
    current = next((e for e in dom.snapshot(page) if e["selector"] == selector), None)
    if current is None:
        raise GuardFailure(step, f"selector {selector} no longer canonical")
    got = dom.fingerprint(current)
    if got != fingerprint:
        diff = {k: got[k] for k in fingerprint if got.get(k) != fingerprint[k]}
        raise GuardFailure(step, f"fingerprint mismatch on {selector}: {diff}")


def find_by_label(page, step: int, tag: str, role: str, text: str) -> str:
    """Guard + resolve a param-targeted element: the visible <tag> with this role whose label equals text."""
    from hotpath import dom

    want = text.strip().lower()
    deadline = time.monotonic() + 1.0
    while True:
        for e in dom.snapshot(page):
            if e["tag"] == tag and e["role"] == role and e["label"].strip().lower() == want:
                return e["selector"]
        if time.monotonic() > deadline:
            raise GuardFailure(step, f"no visible {tag} labelled {text!r} within 1s", kind="input")
        time.sleep(0.1)


def select_option(page, selector: str, text: str) -> None:
    """Choose a <select> option by its text, case-insensitively."""
    options = page.locator(f"{selector} option").all_inner_texts()
    label = next((o for o in options if o.strip().lower() == text.strip().lower()), text)
    page.select_option(selector, label=label, timeout=3000)


def check_table(step: int, table: dict | None, columns=EXPECTED_COLUMNS, price_field="price", price_re=PRICE_RE,
                invariants: dict | None = None) -> dict:
    """Expected columns present, every price well-formed, and every learned value invariant holds."""
    if table is None:
        raise GuardFailure(step, "table not found")
    missing = set(columns) - set(table["columns"])
    if missing:
        raise GuardFailure(step, f"table missing columns {sorted(missing)}")
    pattern = re.compile(price_re) if isinstance(price_re, str) else price_re
    for r in table["rows"] if price_field and pattern else []:
        if not pattern.match(r[price_field]):
            raise GuardFailure(step, f"{price_field} {r[price_field]!r} does not match {pattern.pattern}")
    for col, pat in (invariants or {}).items():
        for r in table["rows"]:
            if col in r and not re.match(pat, r[col]):
                raise GuardFailure(step, f"learned invariant: {col} {r[col]!r} !~ {pat}", kind="semantic")
    return table


def guard_table(page, step: int, selector: str, **spec) -> dict:
    from hotpath import dom

    return check_table(step, dom.extract(page, selector), **spec)
