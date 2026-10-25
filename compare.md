<!-- config: {"trials": 3, "invariants": true, "shadow_every": 0, "suites": ["shop", "stress", "books"]} -->
## Model comparison (live)

| | claude-sonnet-5-5 | claude-sonnet-4-6 |
|---|---:|---:|
| Interpreted p50 latency | 6.06 s | 5.84 s |
| Interpreted LLM calls / run | 3.96 | 3.96 |
| Interpreted cost / run | $0.0138 | $0.0182 |
| Interpreted correct | 89% | 93% |
| Compiled p50 latency | 140 ms | 136 ms |
| Compiled cost / run | $0 | $0 |
| Compiled correct | 100% | 100% |
| Deopt runs (recovered ok) | 30 (100%) | 30 (100%) |
| Deopt p50 latency / cost | 5.53 s / $0.0096 | 4.32 s / $0.0121 |
| Shop bench: correct | 100% | 100% |
| Shop bench: cost (vs all-interpreted) | $0.114 (vs $0.833) | $0.156 (vs $1.106) |
| toscrape books: correct | 9/9 | 9/9 |
| Total spend this suite | $1.220 | $1.560 |

### Stress tests: compiled v1 meets a changed site

Every run is classified **correct**, **flagged** (wrong or failed, but Hotpath raised a flag or failed loudly) or **silent** (a wrong answer nobody was told about). 95% Wilson intervals.

| | claude-sonnet-5-5 | claude-sonnet-4-6 |
|---|---:|---:|
| Hotpath (JIT): correct | 66/72 (83%–96%) | 68/72 (87%–98%) |
| Hotpath (JIT): flagged | 6/72 | 4/72 |
| Hotpath (JIT): **silent wrong** | **0/72** (≤5%) | **0/72** (≤5%) |
| Hotpath (JIT): cost / run, p50 | $0.0053, 1.57 s | $0.0067, 1.35 s |
| LLM alone: correct | 33/36 (78%–97%) | 33/36 (78%–97%) |
| LLM alone: flagged | 0/36 | 0/36 |
| LLM alone: **silent wrong** | **3/36** (≤22%) | **3/36** (≤22%) |
| LLM alone: cost / run, p50 | $0.0136, 6.02 s | $0.0179, 5.66 s |

Per site change (first trial, first → second run; ⚑ = flagged), and totals over all trials:

| site change / task | claude-sonnet-5-5 JIT | claude-sonnet-5-5 JIT all trials | claude-sonnet-5-5 LLM alone | claude-sonnet-4-6 JIT | claude-sonnet-4-6 JIT all trials | claude-sonnet-4-6 LLM alone |
|---|---|---|---|---|---|---|
| redesign/price_of | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| redesign/stock_for | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| rename_all/price_of | deopt@0 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@0 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| rename_all/stock_for | deopt@0 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@0 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| relabel/price_of | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| relabel/stock_for | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@1 ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| cents/price_of | deopt@2 ✗ ⚑ → backoff→interp ✗ ⚑ | 0✓ 6⚑ 0✗ /6 | 0/3 ✓ | deopt@2 ✗ ⚑ → backoff→interp ✓ ⚑ | 2✓ 4⚑ 0✗ /6 | 0/3 ✓ |
| cents/stock_for | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| swap/price_of | deopt@2 ✓ ⚑ → backoff→interp ✓ ⚑ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@2 ✓ ⚑ → backoff→interp ✓ ⚑ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| swap/stock_for | deopt@2 ✓ ⚑ → backoff→interp ✓ ⚑ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | deopt@2 ✓ ⚑ → backoff→interp ✓ ⚑ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| decoy/price_of | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |
| decoy/stock_for | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ | compiled ✓ → compiled ✓ | 6✓ 0⚑ 0✗ /6 | 3/3 ✓ |

Guard failure reasons (claude-sonnet-5-5):

- `redesign/price_of`: deoptimizing at step 1: selector #search-btn not visible within 1s
- `redesign/stock_for`: deoptimizing at step 1: selector #search-btn not visible within 1s
- `rename_all/price_of`: deoptimizing at step 0: selector #q not visible within 1s
- `rename_all/stock_for`: deoptimizing at step 0: selector #q not visible within 1s
- `relabel/price_of`: deoptimizing at step 1: fingerprint mismatch on #search-btn: {'label': 'Find'}
- `relabel/stock_for`: deoptimizing at step 1: fingerprint mismatch on #search-btn: {'label': 'Find'}
- `cents/price_of`: deoptimizing at step 2: learned invariant: price '3825' !~ ^\$\d+\.\d{2}$
- `swap/price_of`: deoptimizing at step 2: learned invariant: price '14' !~ ^\$\d+\.\d{2}$
- `swap/stock_for`: deoptimizing at step 2: learned invariant: stock '$19.99' !~ ^\d+$

### toscrape book sequence

- **claude-sonnet-5-5**: interp ✓, interp ✓, compiled ✓, compiled ✓, compiled ✓, side-exit@0 ✓, compiled ✓, side-exit@0 ✓, compiled ✓
- **claude-sonnet-4-6**: interp ✓, interp ✓, compiled ✓, compiled ✓, compiled ✓, side-exit@0 ✓, compiled ✓, side-exit@0 ✓, compiled ✓
