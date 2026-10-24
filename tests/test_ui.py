"""Playwright UI tests against the dashboard (server worker uses the fake LLM)."""
import re

import pytest

from hotpath import store
from hotpath.server import SITE


@pytest.fixture
def ui(rt, server_url, fresh):
    page = rt.browser.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Keep tests offline: serve the Google Fonts stylesheet as empty CSS.
    page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
               lambda route: route.fulfill(status=200, content_type="text/css", body=""))
    page.goto(server_url + "/")
    yield page, errors
    page.close()


def run_and_wait(page, n_rows, param=""):
    page.fill("#param", param)
    page.click("#run")
    page.wait_for_function(f"document.querySelectorAll('#runs tbody tr td.num').length >= {n_rows} * 5", timeout=20000)


def test_page_loads(ui):
    page, errors = ui
    assert page.title() == "Hotpath"
    assert page.locator("h1").inner_text() == "Hotpath"
    assert page.locator("#tier").get_attribute("data-tier") == "idle"
    assert page.locator("#template option").count() == 3
    assert errors == []


def test_run_updates_tier_and_adds_row(ui):
    page, errors = ui
    page.select_option("#template", "price_of")
    run_and_wait(page, 1, "Pruning Shears")
    page.wait_for_function("document.querySelector('#tier').dataset.tier === 'interpreted'")
    assert page.locator("#runs tbody tr").count() == 1
    assert "interpreted" in page.locator("#runs tbody tr").first.inner_text().lower()
    assert errors == []


def test_compile_toggle_deopt_and_diff(ui, server_url):
    page, errors = ui
    page.select_option("#template", "price_of")
    for i, p in enumerate(["Pruning Shears", "Wireless Mouse", "Copper Kettle"], start=1):
        run_and_wait(page, i, p)
    page.wait_for_function("document.querySelector('#tier').dataset.tier === 'compiled'")
    assert page.locator("#tier-name").inner_text().lower() == "compiled"
    assert "price_of_v1.py" in page.locator("#code-file").inner_text()
    assert "guard_element(page, 0, '#q'" in page.locator("#code").inner_text()
    assert page.locator("#stat-compiled [data-k=llm]").inner_text() == "0"

    page.click("#toggle")
    page.wait_for_function("document.querySelector('#site-state').textContent === 'redesigned'")
    run_and_wait(page, 4, "Headlamp Pro")
    page.wait_for_function("document.querySelector('#tier').dataset.tier === 'deopt'")
    assert re.search(r"deopt @ step 1", page.locator("#tier-name").inner_text(), re.I)
    assert "deoptimizing at step 1" in page.locator("#log").inner_text()
    page.wait_for_function("!document.querySelector('#tab-diff').disabled")
    page.click("#tab-diff")
    diff = page.locator("#code").inner_text()
    assert "price_of_v1.py" in diff and "price_of_v2.py" in diff
    assert page.locator("#code .add", has_text="#go-btn").count() >= 1
    assert page.locator("#code .del", has_text="#search-btn").count() >= 1
    run_and_wait(page, 5, "Gel Pen Pack")
    page.wait_for_function("document.querySelector('#tier').dataset.tier === 'compiled'")
    assert errors == []


def test_bench_table_shown_when_bench_json_exists(rt, server_url, fresh):
    import shutil

    shutil.copy(store.ROOT / "bench.json", store.home() / "bench.json")
    page = rt.browser.new_page()
    page.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
               lambda route: route.fulfill(status=200, content_type="text/css", body=""))
    try:
        page.goto(server_url + "/")
        page.wait_for_selector("#bench-section:not([hidden])")
        assert page.locator("#bench tbody tr").count() >= 3
        assert "Deopt rate" in page.locator("#bench-summary").inner_text()
    finally:
        page.close()
        (store.home() / "bench.json").unlink()
