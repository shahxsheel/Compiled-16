"""The target site: a plain generic store at /shop with a "redesign" mode."""
from html import escape

CATEGORIES = ["Electronics", "Kitchen", "Garden", "Office", "Outdoors"]

CATALOG = [
    {"name": "Aero Desk Lamp", "price": "$34.99", "stock": 12, "category": "Office"},
    {"name": "Basil Seed Kit", "price": "$7.50", "stock": 88, "category": "Garden"},
    {"name": "Brass Garden Hose", "price": "$42.00", "stock": 5, "category": "Garden"},
    {"name": "Camp Stove Mini", "price": "$59.95", "stock": 17, "category": "Outdoors"},
    {"name": "Cast Iron Skillet", "price": "$29.99", "stock": 40, "category": "Kitchen"},
    {"name": "Cedar Planter Box", "price": "$64.00", "stock": 9, "category": "Garden"},
    {"name": "Chef Knife 8in", "price": "$49.00", "stock": 23, "category": "Kitchen"},
    {"name": "Copper Kettle", "price": "$38.25", "stock": 14, "category": "Kitchen"},
    {"name": "Down Sleeping Bag", "price": "$129.00", "stock": 6, "category": "Outdoors"},
    {"name": "Ergo Office Chair", "price": "$219.99", "stock": 3, "category": "Office"},
    {"name": "Gel Pen Pack", "price": "$6.99", "stock": 150, "category": "Office"},
    {"name": "Headlamp Pro", "price": "$24.99", "stock": 31, "category": "Outdoors"},
    {"name": "Hiking Poles", "price": "$44.50", "stock": 19, "category": "Outdoors"},
    {"name": "Mechanical Keyboard", "price": "$89.00", "stock": 27, "category": "Electronics"},
    {"name": "Noise Cancelling Headphones", "price": "$199.00", "stock": 11, "category": "Electronics"},
    {"name": "Pruning Shears", "price": "$19.99", "stock": 52, "category": "Garden"},
    {"name": "Pour Over Coffee Set", "price": "$32.00", "stock": 21, "category": "Kitchen"},
    {"name": "Standing Desk Mat", "price": "$39.99", "stock": 16, "category": "Office"},
    {"name": "USB-C Charger 65W", "price": "$45.00", "stock": 64, "category": "Electronics"},
    {"name": "Wireless Mouse", "price": "$19.99", "stock": 73, "category": "Electronics"},
]


def search(q: str = "", category: str = "") -> list[dict]:
    q = (q or "").strip().lower()
    rows = [p for p in CATALOG if q in p["name"].lower()]
    if category and category != "All":
        rows = [p for p in rows if p["category"].lower() == category.lower()]
    return sorted(rows, key=lambda p: p["name"])


STYLE = """
body { font-family: Arial, Helvetica, sans-serif; margin: 0; background: #fff; color: #222; }
header { background: #f3f3f3; border-bottom: 1px solid #ddd; padding: 12px 24px; }
header h1 { margin: 0; font-size: 22px; }
main { padding: 16px 24px; display: flex; gap: 24px; }
.content { flex: 1; }
form { margin-bottom: 12px; display: flex; gap: 8px; }
input, select, button { font-size: 14px; padding: 6px 8px; }
button { background: #e8e8e8; border: 1px solid #aaa; cursor: pointer; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
th { background: #fafafa; }
aside { width: 220px; background: #fafafa; border: 1px solid #ddd; padding: 12px; }
aside form { flex-direction: column; }
.empty { color: #777; }
"""


MODES = ["original", "redesign", "rename_all", "relabel", "cents", "swap", "decoy"]


def render(q: str = "", category: str = "", redesign: bool = False, mode: str | None = None) -> str:
    """mode overrides redesign. Adversarial modes for stress tests:
    rename_all: redesign + the search inputs renamed too (#q -> #query) so a trace breaks at step 0
    relabel:    original ids, but the submit button text changes (fingerprint mismatch only)
    cents:      prices rendered as integer cents ("1999") instead of "$19.99"
    swap:       the Price and Stock header labels are swapped (values stay put)
    decoy:      a promo table with the same columns is inserted above the results
    """
    mode = mode or ("redesign" if redesign else "original")
    rows = search(q, category)
    cat = category or "All"
    opts = "".join(
        f'<option{" selected" if c == cat else ""}>{escape(c)}</option>' for c in ["All", *CATEGORIES]
    )
    qv = escape(q or "")
    q_id, cat_id = ("query", "cat") if mode == "rename_all" else ("q", "category")
    # The form contract (q/category inputs) is stable; the submit button and table change on redesign.
    if mode not in ("redesign", "rename_all"):
        button = "Find" if mode == "relabel" else "Search"
        form = f"""<form id="search-form" class="search-bar" method="get" action="/shop">
  <input id="{q_id}" name="q" type="search" aria-label="Search products" placeholder="Search products" value="{qv}">
  <select id="{cat_id}" name="category" aria-label="Category">{opts}</select>
  <button id="search-btn" class="btn" type="submit">{button}</button>
</form>"""
        cols = ["name", "price", "stock"]
        table_attrs = 'id="results" class="results"'
    else:
        form = f"""<form id="finder" class="finder-panel" method="get" action="/shop">
  <input id="{q_id}" name="q" type="search" aria-label="Search products" placeholder="Search products" value="{qv}">
  <select id="{cat_id}" name="category" aria-label="Category">{opts}</select>
  <button id="go-btn" class="cta-primary" type="submit">Go</button>
</form>"""
        cols = ["stock", "name", "price"]
        table_attrs = 'id="product-grid" class="grid-v2"'

    def header(c):
        if mode == "swap" and c in ("price", "stock"):
            c = "stock" if c == "price" else "price"
        return c.capitalize()

    def cell(p, c):
        if mode == "cents" and c == "price":
            return p["price"].replace("$", "").replace(".", "")
        return str(p[c])

    def make_table(attrs, label, items):
        head = "".join(f"<th>{header(c)}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(cell(p, c))}</td>" for c in cols) + "</tr>" for p in items
        ) or f'<tr><td colspan="3" class="empty">No products found</td></tr>'
        return f'<table {attrs} aria-label="{label}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

    table = make_table(table_attrs, "Results", rows)
    if mode == "decoy":
        deals = [{"name": "Deal: Mystery Box", "price": "$9.99", "stock": 999, "category": ""},
                 {"name": "Deal: Gift Card", "price": "$25.00", "stock": 500, "category": ""}]
        promo = make_table('id="deals" class="results"', "Today's deals", deals)
        table = f"<h3>Today's deals</h3>{promo}<h3>Results</h3>{table}"
    if mode not in ("redesign", "rename_all"):
        layout = f'<main><div class="content">{form}{table}</div></main>'
    else:
        layout = f'<main><div class="content">{table}</div><aside><h3>Find products</h3>{form}</aside></main>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Shop</title>
<style>{STYLE}</style></head><body><header><h1>General Store</h1></header>{layout}</body></html>"""
