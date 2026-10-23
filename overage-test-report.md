# Overage validation — version 2.3

52 tests passed: 45 regression checks and 7 end-to-end scenarios. All data is synthetic. The temporary fake OCI CLI supplies responses to the real report subprocess; no live tenancy or credentials are used.

## Full-overage scenario

Reference: 2026-10-23 00:00:00 UTC. Active commitment horizon: 2026-11-02 00:00:00 UTC (10 days). The service contract continues until 2027; its later end is not used for the commitment forecast. Credit: EUR 1,000; all four baseline averages: EUR 200/day. Monthly equivalent: 744 hours = 31 days.

| Metric | Expected | Actual (all four baselines) | Check |
| --- | --- | --- | --- |
| Remaining Credit | 1,000.0 | 1,000.0 | PASS |
| Future Consumption | 2,000.0 | 2,000.0 | PASS |
| Unused/Overage Credit - Total | 1,000.0 | 1,000.0 | PASS |
| Actual Consumption - Daily | 200.0 | 200.0 | PASS |
| Required Consumption - Daily | 100.0 | 100.0 | PASS |
| Unused/Overage Credit - Daily | 100.0 | 100.0 | PASS |
| Actual Consumption - Monthly | 6,200.0 | 6,200.0 | PASS |
| Required Consumption - Monthly | 3,100.0 | 3,100.0 | PASS |
| Unused/Overage Credit - Monthly | 3,100.0 | 3,100.0 | PASS |
| Days to horizon | 10.0 Days | 10.0 Days | PASS |
| Forecast outcome | Overage estimate | Overage estimate | PASS |

## End-to-end cases

| Case | Verified result |
| --- | --- |
| All baselines overage | 2,000 future consumption − 1,000 credit = 1,000 overage; daily 100; monthly 3,100. |
| Mixed baselines | Previous day: 1,000 overage; last 7 days: 142.9 overage; last 30 days: 350 unused; last 90 days: 450 unused. Monthly amounts: 3,100 / 442.9 / 1,085 / 1,395. |
| All baselines unused | 10,000 credit − 2,000 future consumption = 8,000 unused. |
| Exact credit exhaustion | 2,000 credit and 2,000 future consumption: zero difference; Balanced estimate. |
| Exhausted credit, existing overage | Remaining credit 0; reported overage 100 stays in balances; future overage is 2,000, not 2,100. |
| Zero consumption | Future consumption 0; all 1,000 credit remains unused. |
| Missing previous day | No forecast table; unavailable note. Missing records are not zero. |

Regression checks also cover fractional horizons, monthly conversion, service/currency isolation, pagination, history, reported/derived consumption, ANSI alignment and subscription headings matching the 7-day outcome, cyan baseline labels, uncolored Baseline heading and blank-line spacing.

## Reproduce

```bash
python3 -m unittest discover -v
python3 -m unittest test_overage -v
```

Full captured reports: [overage](sample-output-overage.txt), [mixed](sample-output-mixed.txt), [already exhausted](sample-output-exhausted.txt).

This validates the implementation against controlled API responses. Live API availability, permissions, retention and charge completeness still require confirmation in the target tenancy.

90-day checks also confirm the exact 2026-07-25 → 2026-10-22 window, 90/90 coverage, a 7-vs-90 trend, isolation of an older missing day, and unavailable 90-day results when service history is too short.
