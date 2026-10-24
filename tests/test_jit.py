"""Integration: real browser + real site, scripted fake LLM."""
from pathlib import Path

from hotpath import hotness, store


def test_two_runs_compile_and_third_run_is_compiled(rt, fresh):
    r1 = rt.run("price_of", {"product": "Pruning Shears"})
    assert r1["tier"] == "interpreted" and r1["ok"] and hotness.compiled("price_of") is None
    r2 = rt.run("price_of", {"product": "Wireless Mouse"})
    assert r2["tier"] == "interpreted" and r2["ok"]
    entry = hotness.compiled("price_of")
    assert entry and entry["version"] == 1
    assert Path(entry["path"]) == store.compiled_dir() / "price_of_v1.py" and Path(entry["path"]).exists()
    r3 = rt.run("price_of", {"product": "Copper Kettle"})
    assert r3["tier"] == "compiled" and r3["llm_calls"] == 0 and r3["cost"] == 0
    assert r3["result"] == {"price": "$38.25"} and r3["correct"]


def test_each_template_compiles(rt, fresh):
    for tid, values in [("top3_in", ["Kitchen", "Garden", "Office"]), ("stock_for", ["Headlamp", "Kettle", "Mouse"])]:
        runs = [rt.run(tid, {"category" if tid == "top3_in" else "term": v}) for v in values]
        assert [r["tier"] for r in runs] == ["interpreted", "interpreted", "compiled"]
        assert all(r["correct"] for r in runs), runs


def test_toggle_deopts_at_step_gt_0_recompiles_v2_then_compiled_again(rt, fresh, server_url):
    import httpx

    events = []
    rt.emit = lambda kind, msg, **d: events.append((kind, msg))
    try:
        for p in ["Pruning Shears", "Wireless Mouse", "Copper Kettle"]:
            rt.run("price_of", {"product": p})
        assert hotness.compiled("price_of")["version"] == 1
        assert httpx.post(f"{server_url}/toggle").json()["redesign"] is True
        r = rt.run("price_of", {"product": "Headlamp Pro"})
        assert r["tier"] == "deopt" and r["deopt_step"] > 0, r
        assert r["ok"] and r["correct"] and r["llm_calls"] > 0
        assert any(k == "deopt" and m.startswith(f"deoptimizing at step {r['deopt_step']}: ") for k, m in events)
        entry = hotness.compiled("price_of")
        assert entry["version"] == 2 and r["recompiled_to"] == 2
        assert (store.compiled_dir() / "price_of_v2.py").exists()
        assert entry["steps"][0]["selector"] == "#q"  # prefix kept
        assert [s["selector"] for s in entry["steps"][1:]] == ["#go-btn", "#product-grid"]
        r2 = rt.run("price_of", {"product": "Gel Pen Pack"})
        assert r2["tier"] == "compiled" and r2["version"] == 2 and r2["llm_calls"] == 0
        assert r2["result"] == {"price": "$6.99"}
    finally:
        rt.emit = lambda *a, **k: None
