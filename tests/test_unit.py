import ast

import pytest

from hotpath import compiler, dom, tasks, trace
from hotpath.guards import GuardFailure, check_table

FP = {"tag": "input", "role": "searchbox", "label": "Search products"}


def step(action, sel, noop=False, **args):
    return {"step": 0, "action": action, "selector": sel, "fingerprint": FP, "args": args, "noop": noop}


TRACE = [step("fill", "#q", text="Pruning Shears"), step("click", "#search-btn"), step("extract_table", "#results")]


def test_selector_canonicalization_stable_across_snapshots(rt, server_url):
    page = rt.browser.new_page()
    try:
        page.goto(f"{server_url}/shop")
        a = dom.snapshot(page)
        page.reload()
        b = dom.snapshot(page)
    finally:
        page.close()
    assert [e["selector"] for e in a] == [e["selector"] for e in b]
    sels = [e["selector"] for e in a]
    assert "#q" in sels and "#search-btn" in sels and "#results" in sels and "#category" in sels


def test_canonical_selector_falls_back_by_priority(rt):
    page = rt.browser.new_page()
    try:
        page.set_content('<input name="n1"><button data-x="go">Go</button><div class="c"><a href="#">a</a><a href="#">b</a></div>')
        sels = [e["selector"] for e in dom.snapshot(page)]
    finally:
        page.close()
    assert sels[0] == 'input[name="n1"]'
    assert sels[1] == 'button[data-x="go"]'
    assert sels[2].endswith("a:nth-of-type(1)") and sels[3].endswith("a:nth-of-type(2)")


def test_normalize_drops_noops_and_collapses_duplicates():
    raw = [step("fill", "#q", text="x"), step("fill", "#q", text="x"), step("click", "#a", noop=True),
           step("click", "#search-btn"), step("extract_table", "#results", noop=True)]
    out = trace.normalize(raw)
    assert [(s["action"], s["selector"]) for s in out] == [("fill", "#q"), ("click", "#search-btn"), ("extract_table", "#results")]
    assert [s["step"] for s in out] == [0, 1, 2]


def test_param_slotting_is_case_insensitive_and_exact():
    out = trace.slot([step("fill", "#q", text="pruning shears"), step("fill", "#x", text="Pruning")],
                     {"product": "Pruning Shears"})
    assert out[0]["args"] == {"slot": "product"}
    assert out[1]["args"] == {"text": "Pruning"}
    assert trace.signature(trace.slot(TRACE, {"product": "Pruning Shears"})) == \
        trace.signature(trace.slot([step("fill", "#q", text="Wireless Mouse")] + TRACE[1:], {"product": "Wireless Mouse"}))


def test_compiler_emits_a_guard_per_step():
    steps = trace.slot(trace.normalize(TRACE), {"product": "Pruning Shears"})
    src = compiler.generate("price_of", steps, 1, "abc")
    ast.parse(src)
    for s in steps:
        assert f"guard_element(page, {s['step']}, {s['selector']!r}" in src
    assert "guard_table(page, 2, '#results')" in src
    assert "params['product']" in src and "Pruning Shears" not in src
    assert "FINALIZERS['price_of'](tables, params)" in src
    assert "anthropic" not in src


def test_guard_failure_carries_step_index():
    with pytest.raises(GuardFailure) as e:
        check_table(2, {"columns": ["name", "stock"], "rows": []})
    assert e.value.step == 2 and "price" in e.value.reason
    with pytest.raises(GuardFailure) as e:
        check_table(5, {"columns": ["name", "price", "stock"], "rows": [{"name": "a", "price": "cheap", "stock": "1"}]})
    assert e.value.step == 5


def test_splice_produces_valid_trace():
    old = trace.normalize(TRACE)
    suffix = [dict(step("click", "#go-btn"), step=1), dict(step("extract_table", "#product-grid"), step=2)]
    out = trace.splice(old[:1], suffix)
    assert trace.is_valid(out)
    assert [s["selector"] for s in out] == ["#q", "#go-btn", "#product-grid"]


TABLE = {"columns": ["name", "price", "stock"], "rows": [
    {"name": "Cast Iron Skillet", "price": "$29.99", "stock": "40"},
    {"name": "Chef Knife 8in", "price": "$49.00", "stock": "23"},
    {"name": "Copper Kettle", "price": "$38.25", "stock": "14"},
    {"name": "Pour Over Coffee Set", "price": "$32.00", "stock": "21"},
]}


def test_finalizers_on_fixture_tables():
    f = tasks.FINALIZERS
    assert f["price_of"]([TABLE], {"product": "copper kettle"}) == {"price": "$38.25"}
    assert f["top3_in"]([TABLE], {"category": "Kitchen"}) == [
        {"name": "Cast Iron Skillet", "price": "$29.99", "stock": 40},
        {"name": "Chef Knife 8in", "price": "$49.00", "stock": 23},
        {"name": "Copper Kettle", "price": "$38.25", "stock": 14},
    ]
    assert f["stock_for"]([TABLE], {"term": "Knife"}) == {"stock": 23}
    for tid, params in [("price_of", {"product": "Nope"}), ("stock_for", {"term": "zzz"})]:
        with pytest.raises(GuardFailure):
            f[tid]([TABLE], params)
    with pytest.raises(GuardFailure):
        f["top3_in"]([{"columns": TABLE["columns"], "rows": TABLE["rows"][:2]}], {"category": "x"})
    for tid in tasks.TEMPLATES:
        assert tasks.validate(tid, f[tid]([TABLE], {"product": "Copper Kettle", "category": "K", "term": "Kettle"})) is None
