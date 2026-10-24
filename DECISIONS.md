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
