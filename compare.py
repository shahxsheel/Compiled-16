"""Live comparison across models: shop benchmark, stress-test redesigns, and a real third-party site.

Usage: python compare.py [--models claude-sonnet-5-5 claude-sonnet-4-6] [--runs 10]
Writes compare.json and compare.md. Run state goes to .hotpath/compare/ (never touches the demo).
"""
import argparse
import html
import json
import os
import re
import shutil
import socket
import statistics
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".hotpath" / "compare"

STRESS_MODES = ["redesign", "rename_all", "relabel", "cents", "swap", "decoy"]
STRESS_TASKS = [("price_of", "product", ["Copper Kettle", "Gel Pen Pack"]), ("stock_for", "term", ["Mouse", "Skillet"])]
BOOKS = ["Tipping the Velvet", "Soumission", "Sharp Objects", "Sapiens: A Brief History of Humankind",
         "The Requiem Red", "In Her Wake", "a light in the attic", "How Music Works", "Soumission"]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))] if xs else None


def book_truth() -> dict:
    import httpx

    truth = {}
    for url in ("https://books.toscrape.com/", "https://books.toscrape.com/catalogue/page-2.html"):
        src = httpx.get(url, timeout=20).text
        titles = re.findall(r'<h3><a href="[^"]+" title="([^"]+)"', src)
        prices = re.findall(r'<p class="price_color">([^<]+)</p>', src)
        truth.update({html.unescape(t).lower(): p for t, p in zip(titles, prices)})
    return truth


class Harness:
    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        os.environ["HOTPATH_BASE_URL"] = f"http://127.0.0.1:{port}"
        os.environ["HOTPATH_HOME"] = str(WORK / "boot")
        import uvicorn

        from hotpath.runtime import Runtime
        from hotpath.server import SITE, app

        self.SITE = SITE
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=self.server.run, daemon=True).start()
        while not self.server.started:
            time.sleep(0.05)
        self.events = []
        self.rt = Runtime(emit=lambda kind, msg, **d: self.events.append((kind, msg)))

    def home(self, path: Path, reset=True):
        from hotpath import store

        os.environ["HOTPATH_HOME"] = str(path)
        if reset:
            store.reset()

    def mode(self, name: str):
        self.SITE["redesign"] = name != "original"
        self.SITE["mode"] = None if name in ("original", "redesign") else name

    def run(self, template_id, params, **tags):
        self.events.clear()
        t0 = time.perf_counter()
        try:
            r = self.rt.run(template_id, params)
        except Exception as e:  # keep the suite going; count it as a failed run
            r = {"template": template_id, "params": params, "tier": "error", "deopt_step": None, "ok": False,
                 "correct": False, "result": None, "error": f"{type(e).__name__}: {e}", "llm_calls": 0, "cost": 0.0,
                 "ms": round((time.perf_counter() - t0) * 1000)}
        reason = next((m for k, m in self.events if k in ("deopt", "side_exit")), "")
        r.update(tags, reason=reason)
        tier = r["tier"] + (f"@{r['deopt_step']}" if r["deopt_step"] is not None else "")
        print(f"  {str(tags):60.60} {template_id:10} {str(list(params.values())[0])[:26]:26} {tier:13} "
              f"{r['ms']:6}ms llm={r['llm_calls']:2} ${r['cost']:.4f} correct={r['correct']} {reason[:60]}")
        return r

    def close(self):
        self.rt.close()
        self.server.should_exit = True


def suite_shop(h, model, runs_per):
    from bench import PARAMS

    h.home(WORK / model / "shop")
    h.mode("original")
    out = []
    for phase in ("before", "after"):
        if phase == "after":
            h.mode("redesign")
        for tid, values in PARAMS.items():
            param = {"price_of": "product", "top3_in": "category", "stock_for": "term"}[tid]
            for v in values[:runs_per]:
                out.append(h.run(tid, {param: v}, suite="shop", phase=phase))
    return out


def suite_stress(h, model):
    out = []
    base = WORK / model / "stress"
    h.home(base)
    h.mode("original")
    for tid, param, _ in STRESS_TASKS:  # warm up: 2 interpreted runs each -> compiled v1
        warm = ["Pruning Shears", "Wireless Mouse"] if tid == "price_of" else ["Headlamp", "Kettle"]
        for v in warm:
            out.append(h.run(tid, {param: v}, suite="stress", mode="original", kind="warmup"))
    snap = WORK / model / "stress_snapshot"
    shutil.rmtree(snap, ignore_errors=True)
    shutil.copytree(base, snap)
    for mode in STRESS_MODES:
        shutil.rmtree(base)
        shutil.copytree(snap, base)  # every mode starts from the same compiled v1
        h.home(base, reset=False)
        h.mode(mode)
        for tid, param, values in STRESS_TASKS:
            for attempt, v in enumerate(values, start=1):
                out.append(h.run(tid, {param: v}, suite="stress", mode=mode, kind="jit", attempt=attempt))
        # Baseline: the same first task on the changed site with no compiled code at all (pure LLM agent).
        for tid, param, values in STRESS_TASKS:
            h.home(WORK / model / "stress_interp")
            out.append(h.run(tid, {param: values[0]}, suite="stress", mode=mode, kind="llm_only"))
    h.mode("original")
    return out


def suite_books(h, model, truth):
    h.home(WORK / model / "books")
    out = []
    for t in BOOKS:
        r = h.run("book_price", {"title": t}, suite="books")
        r["correct"] = bool(r["ok"]) and (r["result"] or {}).get("price") == truth.get(t.lower())
        out.append(r)
    return out


def tier_stats(rs):
    if not rs:
        return None
    return {"runs": len(rs), "p50_ms": statistics.median(r["ms"] for r in rs), "p95_ms": pct([r["ms"] for r in rs], 95),
            "mean_cost": statistics.mean(r["cost"] for r in rs), "llm_calls_per_run": statistics.mean(r["llm_calls"] for r in rs),
            "ok_rate": sum(bool(r["ok"]) for r in rs) / len(rs),
            "correct_rate": sum(bool(r["correct"]) for r in rs) / len(rs)}


def outcome(r):
    tier = {"interpreted": "interp", "compiled": "compiled", "deopt": f"deopt@{r['deopt_step']}",
            "fallback": f"side-exit@{r['deopt_step']}", "error": "crashed"}[r["tier"]]
    if not r["ok"]:
        return f"{tier} FAILED"
    return f"{tier} {'✓' if r['correct'] else '✗ wrong'}"


def summarize(model, runs):
    shop = [r for r in runs if r["suite"] == "shop"]
    stress = [r for r in runs if r["suite"] == "stress"]
    books = [r for r in runs if r["suite"] == "books"]
    all_interp = [r for r in runs if r["tier"] == "interpreted"]
    s = {
        "model": model,
        "interpreted": tier_stats(all_interp),
        "compiled": tier_stats([r for r in runs if r["tier"] == "compiled"]),
        "deopt": tier_stats([r for r in runs if r["tier"] == "deopt"]),
        "side_exit": tier_stats([r for r in runs if r["tier"] == "fallback"]),
        "shop_total_cost": sum(r["cost"] for r in shop),
        "shop_all_interpreted_estimate": statistics.mean(r["cost"] for r in shop if r["tier"] == "interpreted") * len(shop),
        "shop_correct_rate": sum(bool(r["correct"]) for r in shop) / len(shop),
        "shop_deopt_rate_after": sum(r["tier"] == "deopt" for r in shop if r["phase"] == "after") /
                                 max(1, sum(r["phase"] == "after" for r in shop)),
        "stress": {},
        "books_correct": sum(bool(r["correct"]) for r in books), "books_runs": len(books),
        "books_tiers": [outcome(r) for r in books],
        "books_cost": sum(r["cost"] for r in books),
        "total_cost": sum(r["cost"] for r in runs),
    }
    for mode in STRESS_MODES:
        for tid, _, _ in STRESS_TASKS:
            jit = [r for r in stress if r.get("mode") == mode and r["template"] == tid and r.get("kind") == "jit"]
            base = [r for r in stress if r.get("mode") == mode and r["template"] == tid and r.get("kind") == "llm_only"]
            s["stress"][f"{mode}/{tid}"] = {
                "jit": [outcome(r) for r in sorted(jit, key=lambda r: r["attempt"])],
                "reason": jit[0]["reason"] if jit else "",
                "llm_only": outcome(base[0]) if base else None,
                "jit_cost": sum(r["cost"] for r in jit), "llm_only_cost": sum(r["cost"] for r in base),
            }
    return s


def fmt_ms(ms):
    return "—" if ms is None else (f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.0f} ms")


def report(summaries) -> str:
    models = [s["model"] for s in summaries]
    L = ["## Model comparison (live)", "",
         "| | " + " | ".join(models) + " |", "|---|" + "---:|" * len(models)]

    def row(label, f):
        L.append(f"| {label} | " + " | ".join(f(s) for s in summaries) + " |")

    def t(s, tier, key, fmt):
        st = s[tier]
        return "—" if not st else fmt(st[key])

    row("Interpreted p50 latency", lambda s: t(s, "interpreted", "p50_ms", fmt_ms))
    row("Interpreted LLM calls / run", lambda s: t(s, "interpreted", "llm_calls_per_run", lambda v: f"{v:.2f}"))
    row("Interpreted cost / run", lambda s: t(s, "interpreted", "mean_cost", lambda v: f"${v:.4f}"))
    row("Interpreted correct", lambda s: t(s, "interpreted", "correct_rate", lambda v: f"{v:.0%}"))
    row("Compiled p50 latency", lambda s: t(s, "compiled", "p50_ms", fmt_ms))
    row("Compiled cost / run", lambda s: "$0")
    row("Compiled correct", lambda s: t(s, "compiled", "correct_rate", lambda v: f"{v:.0%}"))
    row("Deopt runs (recovered ok)", lambda s: "—" if not s["deopt"] else f"{s['deopt']['runs']} ({s['deopt']['ok_rate']:.0%})")
    row("Deopt p50 latency / cost", lambda s: "—" if not s["deopt"] else f"{fmt_ms(s['deopt']['p50_ms'])} / ${s['deopt']['mean_cost']:.4f}")
    row("Shop bench: correct", lambda s: f"{s['shop_correct_rate']:.0%}")
    row("Shop bench: cost (vs all-interpreted)", lambda s: f"${s['shop_total_cost']:.3f} (vs ${s['shop_all_interpreted_estimate']:.3f})")
    row("toscrape books: correct", lambda s: f"{s['books_correct']}/{s['books_runs']}")
    row("Total spend this suite", lambda s: f"${s['total_cost']:.3f}")
    L += ["", "### Stress tests: compiled v1 meets a changed site",
          "First and second run with the JIT (✓ correct, ✗ wrong answer), vs the same task run by the LLM alone with no compiled code.", "",
          "| site change / task | " + " | ".join(f"{m} JIT | {m} LLM only" for m in models) + " |",
          "|---|" + "---|---|" * len(models)]
    for key in summaries[0]["stress"]:
        cells = []
        for s in summaries:
            st = s["stress"][key]
            cells += [" → ".join(st["jit"]), st["llm_only"] or "—"]
        L.append(f"| {key} | " + " | ".join(cells) + " |")
    L += ["", "Guard failure reasons (" + models[0] + "):", ""]
    for key, st in summaries[0]["stress"].items():
        if st["reason"]:
            L.append(f"- `{key}`: {st['reason']}")
    L += ["", "### toscrape book sequence", ""]
    for s in summaries:
        L.append(f"- **{s['model']}**: " + ", ".join(s["books_tiers"]))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["claude-sonnet-5-5", "claude-sonnet-4-6"])
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--suites", nargs="+", default=["shop", "stress", "books"])
    ap.add_argument("--fake", action="store_true", help="dry run with the scripted LLM (shop/stress only)")
    args = ap.parse_args()

    from hotpath.llm import AnthropicLLM

    truth = book_truth() if "books" in args.suites else {}
    h = Harness()
    results = {}
    try:
        for model in args.models:
            print(f"=== {model} ===")
            if args.fake:
                from hotpath.fake_llm import FakeLLM

                h.rt.llm_factory = FakeLLM
            else:
                h.rt.llm_factory = lambda m=model: AnthropicLLM(m)
            runs = []
            if "shop" in args.suites:
                runs += suite_shop(h, model, args.runs)
            if "stress" in args.suites:
                runs += suite_stress(h, model)
            if "books" in args.suites:
                runs += suite_books(h, model, truth)
            results[model] = runs
    finally:
        h.close()
    summaries = [summarize(m, rs) for m, rs in results.items()]
    md = report(summaries)
    (ROOT / "compare.json").write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   "summaries": summaries, "runs": results}, indent=2, default=str))
    (ROOT / "compare.md").write_text(md)
    print()
    print(md)


if __name__ == "__main__":
    main()
