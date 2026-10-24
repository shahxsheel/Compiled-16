import httpx

from hotpath import shop


def test_search_and_category_filter():
    assert [p["name"] for p in shop.search("mouse")] == ["Wireless Mouse"]
    assert all(p["category"] == "Kitchen" for p in shop.search("", "Kitchen"))
    assert len(shop.CATALOG) == 20


def test_shop_page_and_toggle(server_url):
    html = httpx.get(f"{server_url}/shop", params={"q": "skillet"}).text
    assert 'id="search-btn"' in html and 'id="results"' in html and "Cast Iron Skillet" in html
    assert httpx.post(f"{server_url}/toggle").json() == {"redesign": True}
    html2 = httpx.get(f"{server_url}/shop").text
    assert 'id="search-btn"' not in html2 and 'id="product-grid"' in html2
    assert html2.index("<th>Stock</th>") < html2.index("<th>Name</th>")
    assert html2.index("product-grid") < html2.index('id="q"')  # search box moved below/after table
    assert httpx.post(f"{server_url}/toggle").json() == {"redesign": False}
