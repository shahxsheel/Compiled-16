"""Task templates, output schemas, and hand-written finalizers."""
from hotpath import shop
from hotpath.guards import GuardFailure

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
    },
}


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
        raise GuardFailure(-1, f"finalize: stock {v!r} is not an integer")


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


FINALIZERS = {"price_of": finalize_price_of, "top3_in": finalize_top3_in, "stock_for": finalize_stock_for}


def ground_truth(template_id: str, params: dict):
    """Expected answer computed straight from the catalog (used by bench/tests)."""
    if template_id == "price_of":
        rows = [p for p in shop.CATALOG if p["name"].lower() == params["product"].lower()]
        return {"price": rows[0]["price"]} if rows else None
    if template_id == "top3_in":
        rows = shop.search("", params["category"])[:3]
        return [{"name": p["name"], "price": p["price"], "stock": p["stock"]} for p in rows]
    rows = shop.search(params["term"])
    return {"stock": rows[0]["stock"]} if rows else None
