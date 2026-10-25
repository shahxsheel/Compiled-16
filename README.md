# Hotpath: a JIT compiler for browser agents

An LLM browser agent is a slow, expensive interpreter: every run asks Claude to read the page and decide each click. Hotpath records what the agent does and counts identical traces per task. Once a trace is hot (2 successful runs with the same signature), a deterministic compiler (no LLM) turns it into plain Playwright code, with a guard before every step. Later runs use the compiled code: about 140 ms and $0, against about 7 s and $0.014 interpreted. When the site changes and a guard fails, Hotpath **deoptimizes at that exact step**. The LLM takes over from the live page, finishes the task, and its new steps are spliced onto the steps that still worked and recompiled as the next version.

![Dashboard after a live deopt: DEOPT @ step 1, v1 -> v2 diff](docs/dashboard-deopt.png)

*Dashboard right after a real-model deopt (run 4 of the demo script): the tier indicator, live SSE log, stat cards, runs table, v1→v2 diff, and benchmark table.*

## Architecture

```
                 ┌──────────────────────── hotpath.runtime ─────────────────────────┐
  run(task,      │                                                                   │
      params) ──►│  compiled/<task>_v<k>.py exists?                                  │
                 │     │ no                                  │ yes                   │
                 │     ▼                                     ▼                       │
                 │  INTERPRETER (Claude Sonnet 5.5)       COMPILED run(page, params) │
                 │  tools: click/fill/extract_table/done   guard_element: visible≤1s │
                 │  sees compact DOM: [i] tag "label"        + fingerprint match     │
                 │  el index ─► canonical selector         guard_table: columns +    │
                 │  ≤15 tool calls, trace + metrics          price regex             │
                 │     │ ok                                 │ GuardFailure(step k)   │
                 │     ▼                                    ▼                        │
                 │  HOTNESS (hot.json)                   DEOPT @ step k              │
                 │  normalize ─► slot params ─► sig       interpreter resumes on the  │
                 │  2× same sig (or best of 3) ─┐         CURRENT page with steps     │
                 │                              │         0..k-1 marked done          │
                 │                              ▼                   │                │
                 │                   COMPILER (deterministic) ◄─────┘ splice          │
                 │                   trace ─► Python + guards        prefix+suffix   │
                 │                   ─► compiled/<task>_v<k+1>.py                     │
                 └───────────────────────────────────────────────────────────────────┘
                        │ events (SSE)                     ▲ Playwright (Chromium)
                        ▼                                  │
               Dashboard  /  (Altitude UI)           Target site /shop (+ POST /toggle)
```

The pieces, one module each under `hotpath/`: `dom.py` (compact DOM, canonical selectors, fingerprints), `interpreter.py`, `trace.py` (normalize, slot, signature, splice), `hotness.py`, `compiler.py`, `guards.py`, `tasks.py` (templates, schemas, hand-written finalizers), `runtime.py`, `server.py`, `shop.py`.

## Run it

```bash
make setup                 # uv venv (Python 3.11) + deps + Chromium
export ANTHROPIC_API_KEY=...

make demo                  # http://127.0.0.1:8000/ (dashboard) and /shop (target site)
make demo-show             # same, with the agent's browser visible (python -m hotpath --show)
make demo-fake             # offline: scripted fake LLM instead of Claude

make test                  # unit + integration (fake LLM) + Playwright UI + 1 live smoke test (skipped without a key)
make bench                 # 3 tasks x 10 runs, toggle, 10 more each -> bench.json
```

Equivalent raw commands: `.venv/bin/python -m hotpath [--show] [--fake] [--port 8000]`, `.venv/bin/python -m pytest -q`, `.venv/bin/python bench.py [--fake] [--runs 10]`.

### Demo script

On the dashboard, pick `price_of {product}`:

1. **Run task**: INTERPRETED. Claude fills the search box, clicks Search, extracts the table, and calls `done` (~6 s, 4 LLM calls).
2. **Run task** again: INTERPRETED. Same signature twice, so it compiles to `price_of_v1.py` (shown in the code viewer).
3. **Run task**: COMPILED. ~150 ms, 0 LLM calls, $0. Try a different product; the param is a slot.
4. **Toggle redesign**: the site renames the submit button and table, reorders the columns, and moves the search form into a sidebar.
5. **Run task**: DEOPT @ STEP 1 (`selector #search-btn not visible within 1s`). Step 0 (fill `#q`) still passes. Claude finishes from the live page, the suffix is spliced on, and it recompiles to v2. **Diff vs previous** shows `#search-btn → #go-btn` and `#results → #product-grid`.
6. **Run task**: COMPILED v2.

## Tasks

| id | param | result |
|---|---|---|
| `price_of` | `{product}` | `{"price": "$19.99"}` |
| `top3_in` | `{category}` | `[{"name","price","stock"} x3]` |
| `stock_for` | `{term}` | `{"stock": 31}` |

`done()` is schema-validated, and compiled runs return the output of hand-written finalizers in `tasks.py`, so the two tiers' outputs compare field by field.

## Benchmark (real model, `claude-sonnet-5-5`)

`bench.py`: 3 tasks x 10 runs with a different param each run, then one redesign toggle, then 10 more each (60 runs).

| phase | tier | runs | p50 | p95 | mean cost | LLM calls/run |
|---|---|---:|---:|---:|---:|---:|
| before | interpreted | 6 | 6.87 s | 10.53 s | $0.0138 | 4.00 |
| before | compiled | 24 | 137 ms | 164 ms | $0 | 0.00 |
| after | compiled | 27 | 138 ms | 161 ms | $0 | 0.00 |
| after | deopt | 3 | 5.93 s | 7.24 s | $0.0102 | 3.00 |

- Deopt rate after the toggle: **10%** (one deopt per task, then v2 handles the rest)
- Correctness (compiled/deopt output == expected interpreted output): **100%** (60/60 runs succeeded)
- Total cost: **$0.113** for 60 runs, versus about $0.83 if every run had been interpreted. Compiled runs are about **50x faster** at p50.

## Live testing beyond the demo

`compare.py` runs three live suites per model and writes `compare.json` / [`compare.md`](compare.md):
the 60-run shop benchmark, six stress-test site changes against a shared compiled v1 (each also run by the LLM alone as a baseline), and a 9-title sequence on **books.toscrape.com**, a real public scraping sandbox.

```bash
.venv/bin/python compare.py --models claude-sonnet-5-5 claude-sonnet-4-6   # ~$1.50, ~15 min
```

| | Sonnet 5.5 | Sonnet 4.6 (older) |
|---|---:|---:|
| Interpreted p50 / cost per run | 6.27 s / $0.0140 | 5.79 s / $0.0184 |
| Compiled p50 / cost per run | 136 ms / $0 | 132 ms / $0 |
| Deopts recovered | 11/11 | 11/11 |
| Shop bench correct, cost (vs all-interpreted) | 100%, $0.114 (vs $0.834) | 100%, $0.156 (vs $1.106) |
| toscrape books correct | 9/9 | 9/9 |

Both models behave the same: Hotpath recovers from every *structural* change (renamed elements at step 0 or 1, relabelled button, decoy table). It is **fooled by changes in meaning**: with prices shown in cents, or the Price/Stock headers swapped, every guard passes and compiled code returns a wrong price (the LLM alone gets the swap right). The locked price regex `^\$?\d+(\.\d{2})?$` accepts `3825` and `52`; tightening it to `^\$\d+\.\d{2}$` would turn both into deopts. Two real-site bugs found and fixed along the way are in DECISIONS.md (param-targeted clicks, side exits).

## Design notes

Every judgment call is logged one line at a time in [DECISIONS.md](DECISIONS.md). The spec is in [SPEC.md](SPEC.md).
