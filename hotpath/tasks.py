"""Task templates, output schemas, and hand-written finalizers."""
from hotpath import shop
from hotpath.guards import EXPECTED_COLUMNS, PRICE_RE, GuardFailure

SHOP_HINT = ("Be efficient: fill the search box or filter, click the submit button, "
             "call extract_table on the results table, then call done.")

TEMPLATES = {
    "price_of": {
        "param": "product",
        "goal": "Find the price of the product named '{product}'.",
        "schema": {
            "type": "object",
            "properties": {"price": {"type": "string", "description": "Price exactly as shown, e.g. $19.99"}},
            "required": ["price"],
            "additionalProperties": False,
        },
        "default": "Pruning Shears",
        "hint": SHOP_HINT,
    },
    "top3_in": {
        "param": "category",
        "goal": "Filter products by the category '{category}' and return the top 3 rows of the results table, in order.",
        "schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "price": {"type": "string"}, "stock": {"type": "integer"}},
                "required": ["name", "price", "stock"],
                "additionalProperties": False,
            },
            "minItems": 3,
            "maxItems": 3,
        },
        "default": "Kitchen",
        "hint": SHOP_HINT,
    },
    "stock_for": {
        "param": "term",
        "goal": "Search for '{term}' and return the stock count of the matching product.",
        "schema": {
            "type": "object",
            "properties": {"stock": {"type": "integer"}},
            "required": ["stock"],
            "additionalProperties": False,
        },
        "default": "Headlamp",
        "hint": SHOP_HINT,
    },
    # A real third-party site (a public scraping sandbox): no search box, key/value product table, prices in GBP.
    "book_price": {
        "param": "title",
        "start_url": "https://books.toscrape.com/",
        "goal": "Find the price (incl. tax) of the book titled '{title}'. Return it exactly as shown, e.g. £12.34.",
        "schema": {
            "type": "object",
            "properties": {"price": {"type": "string", "description": "Price incl. tax exactly as shown, e.g. £12.34"}},
            "required": ["price"],
            "additionalProperties": False,
        },
        "default": "Tipping the Velvet",
        "columns": ["price (incl. tax)"],
        "price_field": "price (incl. tax)",
        "price_re": r"^£\d+\.\d{2}$",
    },
}


def start_url(template_id: str, base_url: str) -> str:
    url = TEMPLATES[template_id].get("start_url") or "{base_url}/shop"
    return url.replace("{base_url}", base_url)


def table_spec(template_id: str) -> dict:
    """What guard_table checks for this template (defaults: the /shop table)."""
    t = TEMPLATES[template_id]
    return {"columns": t.get("columns", sorted(EXPECTED_COLUMNS)), "price_field": t.get("price_field", "price"),
            "price_re": t.get("price_re", PRICE_RE.pattern)}


def goal(template_id: str, params: dict) -> str:
    return TEMPLATES[template_id]["goal"].format(**params)


def validate(template_id: str, result) -> str | None:
    """Minimal schema check for done(). Returns an error string or None."""

    def check(schema, v, path="result"):
        t = schema["type"]
        if t == "object":
            if not isinstance(v, dict):
                return f"{path} must be an object"
            for k in schema["required"]:
                if k not in v:
                    return f"{path}.{k} is required"
            extra = set(v) - set(schema["properties"])
            if extra:
                return f"{path} has unexpected keys {sorted(extra)}"
            for k, sub in schema["properties"].items():
                if k in v and (err := check(sub, v[k], f"{path}.{k}")):
                    return err
        elif t == "array":
            if not isinstance(v, list):
                return f"{path} must be an array"
            if not (schema.get("minItems", 0) <= len(v) <= schema.get("maxItems", 10**9)):
                return f"{path} must have {schema.get('minItems')} items"
            for i, item in enumerate(v):
                if err := check(schema["items"], item, f"{path}[{i}]"):
                    return err
        elif t == "string" and not isinstance(v, str):
            return f"{path} must be a string"
        elif t == "integer" and (not isinstance(v, int) or isinstance(v, bool)):
            return f"{path} must be an integer"
        return None

    return check(TEMPLATES[template_id]["schema"], result)


def _rows(tables: list[dict]) -> list[dict]:
    if not tables:
        raise GuardFailure(-1, "finalize: no table was extracted")
    return tables[-1]["rows"]


def _stock(v: str) -> int:
    try:
        return int(str(v).replace(",", ""))
    except ValueError:
        raise GuardFailure(-1, f"finalize: stock {v!r} is not an integer", kind="semantic")


def finalize_price_of(tables, params):
    want = params["product"].strip().lower()
    for r in _rows(tables):
        if r.get("name", "").strip().lower() == want:
            return {"price": r["price"]}
    raise GuardFailure(-1, f"finalize: no row named {params['product']!r}")


def finalize_top3_in(tables, params):
    rows = _rows(tables)
    if len(rows) < 3:
        raise GuardFailure(-1, f"finalize: expected 3 rows, got {len(rows)}")
    return [{"name": r["name"], "price": r["price"], "stock": _stock(r["stock"])} for r in rows[:3]]


def finalize_stock_for(tables, params):
    want = params["term"].strip().lower()
    for r in _rows(tables):
        if want in r.get("name", "").lower():
            return {"stock": _stock(r["stock"])}
    raise GuardFailure(-1, f"finalize: no row matching {params['term']!r}")


def finalize_book_price(tables, params):
    rows = _rows(tables)
    if not rows or "price (incl. tax)" not in rows[0]:
        raise GuardFailure(-1, "finalize: no 'price (incl. tax)' in the extracted table")
    return {"price": rows[0]["price (incl. tax)"]}


FINALIZERS = {"price_of": finalize_price_of, "top3_in": finalize_top3_in, "stock_for": finalize_stock_for,
              "book_price": finalize_book_price}


def ground_truth(template_id: str, params: dict):
    """Expected answer computed straight from the catalog (used by bench/tests). None if unknown."""
    if template_id not in ("price_of", "top3_in", "stock_for"):
        return None
    if template_id == "price_of":
        rows = [p for p in shop.CATALOG if p["name"].lower() == params["product"].lower()]
        return {"price": rows[0]["price"]} if rows else None
    if template_id == "top3_in":
        rows = shop.search("", params["category"])[:3]
        return [{"name": p["name"], "price": p["price"], "stock": p["stock"]} for p in rows]
    rows = shop.search(params["term"])
    return {"stock": rows[0]["stock"]} if rows else None


def register_lookup(template_id: str, spec: dict) -> None:
    """Declare a task without Python: find the table row whose `match_column` equals (or contains) the param,
    return `return_columns` (ints for `int_columns`). Used by `hotpath ci` specs."""
    param, match_col = spec["param"], spec["match_column"]
    ret, ints = list(spec["return_columns"]), set(spec.get("int_columns", []))
    contains = spec.get("match", "equals") == "contains"

    def finalize(tables, params):
        want = str(params[param]).strip().lower()
        for r in _rows(tables):
            cell = str(r.get(match_col, "")).strip().lower()
            if (want in cell) if contains else (cell == want):
                return {c: _stock(r[c]) if c in ints else r[c] for c in ret}
        raise GuardFailure(-1, f"finalize: no row whose {match_col} {'contains' if contains else 'is'} {params[param]!r}")

    TEMPLATES[template_id] = {
        "param": param,
        "goal": spec["goal"],
        "start_url": spec.get("start_url", "{base_url}/shop"),
        "hint": spec.get("hint", ""),
        "default": spec.get("default", ""),
        "schema": {
            "type": "object",
            "properties": {c: {"type": "integer" if c in ints else "string"} for c in ret},
            "required": ret,
            "additionalProperties": False,
        },
        "columns": [match_col, *ret],
        "price_field": spec.get("price_field"),
        "price_re": spec.get("price_re"),
    }
    FINALIZERS[template_id] = finalize
