# Decisions

- Python 3.11 via `uv venv --python 3.11` (system Python is 3.15); deps in requirements.txt.
- SPEC.md written from the full spec text (the original /goal exceeded its length limit).
- /shop search is a GET form (q, category) submitted by a button, so every task is fill -> click -> extract_table; that gives a 3-step trace with a click step that can break.
- Redesign keeps the form contract (#q, #category) stable but renames the submit button (#search-btn "Search" -> #go-btn "Go"), the table id/classes, reorders columns, and moves the search form into a sidebar, so the first guard failure lands at step 1 (k > 0) and splicing reuses step 0.
- extract_table returns rows keyed by normalized header text (not column position), so the column reorder is harmless and the price regex always checks the price field.
- fill on a <select> picks the option by text (case-insensitive), so category is a fill param slot like the search term.
- The interpreter sends the URL plus compact element list after every action; tool_choice auto with parallel tool use disabled, since indexes refresh after each action.
- Real model runs with thinking {type: between_tools} at effort low for latency/cost; cost = $2/M input + $10/M output (Sonnet 5.5 list price).
- The 15-call cap counts tool calls and LLM calls; a capped run is a failed run.
- The scripted FakeLLM reads the same observation text as the real model, so it also handles deopt (it continues from whatever page state it is handed).
- Run correctness is checked against ground truth from the catalog (for a correct interpreter that equals compiled == interpreted).
- State (runs.json, hot.json, compiled/) lives under $HOTPATH_HOME, default project root; tests use a temp dir.
- hot.json holds per-template signature counts/traces plus the registry of the active compiled version; compiled modules are exec'd from source each run (no stale bytecode).
- Compiled steps store slotted args ({"slot": "product"}); generated code reads params[...] so one compiled file serves every product/category/term.
- A finalize miss is reported as GuardFailure at step N (one past the last action), so deopt can still resume from the current page.
- Deopt hands the interpreter the live page (no reload) plus the completed prefix with params filled back in; the suffix is slotted, spliced onto steps 0..k-1, normalized, and compiled as the next version. If the deopt interpreter fails, the run fails and the old version stays.
- Dashboard: one Playwright worker thread owns the browser and runs queued jobs; the runtime emits events into an in-memory bus that /api/events streams as SSE (replayed from the start on connect).
- `python -m hotpath [--show] [--fake] [--port]` is the entrypoint; --show runs the agent browser headed, --fake swaps in the scripted LLM for offline demos.
- UI tests stub the Google Fonts request with empty CSS so they run offline with no console errors.
- Code diff marks added lines with the accent border and removed lines struck through in placeholder grey (no green/red, per the Altitude rules).
- bench.py runs in its own state dir (.hotpath/bench) so it never clobbers the demo; it writes bench.json at the project root, which the dashboard and README read. Params vary per run so compiled runs are tested on inputs the interpreter never saw.
- Tier indicator shows the compiled version (e.g. "v2 · 137ms · 0 LLM calls"), and Reset clears the server event buffer and the on-page log, so a fresh demo starts with an empty log even after a reload.
- Verified the full demo sequence in the real dashboard UI with the real model (headless Playwright clicking Run/Toggle/Reset); screenshot saved as docs/dashboard-deopt.png.

## Real-site and stress testing (after M5)
- Third-party test target: books.toscrape.com (a public scraping sandbox), approved by the user as an exception to "never visit third-party sites"; the agent visits only that site.
- Templates may set start_url, expected table columns, price field and price regex; /shop templates keep the locked defaults (name/price/stock and ^\$?\d+(\.\d{2})?$).
- extract_table also reads key/value tables (<tr><th>key</th><td>value</td></tr>) as one row; element labels prefer aria-label, then the title attribute (toscrape truncates link text).
- Site-specific "fill, click, extract" guidance moved from the system prompt into each /shop template's hint, so the agent gets no /shop hints on other sites.
- Param-targeted clicks: a click whose element label equals a param value is slotted (target_slot); compiled code resolves it at run time with find_by_label(), and the signature uses the element kind instead of its position. Without this, toscrape compiled code returned the first book's price for every title with no guard failing.
- Two guard-failure kinds: "structure" (the page changed: deopt, splice, recompile) and "input" (a param-targeted element is not on the page: side exit to the interpreter from the start page, compiled code kept). Without this, a book on page 2 spliced the agent's category browsing into the trace and every later run deoptimized.
- Model is configurable (HOTPATH_MODEL, or AnthropicLLM(model)); Sonnet 5.5 uses thinking between_tools, while Sonnet 4.6 omits the thinking parameter (no thinking). Cost uses per-model list prices.
- Stress modes on /shop (POST /mode/{name}): rename_all, relabel, cents, swap, decoy; compare.py runs them live per model against a shared compiled v1, plus an LLM-only baseline on each changed site.
