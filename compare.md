## Model comparison (live)

| | claude-sonnet-5-5 | claude-sonnet-4-6 |
|---|---:|---:|
| Interpreted p50 latency | 6.27 s | 5.79 s |
| Interpreted LLM calls / run | 3.92 | 3.92 |
| Interpreted cost / run | $0.0140 | $0.0184 |
| Interpreted correct | 96% | 96% |
| Compiled p50 latency | 136 ms | 132 ms |
| Compiled cost / run | $0 | $0 |
| Compiled correct | 94% | 94% |
| Deopt runs (recovered ok) | 11 (100%) | 11 (100%) |
| Deopt p50 latency / cost | 5.76 s / $0.0100 | 5.84 s / $0.0133 |
| Shop bench: correct | 100% | 100% |
| Shop bench: cost (vs all-interpreted) | $0.114 (vs $0.834) | $0.156 (vs $1.106) |
| toscrape books: correct | 9/9 | 9/9 |
| Total spend this suite | $0.512 | $1.021 |

### Stress tests: compiled v1 meets a changed site
First and second run with the JIT (✓ correct, ✗ wrong answer), vs the same task run by the LLM alone with no compiled code.

| site change / task | claude-sonnet-5-5 JIT | claude-sonnet-5-5 LLM only | claude-sonnet-4-6 JIT | claude-sonnet-4-6 LLM only |
|---|---|---|---|---|
| redesign/price_of | deopt@1 ✓ → compiled ✓ | interp ✓ | deopt@1 ✓ → compiled ✓ | interp ✓ |
| redesign/stock_for | deopt@1 ✓ → compiled ✓ | interp ✓ | deopt@1 ✓ → compiled ✓ | interp ✓ |
| rename_all/price_of | deopt@0 ✓ → compiled ✓ | interp ✓ | deopt@0 ✓ → compiled ✓ | interp ✓ |
| rename_all/stock_for | deopt@0 ✓ → compiled ✓ | interp ✓ | deopt@0 ✓ → compiled ✓ | interp ✓ |
| relabel/price_of | deopt@1 ✓ → compiled ✓ | interp ✓ | deopt@1 ✓ → compiled ✓ | interp ✓ |
| relabel/stock_for | deopt@1 ✓ → compiled ✓ | interp ✓ | deopt@1 ✓ → compiled ✓ | interp ✓ |
| cents/price_of | compiled ✗ wrong → compiled ✗ wrong | interp ✗ wrong | compiled ✗ wrong → compiled ✗ wrong | interp ✗ wrong |
| cents/stock_for | compiled ✓ → compiled ✓ | interp ✓ | compiled ✓ → compiled ✓ | interp ✓ |
| swap/price_of | compiled ✗ wrong → compiled ✗ wrong | interp ✓ | compiled ✗ wrong → compiled ✗ wrong | interp ✓ |
| swap/stock_for | deopt@3 ✓ → deopt@3 ✓ | interp ✓ | deopt@3 ✓ → deopt@3 ✓ | interp ✓ |
| decoy/price_of | compiled ✓ → compiled ✓ | interp ✓ | compiled ✓ → compiled ✓ | interp ✓ |
| decoy/stock_for | compiled ✓ → compiled ✓ | interp ✓ | compiled ✓ → compiled ✓ | interp ✓ |

Guard failure reasons (claude-sonnet-5-5):

- `redesign/price_of`: deoptimizing at step 1: selector #search-btn not visible within 1s
- `redesign/stock_for`: deoptimizing at step 1: selector #search-btn not visible within 1s
- `rename_all/price_of`: deoptimizing at step 0: selector #q not visible within 1s
- `rename_all/stock_for`: deoptimizing at step 0: selector #q not visible within 1s
- `relabel/price_of`: deoptimizing at step 1: fingerprint mismatch on #search-btn: {'label': 'Find'}
- `relabel/stock_for`: deoptimizing at step 1: fingerprint mismatch on #search-btn: {'label': 'Find'}
- `swap/stock_for`: deoptimizing at step 3: finalize: stock '$19.99' is not an integer

### toscrape book sequence

- **claude-sonnet-5-5**: interp ✓, interp ✓, compiled ✓, compiled ✓, compiled ✓, side-exit@0 ✓, compiled ✓, side-exit@0 ✓, compiled ✓
- **claude-sonnet-4-6**: interp ✓, interp ✓, compiled ✓, compiled ✓, compiled ✓, side-exit@0 ✓, compiled ✓, side-exit@0 ✓, compiled ✓
