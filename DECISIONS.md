# Decisions

- Python 3.11 via `uv venv --python 3.11` (system Python is 3.15); deps in requirements.txt.
- SPEC.md written from the full spec text (the original /goal exceeded its length limit).
- /shop search is a GET form (q, category) submitted by a button, so every task is fill -> click -> extract_table; that gives a 3-step trace with a click step that can break.
- Redesign keeps the form contract (#q, #category) stable but renames the submit button (#search-btn "Search" -> #go-btn "Go"), the table id/classes, reorders columns, and moves the search form into a sidebar, so the first guard failure lands at step 1 (k > 0) and splicing reuses step 0.
