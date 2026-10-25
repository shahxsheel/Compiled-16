<!-- config: {"trials": 3, "invariants": false, "shadow_every": 1, "suites": ["stress"]} -->
## Model comparison (live)

| | claude-sonnet-5-5 |
|---|---:|
| Interpreted p50 latency | 6.11 s |
| Interpreted LLM calls / run | 4.00 |
| Interpreted cost / run | $0.0137 |
| Interpreted correct | 93% |
| Compiled p50 latency | 163 ms |
| Compiled cost / run | $0 |
| Compiled correct | 80% |
| Deopt runs (recovered ok) | 21 (100%) |
| Deopt p50 latency / cost | 5.63 s / $0.0104 |
| Shop bench: correct | 0% |
| Shop bench: cost (vs all-interpreted) | $0.000 (vs $0.000) |
| toscrape books: correct | 0/0 |
| Total spend this suite | $1.466 |

### Stress tests: compiled v1 meets a changed site

Every run is classified **correct**, **flagged** (wrong or failed, but Hotpath raised a flag or failed loudly) or **silent** (a wrong answer nobody was told about). 95% Wilson intervals.

| | claude-sonnet-5-5 |
|---|---:|
| Hotpath (JIT): correct | 63/72 (78%–93%) |
| Hotpath (JIT): flagged | 3/72 |
| Hotpath (JIT): **silent wrong** | **6/72** (≤17%) |
| Hotpath (JIT): cost / run, p50 | $0.0042, 165 ms |
| LLM alone: correct | 33/36 (78%–97%) |
| LLM alone: flagged | 0/36 |
| LLM alone: **silent wrong** | **3/36** (≤22%) |
| LLM alone: cost / run, p50 | $0.0137, 6.08 s |

Per site change (first trial, first → second run; ⚑ = flagged), and totals over all trials:

| site change / task | claude-sonnet-5-5 JIT | claude-sonnet-5-5 JIT all trials | claude-sonnet-5-5 LLM alone |
|---|---|---|---|
| redesign/price_of | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| redesign/stock_for | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| rename_all/price_of | deopt@0 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| rename_all/stock_for | deopt@0 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| relabel/price_of | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| relabel/stock_for | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| cents/price_of | compiled ✗ → compiled ✗ | 0✓ 0⚑ 6✗ /6 | 0/3 ✓ |
| cents/stock_for | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| swap/price_of | compiled ✗ ⚑ → interp ✓ | 3✓ 3⚑ 0✗ /6 | 3/3 ✓ |
| swap/stock_for | deopt@3 ✓ ⚑ → backoff→interp ✓ ⚑ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| decoy/price_of | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| decoy/stock_for | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |

Guard failure reasons (claude-sonnet-5-5):

- `redesign/price_of`: deoptimizing at step 1: selector #search-btn not visible within 1s
- `redesign/stock_for`: deoptimizing at step 1: selector #search-btn not visible within 1s
- `rename_all/price_of`: deoptimizing at step 0: selector #q not visible within 1s
- `rename_all/stock_for`: deoptimizing at step 0: selector #q not visible within 1s
- `relabel/price_of`: deoptimizing at step 1: fingerprint mismatch on #search-btn: {'label': 'Find'}
- `relabel/stock_for`: deoptimizing at step 1: fingerprint mismatch on #search-btn: {'label': 'Find'}
- `swap/stock_for`: deoptimizing at step 3: finalize: stock '$19.99' is not an integer

### toscrape book sequence

- **claude-sonnet-5-5**: 
