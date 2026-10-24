"""Runtime guards used by compiled traces."""
import re

PRICE_RE = re.compile(r"^\$?\d+(\.\d{2})?$")
EXPECTED_COLUMNS = {"name", "price", "stock"}


class GuardFailure(Exception):
    def __init__(self, step: int, reason: str):
        super().__init__(f"step {step}: {reason}")
        self.step = step
        self.reason = reason


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


def select_option(page, selector: str, text: str) -> None:
    """Choose a <select> option by its text, case-insensitively."""
    options = page.locator(f"{selector} option").all_inner_texts()
    label = next((o for o in options if o.strip().lower() == text.strip().lower()), text)
    page.select_option(selector, label=label, timeout=3000)


def check_table(step: int, table: dict | None) -> dict:
    """Expected columns present and every price well-formed."""
    if table is None:
        raise GuardFailure(step, "table not found")
    missing = EXPECTED_COLUMNS - set(table["columns"])
    if missing:
        raise GuardFailure(step, f"table missing columns {sorted(missing)}")
    for r in table["rows"]:
        if not PRICE_RE.match(r["price"]):
            raise GuardFailure(step, f"price {r['price']!r} does not match {PRICE_RE.pattern}")
    return table


def guard_table(page, step: int, selector: str) -> dict:
    from hotpath import dom

    return check_table(step, dom.extract(page, selector))
