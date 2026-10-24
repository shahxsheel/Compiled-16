"""FastAPI app: the /shop target site plus the Hotpath dashboard and API."""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from hotpath import shop

app = FastAPI(title="Hotpath")
SITE = {"redesign": False}


@app.get("/shop", response_class=HTMLResponse)
def shop_page(q: str = "", category: str = ""):
    return shop.render(q, category, SITE["redesign"])


@app.post("/toggle")
def toggle():
    SITE["redesign"] = not SITE["redesign"]
    return {"redesign": SITE["redesign"]}
