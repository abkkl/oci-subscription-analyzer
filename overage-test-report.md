# Overage validation — version 3.0

84 tests passed: regression, HTML/frame, baseline-selection and subprocess checks. All data is synthetic. The temporary fake OCI CLI supplies responses to the real report subprocess; no live tenancy or credentials are used.

## Full-overage scenario

Reference: 2026-10-23 00:00:00 UTC. Active commitment horizon: 2026-11-02 00:00:00 UTC (10 days). The service contract continues until 2027; its later end is not used for the commitment forecast. Credit: EUR 1,000; all four baseline averages: EUR 200/day. Monthly equivalent: 744 hours = 31 days.

| Metric | Expected | Actual (all four baselines) | Check |
| --- | --- | --- | --- |
| Remaining Credit - Total | 1,000.0 | 1,000.0 | PASS |
| Forecasted Consumption - Total | 2,000.0 | 2,000.0 | PASS |
| Unused/Overage Credit - Total | 1,000.0 | 1,000.0 | PASS |
| Forecasted Consumption - Daily | 200.0 | 200.0 | PASS |
| Required Consumption - Daily | 100.0 | 100.0 | PASS |
| Unused/Overage Credit - Daily | 100.0 | 100.0 | PASS |
| Forecasted Consumption - Monthly | 6,200.0 | 6,200.0 | PASS |
| Required Consumption - Monthly | 3,100.0 | 3,100.0 | PASS |
| Unused/Overage Credit - Monthly | 3,100.0 | 3,100.0 | PASS |
| Days to horizon | 10.0 Days | 10.0 Days | PASS |
| Forecast outcome | Overage estimate | Overage estimate | PASS |

## End-to-end cases

| Case | Verified result |
| --- | --- |
| All baselines overage | 2,000 future consumption − 1,000 credit = 1,000 overage; daily 100; monthly 3,100. |
| Mixed baselines | Selected day: 1,000 overage; last 7 days: 142.9 overage; last 30 days: 350 unused; last 90 days: 450 unused. Monthly amounts: 3,100 / 442.9 / 1,085 / 1,395. |
| All baselines unused | 10,000 credit − 2,000 future consumption = 8,000 unused. |
| Exact credit exhaustion | 2,000 credit and 2,000 future consumption: zero difference; Balanced estimate. |
| Exhausted credit, existing overage | Remaining credit 0; reported overage 100 stays in balances; future overage is 2,000, not 2,100. |
| Zero consumption | Future consumption 0; all 1,000 credit remains unused. |
| Missing recent day | The latest equal maximum is selected from the remaining records; windows shift together and use reported-day averages. |

Regression checks also cover fractional horizons, monthly conversion, service/currency isolation, pagination, history, reported/derived consumption, ANSI alignment and subscription headings matching the 7-day outcome, cyan baseline labels, uncolored Baseline heading and blank-line spacing.

## Reproduce

```bash
python3 -m unittest discover -v
python3 -m unittest test_overage -v
```

Full captured reports: [overage](examples/sample-output-overage.txt), [mixed](examples/sample-output-mixed.txt), [already exhausted](examples/sample-output-exhausted.txt).

This validates the implementation against controlled API responses. Live API availability, permissions, retention and charge completeness still require confirmation in the target tenancy.

90-day checks also confirm the exact 2026-07-25 → 2026-10-22 window and a 7-vs-90 trend. Missing dates and dates before service start are excluded from the denominator. An explicit zero-cost record still counts; no reported dates means N/A. Additional checks cover aligned labels/dates, a cyan trend prefix only, and unavailable results on API errors or malformed records.

The [missing-days report](examples/sample-output-missing-days.txt) has 64 records at EUR 200/day: the average is 12,800 / 64 = 200, not 142.2. Coverage stays 64/90. No extra missing-record note is printed.

HTML/frame tests cover default and custom output folders, --no-html, only the home-relative download code, escaping untrusted text, preserved colors, no spinner frames in HTML, exclusive file creation, owner-only permissions, partial failures, complete terminal frames and subscription rules matching the terminal frame width.

The single-day baseline selects the largest reported total among today and the previous four UTC days (newest date wins ties). Positive `--usage-delay-hours` instead selects by elapsed hours after day end. All 1/7/30/90-day windows share this date. Tests cover current-day inclusion in both sources, midnight/year/leap boundaries, missing selected dates, zero amounts, out-of-window delays, midnight-aligned API lookbacks, CLI/HTML propagation and terminal-width rules.
