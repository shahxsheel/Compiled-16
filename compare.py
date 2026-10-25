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


def suite_stress(h, model, trials=1):
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
    for trial in range(1, trials + 1):
        for mode in STRESS_MODES:
            shutil.rmtree(base)
            shutil.copytree(snap, base)  # every mode and trial starts from the same compiled v1
            h.home(base, reset=False)
            h.mode(mode)
            for tid, param, values in STRESS_TASKS:
                for attempt, v in enumerate(values, start=1):
                    out.append(h.run(tid, {param: v}, suite="stress", mode=mode, kind="jit", attempt=attempt, trial=trial))
            # Baseline: the same first task on the changed site with no compiled code at all (pure LLM agent).
            for tid, param, values in STRESS_TASKS:
                h.home(WORK / model / "stress_interp")
                out.append(h.run(tid, {param: values[0]}, suite="stress", mode=mode, kind="llm_only", trial=trial))
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


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


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
    if r.get("backoff"):
        tier = "backoff→interp"
    flag = " ⚑" if r.get("flag") else ""
    if not r["ok"]:
        return f"{tier} FAILED{flag}"
    return f"{tier} {'✓' if r['correct'] else '✗'}{flag}"


def verdict(r):
    """correct / flagged (wrong or failed but surfaced to a human) / silent (wrong, nobody told)."""
    if r["ok"] and r["correct"]:
        return "correct"
    if r.get("flag") or not r["ok"]:
        return "flagged"
    return "silent"


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
        "shop_all_interpreted_estimate": (statistics.mean(r["cost"] for r in shop if r["tier"] == "interpreted") * len(shop))
        if any(r["tier"] == "interpreted" for r in shop) else 0,
        "shop_correct_rate": sum(bool(r["correct"]) for r in shop) / len(shop) if shop else 0,
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
            first = [r for r in jit if r.get("trial", 1) == 1]
            s["stress"][f"{mode}/{tid}"] = {
                "jit": [outcome(r) for r in sorted(first, key=lambda r: r["attempt"])],
                "jit_verdicts": {v: sum(verdict(r) == v for r in jit) for v in ("correct", "flagged", "silent")},
                "jit_n": len(jit),
                "reason": jit[0]["reason"] if jit else "",
                "llm_only": outcome(base[0]) if base else None,
                "llm_only_verdicts": {v: sum(verdict(r) == v for r in base) for v in ("correct", "flagged", "silent")},
                "llm_only_n": len(base),
                "jit_cost_per_run": statistics.mean(r["cost"] for r in jit) if jit else 0,
                "llm_only_cost_per_run": statistics.mean(r["cost"] for r in base) if base else 0,
            }
    jit_all = [r for r in stress if r.get("kind") == "jit"]
    base_all = [r for r in stress if r.get("kind") == "llm_only"]
    for name, rs in (("stress_jit", jit_all), ("stress_llm_only", base_all)):
        n = len(rs)
        ver = {v: sum(verdict(r) == v for r in rs) for v in ("correct", "flagged", "silent")}
        s[name] = {"n": n, **ver, "correct_ci": wilson(ver["correct"], n), "silent_ci": wilson(ver["silent"], n),
                   "cost_per_run": statistics.mean(r["cost"] for r in rs) if rs else 0,
                   "p50_ms": statistics.median(r["ms"] for r in rs) if rs else None}
    shadow = [r for r in runs if r.get("shadow")]
    s["shadow"] = {"checks": len(shadow), "mismatches": sum(not r["shadow"]["match"] for r in shadow),
                   "cost": sum(r["shadow"]["cost"] for r in shadow)}
    s["total_cost"] += s["shadow"]["cost"]
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
    def ci(v):
        lo, hi = v
        return "—" if lo is None else f"{lo:.0%}–{hi:.0%}"

    L += ["", "### Stress tests: compiled v1 meets a changed site", "",
          "Every run is classified **correct**, **flagged** (wrong or failed, but Hotpath raised a flag or failed loudly) "
          "or **silent** (a wrong answer nobody was told about). 95% Wilson intervals.", "",
          "| | " + " | ".join(models) + " |", "|---|" + "---:|" * len(models)]
    for label, key in (("Hotpath (JIT)", "stress_jit"), ("LLM alone", "stress_llm_only")):
        row(f"{label}: correct", lambda s, k=key: f"{s[k]['correct']}/{s[k]['n']} ({ci(s[k]['correct_ci'])})")
        row(f"{label}: flagged", lambda s, k=key: f"{s[k]['flagged']}/{s[k]['n']}")
        row(f"{label}: **silent wrong**", lambda s, k=key: f"**{s[k]['silent']}/{s[k]['n']}** (≤{s[k]['silent_ci'][1]:.0%})")
        row(f"{label}: cost / run, p50", lambda s, k=key: f"${s[k]['cost_per_run']:.4f}, {fmt_ms(s[k]['p50_ms'])}")
    L += ["", "Per site change (first trial, first → second run; ⚑ = flagged), and totals over all trials:", "",
          "| site change / task | " + " | ".join(f"{m} JIT | {m} JIT all trials | {m} LLM alone" for m in models) + " |",
          "|---|" + "---|---|---|" * len(models)]
    for key in summaries[0]["stress"]:
        cells = []
        for s in summaries:
            st = s["stress"][key]
            v = st["jit_verdicts"]
            cells += [" → ".join(st["jit"]), f"{v['correct']}✓ {v['flagged']}⚑ {v['silent']}✗ /{st['jit_n']}",
                      f"{st['llm_only_verdicts']['correct']}/{st['llm_only_n']} ✓"]
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
    ap.add_argument("--trials", type=int, default=3, help="stress-test repetitions per site change")
    ap.add_argument("--no-invariants", action="store_true", help="ablation: compile without learned value guards")
    ap.add_argument("--shadow-every", type=int, default=0, help="shadow-verify every Nth compiled run")
    ap.add_argument("--label", default="", help="write compare_<label>.json/md instead of compare.json/md")
    args = ap.parse_args()

    from hotpath.llm import AnthropicLLM

    truth = book_truth() if "books" in args.suites else {}
    if args.no_invariants:
        os.environ["HOTPATH_NO_INVARIANTS"] = "1"
    h = Harness()
    h.rt.shadow_every = args.shadow_every
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
                runs += suite_stress(h, model, args.trials)
            if "books" in args.suites:
                runs += suite_books(h, model, truth)
            results[model] = runs
    finally:
        h.close()
    summaries = [summarize(m, rs) for m, rs in results.items()]
    md = report(summaries)
    name = f"compare_{args.label}" if args.label else "compare"
    config = {"trials": args.trials, "invariants": not args.no_invariants, "shadow_every": args.shadow_every,
              "suites": args.suites}
    md = f"<!-- config: {json.dumps(config)} -->\n" + md
    (ROOT / f"{name}.json").write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "config": config,
                                                  "summaries": summaries, "runs": results}, indent=2, default=str))
    (ROOT / f"{name}.md").write_text(md)
    print()
    print(md)


if __name__ == "__main__":
    main()
