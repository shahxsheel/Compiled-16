GOAL: Ship a working, tested demo of "Hotpath", a JIT compiler for browser agents, by 5:45 PM PT today. Work autonomously. Never stop to ask me questions: when a choice comes up, pick the option you'd recommend, apply it, and log one line in DECISIONS.md (choice + why). Commit after every milestone with a clear message.

WHAT IT DOES
An LLM browser agent completes a task (slow, costly). Hotpath records traces, detects when a task is "hot", compiles it to deterministic Playwright code with guards, and runs that instead (fast, $0). When a guard fails (site changed), it deoptimizes at that exact step: the LLM takes over from the current page state, finishes, and the trace is spliced and recompiled.

STACK
Python 3.11, Playwright (sync), anthropic SDK, FastAPI, plain HTML/CSS/JS for the UI (no build step). Runtime agent model: claude-sonnet-5-5. Never visit third-party sites. Key from ANTHROPIC_API_KEY env.

LOCKED DECISIONS (do not revisit)
- Element picking: the compact DOM lists elements with indexes ([3] input "Search"). Tools take el=<index>; our code maps it to ONE canonical selector we generate (#id > [name=] > [data-*] > tag.class:nth-of-type). Never let the LLM write CSS.
- Compact DOM only: interactive elements + tables. Never raw HTML.
- Hard cap: 15 tool calls per interpreted run.
- Hotness key = task_template_id + normalized signature. Normalize by dropping no-op steps (no URL/DOM-hash/focus change) and collapsing consecutive duplicates. Only successful runs count; capped or failed runs don't. Compile when 2 successful runs share a signature; if run 3 succeeds with no match, compile from the shortest successful trace.
- Param slots: exact, case-insensitive match of fill args to known param values. Extract outputs are never slots.
- Each step stores canonical selector + fingerprint (tag, role, visible text/aria-label). Guards check the selector is visible within 1s AND the fingerprint matches. After extract_table, check expected columns and price matches ^\$?\d+(\.\d{2})?$.
- The compiler is deterministic (no LLM) and emits only action + guard steps, then calls tasks.FINALIZERS[template_id](tables, params). Finalizers are hand-written in tasks.py with an output schema. A finalize miss raises GuardFailure.
- done() takes schema-validated JSON, so interpreted and compiled outputs compare field by field.
- Deopt: on GuardFailure at step k, emit "deoptimizing at step k: <reason>", hand the interpreter the CURRENT page + remaining goal + completed steps, finish, splice the suffix onto steps 0..k-1, recompile as v<k+1>.

TASKS (tasks.py)
1. price_of {product} -> {"price": "$19.99"}
2. top3_in {category} -> [{"name","price","stock"} x3]
3. stock_for {term} -> {"stock": int}

MILESTONES, IN ORDER (each must pass its tests before moving on)
M0 Target site at /shop: search box, category filter, results table (name, price, stock), seeded with about 20 products. Every interactive element has a stable id/name. POST /toggle flips "redesign" mode: renames ids/classes, reorders columns, moves the search box. Style /shop as a plain generic store (NOT the Altitude theme) so it reads as "some website".
M1 Interpreter + trace logging + run metrics (ms, llm_calls, tokens, cost).
M2 Hotness + deterministic compiler -> compiled/<template>_v<k>.py
M3 Deopt runtime + splice + recompile.
M4 Dashboard at / (design below): [Run task] with template dropdown + param input, [Toggle redesign], [Reset]; live event log via SSE; runs table; large tier indicator for the current run (INTERPRETED / COMPILED / DEOPT @ STEP k); side-by-side stat cards (first interpreted run vs latest compiled run: time, LLM calls, cost); compiled code viewer showing the current version and a diff vs the previous version after recompile.
M5 bench.py: 3 tasks x 10 runs, then one toggle, then 10 more each. Print and save bench.json: p50/p95 latency, mean cost, LLM calls per tier, deopt rate, correctness rate (compiled output == interpreted output). Dashboard shows the bench table if bench.json exists.

TESTS (required, run them and fix until green)
- pytest unit: selector canonicalization is stable across two DOM snapshots; signature normalization drops no-ops and collapses duplicates; param slotting; compiler output includes a guard per step; GuardFailure carries the right step index; splice produces a valid trace; each finalizer on fixture tables.
- pytest integration (real browser, mock the LLM with a scripted fake that returns fixed tool calls): run task twice -> compiled file exists; third run uses compiled tier with 0 LLM calls; toggle -> next run reports deopt at a step > 0 and recompiles to v2; following run is compiled again.
- Playwright UI tests against the dashboard: page loads; Run updates the tier indicator and adds a runs-table row; Toggle + Run shows DEOPT in the log and indicator; code viewer shows a diff after recompile; no console errors.
- One live smoke test with the real model on task 1 (skip if no API key).
Run the full suite before every commit. Add `make test` and `make demo`.

DASHBOARD DESIGN: "Altitude" style (midnight financial editorial). Load Libre Baskerville, Inter, Fira Code from Google Fonts.
- Surfaces: page #181818, deepest #111111, cards/inputs #1f1f1f, rows/hover #262626, popovers #323232. Text #eeeeee, muted #a4a19b, placeholder #5e5d59, borders #262626/#4b4b4b.
- One accent only: #2b7fff, for focus rings, links, and the COMPILED tier highlight. No green/red/yellow anywhere. Show DEOPT with a 1px #eeeeee border, uppercase tracked label, and Fira Code step text, not color.
- Type: headings in Libre Baskerville 400 (never bold), letter-spacing -0.025em; page title 48px. All UI in Inter 14px/400; table headers Inter 11px/500 uppercase, tracking 0.05em, #a4a19b. Code, logs, and traces in Fira Code.
- Shape: 4px radius for buttons/inputs/badges, 8px for cards. Hairline borders do the structure; shadows barely visible. Ghost buttons: transparent, 1px #eeeeee border, hover #262626.
- Layout: max-width 1200px, 8px element gaps, 12px card padding, generous section spacing. Big serif stat numbers on the comparison cards (45s vs 2s style). Optional: one thin 1px #a4a19b mountain-ridge SVG line under the header.

GUARDRAILS
- Keep the interpreter cheap: Sonnet, compact DOM, 15-call cap. If live interpreted runs are flaky, give the model a fixed whitelist of /shop element indexes.
- No new features after M4 passes tests if it's past 5:30 PM. Only fixes, bench, and README.
- README: one-paragraph pitch, architecture diagram in ASCII, exact run commands, and the bench table.

DONE WHEN: all tests pass, `make demo` launches the site and dashboard, and this sequence works live with the real model: run task 1 (interpreted) -> run again (interpreted) -> run again (COMPILED, ~0 LLM calls) -> toggle redesign -> run (DEOPT at step k, recompiles to v2) -> run (COMPILED). bench.json exists with real numbers.
