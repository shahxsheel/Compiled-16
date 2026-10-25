## CI pipeline simulation (claude-sonnet-5-5, 9 checks per build)

A build is **right** when the pipeline is green with no regression and red with a real regression.

| build | site | Hotpath | Hotpath cost / time | frozen Playwright suite | LLM agent every check | LLM cost / time |
|---|---|---|---:|---|---|---:|
| main #1 (cold cache) | original | ✅ 9/9 pass, 3 compiled | $0.081 / 46.8s | ✅ 9/9 pass | ✅ 9/9 pass | $0.121 / 54.5s |
| main #2 | original | ✅ 9/9 pass, 9 compiled | $0.000 / 1.5s | ✅ 9/9 pass | ✅ 9/9 pass | $0.121 / 54.5s |
| PR #7: UI refactor | redesign | ✅ 9/9 pass, 3 self-healed, 6 compiled | $0.030 / 19.5s | ❌ 0/9 pass | ✅ 9/9 pass | $0.122 / 71.4s |
| PR #7 re-run | redesign | ✅ 9/9 pass, 9 compiled | $0.000 / 1.4s | ❌ 0/9 pass | ✅ 9/9 pass | $0.122 / 71.4s |
| main #3 | original | ✅ 9/9 pass, 9 compiled | $0.000 / 4.7s | ✅ 9/9 pass | ✅ 9/9 pass | $0.121 / 54.5s |
| PR #8: breaks price formatting | cents | ✅ 3/9 pass, 3 compiled | $0.068 / 35.8s | ✅ 3/9 pass | ✅ 4/9 pass | $0.122 / 53.0s |

| over 6 builds | builds right | LLM cost | wall time |
|---|---:|---:|---:|
| Hotpath | 6/6 | $0.179 | 109.7s |
| Frozen Playwright suite | 4/6 | $0.000 | 24.5s |
| LLM agent every check | 6/6 | $0.730 | 359.5s |
