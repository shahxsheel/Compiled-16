"""`python -m hotpath ci checks.json`: natural-language browser checks for a CI pipeline.

The spec lists checks (template + params + expected result) and may declare new lookup templates in JSON.
Compiled programs live in $HOTPATH_HOME (cache it between pipeline runs), so after the first runs a check
costs $0 and ~150 ms. A UI change deoptimizes, self-heals and is reported as a warning with the diff.

Exit code: 0 = all passed, 1 = a check failed (wrong result, run failed, or a flag with --strict).
"""
import argparse
import difflib
import json
import os
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr


def load_spec(path: str) -> dict:
    spec = json.loads(Path(path).read_text())
    from hotpath import tasks

    for tid, t in spec.get("templates", {}).items():
        tasks.register_lookup(tid, t)
    return spec


def verdict(run: dict, expect, strict: bool) -> tuple[str, str]:
    """(status, message): status is pass / warn / fail."""
    if not run["ok"]:
        return "fail", f"run failed: {run.get('error') or run.get('flag') or 'unknown error'}"
    if expect is not None and run["result"] != expect:
        return "fail", f"expected {json.dumps(expect)}, got {json.dumps(run['result'])}"
    if run.get("flag"):
        return ("fail" if strict else "warn"), f"flagged: {run['flag']}"
    if run.get("recompiled_to"):
        return "warn", f"self-healed: deopt at step {run['deopt_step']}, recompiled v{run['version']} -> v{run['recompiled_to']}"
    return "pass", ""


def junit(results: list[dict], elapsed: float) -> str:
    fails = sum(r["status"] == "fail" for r in results)
    out = [f'<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuite name="hotpath" tests="{len(results)}" failures="{fails}" time="{elapsed:.3f}">']
    for r in results:
        run = r["run"]
        out.append(f'  <testcase classname={quoteattr("hotpath." + run["template"])} name={quoteattr(r["name"])} '
                   f'time="{run["ms"] / 1000:.3f}">')
        out.append("    <properties>")
        for k in ("tier", "version", "deopt_step", "recompiled_to", "llm_calls", "cost"):
            out.append(f'      <property name="{k}" value={quoteattr(str(run.get(k)))}/>')
        out.append("    </properties>")
        if r["status"] == "fail":
            out.append(f'    <failure message={quoteattr(r["message"])}>{escape(json.dumps(run.get("result")))}</failure>')
        elif r["message"]:
            out.append(f"    <system-out>{escape(r['message'])}</system-out>")
        out.append("  </testcase>")
    out.append("</testsuite>")
    return "\n".join(out) + "\n"


def summary(results: list[dict], heals: list[dict]) -> str:
    icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
    total = sum(r["run"]["cost"] for r in results)
    compiled = sum(r["run"]["tier"] == "compiled" for r in results)
    L = ["## Hotpath checks", "",
         f"{sum(r['status'] != 'fail' for r in results)}/{len(results)} passed · {compiled} ran compiled ($0) · "
         f"total LLM cost ${total:.4f}", "",
         "| | check | tier | time | LLM calls | cost | note |", "|---|---|---|---:|---:|---:|---|"]
    for r in results:
        run = r["run"]
        tier = run["tier"] + (f" @{run['deopt_step']}" if run.get("deopt_step") is not None else "")
        L.append(f"| {icon[r['status']]} | {r['name']} | {tier} | {run['ms']} ms | {run['llm_calls']} | "
                 f"${run['cost']:.4f} | {r['message'].replace('|', '/')} |")
    for h in heals:
        L += ["", f"<details><summary>Self-healed <code>{h['template']}</code> v{h['from']} → v{h['to']}</summary>", "",
              "```diff", h["diff"].rstrip(), "```", "</details>"]
    return "\n".join(L) + "\n"


def run_checks(spec: dict, strict: bool = False, llm_factory=None, emit=None) -> tuple[list[dict], list[dict]]:
    from hotpath import compiler, hotness
    from hotpath.runtime import Runtime

    rt = Runtime(headless=os.environ.get("HOTPATH_SHOW") != "1", llm_factory=llm_factory,
                 shadow_every=spec.get("shadow_every", 0), **({"emit": emit} if emit else {}))
    results, heals = [], []
    try:
        for check in spec["checks"]:
            run = rt.run(check["template"], check["params"])
            status, msg = verdict(run, check.get("expect"), strict)
            results.append({"name": check.get("name") or f"{check['template']} {check['params']}", "run": run,
                            "status": status, "message": msg})
            if run.get("recompiled_to"):
                old = compiler.path_for(run["template"], run["version"])
                new = compiler.path_for(run["template"], run["recompiled_to"])
                diff = "".join(difflib.unified_diff(old.read_text().splitlines(True), new.read_text().splitlines(True),
                                                    fromfile=old.name, tofile=new.name))
                heals.append({"template": run["template"], "from": run["version"], "to": run["recompiled_to"], "diff": diff})
    finally:
        rt.close()
    return results, heals


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hotpath ci", description=__doc__.split("\n\n")[0])
    ap.add_argument("spec", help="checks JSON file")
    ap.add_argument("--junit", help="write JUnit XML here")
    ap.add_argument("--summary", help="write a Markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--strict", action="store_true", help="treat flagged results as failures")
    ap.add_argument("--fake", action="store_true", help="scripted LLM (offline smoke test)")
    ap.add_argument("--serve-demo", action="store_true", help="serve the bundled /shop demo site for this run")
    args = ap.parse_args(argv)

    spec = load_spec(args.spec)
    if args.fake:
        os.environ["HOTPATH_LLM"] = "fake"
    os.environ.setdefault("HOTPATH_HOME", str(Path(".hotpath") / "ci"))
    server = None
    if args.serve_demo:
        import socket
        import threading

        import uvicorn

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        os.environ["HOTPATH_BASE_URL"] = f"http://127.0.0.1:{port}"
        from hotpath.server import app

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.05)
    elif spec.get("base_url"):
        os.environ.setdefault("HOTPATH_BASE_URL", spec["base_url"])

    t0 = time.perf_counter()
    try:
        results, heals = run_checks(spec, args.strict)
    finally:
        if server:
            server.should_exit = True
    elapsed = time.perf_counter() - t0
    md = summary(results, heals)
    print(md)
    if args.junit:
        Path(args.junit).write_text(junit(results, elapsed))
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(md)
    return 1 if any(r["status"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
