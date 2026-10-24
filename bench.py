"""Benchmark: 3 tasks x 10 runs, one redesign toggle, then 10 more each. Writes bench.json.

Usage: python bench.py [--fake] [--runs 10]
Run state goes to .hotpath/bench/ so it never touches the dashboard's state.
"""
import argparse
import json
import os
import socket
import statistics
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PARAMS = {
    "price_of": ["Pruning Shears", "Wireless Mouse", "Copper Kettle", "Headlamp Pro", "Gel Pen Pack",
                 "Chef Knife 8in", "Hiking Poles", "Cedar Planter Box", "Mechanical Keyboard", "Basil Seed Kit"],
    "top3_in": ["Kitchen", "Garden", "Office", "Outdoors", "Electronics"] * 2,
    "stock_for": ["Headlamp", "Kettle", "Mouse", "Skillet", "Keyboard", "Hose", "Poles", "Charger", "Planter", "Chair"],
}


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    return xs[min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))]


def summarize(runs, phase):
    rows = []
    for tier in ("interpreted", "compiled", "deopt"):
        rs = [r for r in runs if r["phase"] == phase and r["tier"] == tier]
        if not rs:
            continue
        rows.append({
            "phase": phase, "tier": tier, "runs": len(rs),
            "p50_ms": statistics.median(r["ms"] for r in rs), "p95_ms": pct([r["ms"] for r in rs], 95),
            "mean_cost": statistics.mean(r["cost"] for r in rs),
            "llm_calls_per_run": statistics.mean(r["llm_calls"] for r in rs),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="scripted LLM instead of Claude (numbers not real)")
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    os.environ["HOTPATH_HOME"] = str(ROOT / ".hotpath" / "bench")
    os.environ["HOTPATH_BASE_URL"] = f"http://127.0.0.1:{port}"
    if args.fake:
        os.environ["HOTPATH_LLM"] = "fake"

    import uvicorn

    from hotpath import store
    from hotpath.runtime import Runtime
    from hotpath.server import SITE, app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    store.reset()
    SITE["redesign"] = False
    rt = Runtime()
    runs = []
    try:
        for phase in ("before", "after"):
            if phase == "after":
                SITE["redesign"] = True
                print("--- toggled redesign ---")
            for tid, values in PARAMS.items():
                param = {"price_of": "product", "top3_in": "category", "stock_for": "term"}[tid]
                for v in values[: args.runs]:
                    r = rt.run(tid, {param: v})
                    r["phase"] = phase
                    runs.append(r)
                    tier = r["tier"] + (f"@{r['deopt_step']}" if r["tier"] == "deopt" else "")
                    print(f"{phase:6} {tid:9} {v:22} {tier:12} {r['ms']:6}ms llm={r['llm_calls']:2} "
                          f"${r['cost']:.4f} ok={r['ok']} correct={r['correct']}")
    finally:
        rt.close()
        server.should_exit = True

    after = [r for r in runs if r["phase"] == "after"]
    jitted = [r for r in runs if r["tier"] in ("compiled", "deopt")]
    interp = [r for r in runs if r["tier"] == "interpreted"]
    bench = {
        "model": "fake" if args.fake else "claude-sonnet-5-5",
        "runs_per_task_per_phase": args.runs,
        "rows": summarize(runs, "before") + summarize(runs, "after"),
        "deopt_rate": sum(r["tier"] == "deopt" for r in after) / len(after),
        "correctness_rate": sum(r["correct"] for r in jitted) / len(jitted) if jitted else None,
        "interpreted_correctness_rate": sum(r["correct"] for r in interp) / len(interp) if interp else None,
        "success_rate": sum(r["ok"] for r in runs) / len(runs),
        "total_cost": sum(r["cost"] for r in runs),
        "total_llm_calls": sum(r["llm_calls"] for r in runs),
        "all_interpreted_cost_estimate": statistics.mean(r["cost"] for r in interp) * len(runs) if interp else None,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (ROOT / "bench.json").write_text(json.dumps(bench, indent=2))

    print()
    print(f"{'phase':7}{'tier':13}{'runs':>5}{'p50':>9}{'p95':>9}{'mean $':>10}{'LLM/run':>9}")
    for row in bench["rows"]:
        print(f"{row['phase']:7}{row['tier']:13}{row['runs']:5}{row['p50_ms']:8.0f}ms{row['p95_ms']:7.0f}ms"
              f"{row['mean_cost']:10.4f}{row['llm_calls_per_run']:9.2f}")
    print(f"\ndeopt rate (after toggle): {bench['deopt_rate']:.1%}")
    print(f"correctness (compiled/deopt output == interpreted/ground truth): {bench['correctness_rate']:.1%}")
    print(f"total cost: ${bench['total_cost']:.4f} over {len(runs)} runs "
          f"(all-interpreted estimate: ${bench['all_interpreted_cost_estimate']:.4f})")
    print(f"wrote {ROOT / 'bench.json'}")


if __name__ == "__main__":
    main()
