"""Simulate a CI pipeline over six builds and compare three ways to run the same 9 browser checks:

  hotpath  - `hotpath ci` with a cached state dir (compile, self-heal, flag)
  static   - the v1 compiled scripts frozen as an ordinary hand-written Playwright suite (no healing)
  llm      - an LLM agent running every check from scratch on every build

Builds: main (cold), main, PR "UI refactor" (redesign: no functional change), PR re-run, main again,
PR "breaks price formatting" (cents: a real regression the pipeline should catch).
Usage: python pipeline_sim.py [--fake] [--model claude-sonnet-5-5]   -> pipeline.json, pipeline.md
"""
import argparse
import json
import os
import shutil
import socket
import statistics
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".hotpath" / "pipeline"
SPEC = ROOT / "examples" / "shop-checks.json"
BUILDS = [("main #1 (cold cache)", "original", False), ("main #2", "original", False),
          ("PR #7: UI refactor", "redesign", False), ("PR #7 re-run", "redesign", False),
          ("main #3", "original", False), ("PR #8: breaks price formatting", "cents", True)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    args = ap.parse_args()
    if args.fake:
        os.environ["HOTPATH_LLM"] = "fake"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    os.environ["HOTPATH_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["HOTPATH_MODEL"] = args.model
    shutil.rmtree(WORK, ignore_errors=True)
    os.environ["HOTPATH_HOME"] = str(WORK / "hotpath")

    import uvicorn

    from hotpath import ci, compiler, interpreter, store
    from hotpath.guards import GuardFailure
    from hotpath.server import SITE, app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    spec = ci.load_spec(str(SPEC))

    def site(mode):
        SITE["redesign"] = mode != "original"
        SITE["mode"] = None if mode in ("original", "redesign") else mode

    # 1) Hotpath over the six builds, cache kept between builds.
    builds = []
    for name, mode, regression in BUILDS:
        site(mode)
        t0 = time.perf_counter()
        results, heals = ci.run_checks(spec)
        wall = time.perf_counter() - t0
        b = {"build": name, "mode": mode, "regression": regression, "wall_s": round(wall, 2),
             "passed": sum(r["status"] != "fail" for r in results), "failed": sum(r["status"] == "fail" for r in results),
             "self_healed": sum("self-healed" in r["message"] for r in results),
             "flagged": sum(r["message"].startswith("flagged") for r in results),
             "compiled": sum(r["run"]["tier"] == "compiled" for r in results),
             "llm_calls": sum(r["run"]["llm_calls"] for r in results), "cost": sum(r["run"]["cost"] for r in results),
             "checks": [{"name": r["name"], "status": r["status"], "tier": r["run"]["tier"], "msg": r["message"]} for r in results]}
        builds.append(b)
        print(f"{name:32} {b['passed']}/{len(results)} pass  healed={b['self_healed']} compiled={b['compiled']} "
              f"llm={b['llm_calls']} ${b['cost']:.4f} {wall:.1f}s")

    # 2) The frozen suite: the first compiled version of each template, no runtime, no healing.
    from playwright.sync_api import sync_playwright

    v1 = {tid: compiler.path_for(tid, 1) for tid in {c["template"] for c in spec["checks"]}}
    static = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for mode in ("original", "redesign", "cents"):
            site(mode)
            ok, t0 = 0, time.perf_counter()
            for c in spec["checks"]:
                page = browser.new_page()
                page.goto(f"{store.base_url()}/shop")
                try:
                    ok += compiler.load(str(v1[c["template"]])).run(page, c["params"]) == c["expect"]
                except GuardFailure:
                    pass
                finally:
                    page.close()
            static[mode] = {"passed": ok, "wall_s": round(time.perf_counter() - t0, 2)}
        # 3) LLM agent on every check, every build (measured once per site state).
        from hotpath.llm import get_llm

        llm_only = {}
        for mode in ("original", "redesign", "cents"):
            site(mode)
            ok, cost, calls, t0 = 0, 0.0, 0, time.perf_counter()
            for c in spec["checks"]:
                page = browser.new_page()
                page.goto(f"{store.base_url()}/shop")
                try:
                    res = interpreter.run(page, c["template"], c["params"], llm=get_llm())
                finally:
                    page.close()
                ok += res.ok and res.result == c["expect"]
                cost += res.cost
                calls += res.llm_calls
            llm_only[mode] = {"passed": ok, "cost": cost, "llm_calls": calls, "wall_s": round(time.perf_counter() - t0, 2)}
            print(f"llm-only on {mode:9} {ok}/9 pass ${cost:.4f} {llm_only[mode]['wall_s']}s")
        browser.close()
    server.should_exit = True
    site("original")

    n = len(spec["checks"])

    def correct_outcome(b, passed):
        """A build is handled correctly if the pipeline is green exactly when there is no regression."""
        return (passed < n) if b["regression"] else (passed == n)

    L = [f"## CI pipeline simulation ({'fake LLM' if args.fake else args.model}, {n} checks per build)", "",
         "A build is **right** when the pipeline is green with no regression and red with a real regression.", "",
         "| build | site | Hotpath | Hotpath cost / time | frozen Playwright suite | LLM agent every check | LLM cost / time |",
         "|---|---|---|---:|---|---|---:|"]
    totals = {"hotpath": [0, 0.0, 0.0], "static": [0, 0.0, 0.0], "llm": [0, 0.0, 0.0]}
    for b in builds:
        st, lo = static[b["mode"]], llm_only[b["mode"]]
        hp_ok = correct_outcome(b, b["passed"])
        st_ok = correct_outcome(b, st["passed"])
        lo_ok = correct_outcome(b, lo["passed"])
        for k, ok, cost, wall in (("hotpath", hp_ok, b["cost"], b["wall_s"]), ("static", st_ok, 0.0, st["wall_s"]),
                                  ("llm", lo_ok, lo["cost"], lo["wall_s"])):
            totals[k][0] += ok
            totals[k][1] += cost
            totals[k][2] += wall
        note = (f", {b['self_healed']} self-healed" if b["self_healed"] else "") + (f", {b['compiled']} compiled" if b["compiled"] else "")
        L.append(f"| {b['build']} | {b['mode']} | {'✅' if hp_ok else '❌'} {b['passed']}/{n} pass{note} | "
                 f"${b['cost']:.3f} / {b['wall_s']:.1f}s | {'✅' if st_ok else '❌'} {st['passed']}/{n} pass | "
                 f"{'✅' if lo_ok else '❌'} {lo['passed']}/{n} pass | ${lo['cost']:.3f} / {lo['wall_s']:.1f}s |")
    L += ["", "| over 6 builds | builds right | LLM cost | wall time |", "|---|---:|---:|---:|"]
    for k, label in (("hotpath", "Hotpath"), ("static", "Frozen Playwright suite"), ("llm", "LLM agent every check")):
        L.append(f"| {label} | {totals[k][0]}/6 | ${totals[k][1]:.3f} | {totals[k][2]:.1f}s |")
    md = "\n".join(L) + "\n"
    (ROOT / "pipeline.json").write_text(json.dumps({"model": "fake" if args.fake else args.model, "builds": builds,
                                                    "static": static, "llm_only": llm_only, "totals": totals}, indent=2))
    (ROOT / "pipeline.md").write_text(md)
    print()
    print(md)


if __name__ == "__main__":
    main()
