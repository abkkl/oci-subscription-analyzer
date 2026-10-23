# OCI Subscription Analyzer

Read-only OCI subscription, balance, commitment and credit forecast report. Supports PoC and production accounts, multiple subscriptions and API-reported currencies.

## Run in OCI Cloud Shell

Open **OCI Console → Cloud Shell**:

```bash
curl -fsSL https://raw.githubusercontent.com/abkkl/oci-subscription-analyzer/main/oci_balance.py -o oci_balance.py && python3 oci_balance.py
```

Uses Cloud Shell's native OCI authentication and `OCI_TENANCY`. Requires Python 3.7+, OCI CLI and subscription/usage read access. No extra Python packages or API key setup needed.

The home region is detected automatically. To select it manually:

```bash
python3 oci_balance.py --region eu-frankfurt-1
```

### All options

| Option | Description |
| --- | --- |
| `--region REGION` | Use the specified tenancy home region; skip automatic discovery. Other regions may be rejected by billing APIs. |
| `--include-history` | Expand past services and commitment details. Default: history summary. |
| `--as-of YYYY-MM-DD` | Set the forecast reference to midnight UTC. Balances remain live; this is not a historical balance report. Default: current UTC time. |
| `--help`, `-h` | Show help and exit. |

Combine options:

```bash
python3 oci_balance.py --region eu-frankfurt-1 --include-history --as-of 2026-10-23
```

Set `NO_COLOR=1` to disable color. Loading animation appears only in interactive terminals.

The tenant name is read from IAM; if permission is unavailable, the header says `Tenant name unavailable`. The colored end marker includes completion date/time in UTC.

The download command uses the version published on GitHub. To run a locally supplied update, upload it to Cloud Shell and run `python3 ~/oci_balance.py`.

## Report contents

- Colored tenant/subscription/service headings, terminal-width separators and contract countdowns in years, months and days (zero components omitted).
- Balances, reported overage and commitment periods with active/past/future status and remaining days.
- Compact forecast: metrics as rows; columns ordered Previous day, Last 7 days, Last 30 days, Last 90 days. Exact UTC date ranges appear above the table.
- Consumption trend: 7-day versus 90-day average (without the Comment prefix).
- Summarized history and omission notes for empty zero-credit services. When history exists, one reminder to use `--include-history` appears just before the final subscription counts.

Amounts use one decimal place; calculations retain full precision. `—` means unavailable, not zero. Service and commitment balances are not added together; currencies are never combined.

## Forecast calculations

The horizon is the **unique active commitment's end**, or the service contract end when there are no commitments. It may be earlier than the overall contract end.

Let `B` = remaining credit, `R` = baseline daily consumption and `D` = fractional days to the forecast horizon:

Subscription headings and separators match the Last 7 days forecast: unused yellow, overage red, balanced green. With multiple pools, any 7-day overage takes priority; unavailable forecasts retain yellow. `Baseline` is uncolored; a blank line precedes the monthly calculation note. Baseline column headings and the three baseline-dependent metric labels (Forecasted Consumption, Forecasted Consumption - Daily/Monthly) are cyan. Only the `Consumption trend:` prefix is blue; the rest of its text stays uncolored. Baseline date columns and the ends of Daily/Monthly metric labels are aligned. The table header includes currency. Columns are Previous day, Last 7 days, Last 30 days and Last 90 days. Rows are divided into four groups:

| Group | Metric | Meaning |
| --- | --- | --- |
| Credit totals | Remaining Credit | `B`, the service or selected commitment balance. |
| | Forecasted Consumption | `R × D`. |
| | Unused/Overage Credit - Total | Unused = `max(0, B − R × D)`; overage = `max(0, R × D − B)`. |
| Daily | Required Consumption - Daily | `B / D`, needed to use credit by the horizon. |
| | Forecasted Consumption - Daily | `R`, the selected baseline's average, including zero-filled days. |
| | Unused/Overage Credit - Daily | Unused or overage total divided by `D`. |
| Monthly | Required Consumption - Monthly | Required daily consumption × 31. |
| | Forecasted Consumption - Monthly | `R × 31`, a monthly equivalent of the baseline, not an actual calendar-month bill. |
| | Unused/Overage Credit - Monthly | Unused or overage daily amount × 31. |
| Coverage/outcome | Days to horizon | `D`, e.g. `84.4 Days`. |
| | Coverage | Reported dates / required dates, e.g. `7/7`. |
| | Forecast outcome | Unused estimate, Overage estimate, Balanced estimate or N/A. |

The horizon heading also shows remaining calendar years/months/days and total calendar days, omitting zero components. Forecast arithmetic uses unrounded fractional days. Monthly figures use a fixed 744 hours, not the actual length of a calendar month. Unused is yellow and overage red in supported terminals. The outcome appears only in the final table row; amount cells contain numbers only. Mixed scenarios keep their own outcome. Future overage excludes already reported overage.

Cost Analysis supplies subscription-level daily costs only when a single active credit pool is identified in that currency, assuming those costs consume that pool. Otherwise, exact service-level OneSubscription usage is used.

Usage requests cover 90 complete UTC days. Missing daily forecast records are treated as **zero**, including dates before the service start. Each average uses its full 1/7/30/90-day denominator. `Coverage` retains the actual returned-date count. Below the table, after a blank line, a dynamic note lists how many days were zero-filled in each baseline (for example, Last 90 days: 26 days).

A successful empty usage response is zero-filled; API errors, malformed matching records, missing service/currency identifiers and invalid forecast periods remain unavailable. Reported overage and balance fields are not zero-filled. Ingestion delays can therefore lower a zero-filled average. Estimates assume steady consumption and no renewals or rollover; they are not invoices.

Commitment `Credit status` follows Status: positive reported remaining balance = Unused credit; a negative balance or eligible reported used amount above net = Overage credit. Future and indeterminate cases show `--`. This describes reported commitment data, not a forecast or an inferred invoice total.

Commitment `Remaining days`: past = 0; active = UTC end date minus today; future = the full period duration, rounded up to whole days (normally 365 for an annual period, 366 in a leap year). Invalid dates show `—`.

## Consumption and overage notes

**Commitment Consumed:** use API `used-amount` when available. For eligible active periods, `net amount − remaining` is shown with `*` as a balance-based estimate that may include adjustments. Future/expired periods are not inferred; zero after expiry does not prove consumption.

**Overage (records):** sums explicit `OVERAGE` records for the matching service, currency and contract dates, retaining signed adjustments. The report shows returned date coverage. This is a returned-record subtotal, not a verified lifetime or invoice total. Missing records show `—`; `0.0` only describes the available typed records. Long histories can take longer to retrieve.

## Examples and troubleshooting

All reports are fictional; browse the [examples folder](examples/README.md).

Fictional examples: [default report](examples/sample-output.txt) · [expanded history](examples/sample-output-history.txt) · [missing days](examples/sample-output-missing-days.txt).

Forecast excerpt (fictional data; full report linked above):

```text
FORECAST (EUR) | Horizon: Active commitment end - 2026-11-02 (10 days remaining; 10 days total)

Balance snapshot UTC: 2026-10-23 00:00:00
Latest reported completed usage day (UTC): 2026-10-22
Future renewals and credit rollover are not forecast.

Baseline
Previous day (UTC): 2026-10-22 - 2026-10-22
 Last 7 days (UTC): 2026-10-16 - 2026-10-22
Last 30 days (UTC): 2026-09-23 - 2026-10-22
Last 90 days (UTC): 2026-07-25 - 2026-10-22

Monthly calculation: 744 hours = 31 days.

Metric (EUR)                     | Previous day     | Last 7 days      | Last 30 days    | Last 90 days
---------------------------------+------------------+------------------+-----------------+----------------
Remaining Credit                 |          1,000.0 |          1,000.0 |         1,000.0 |         1,000.0
Forecasted Consumption           |          2,000.0 |          1,142.9 |           650.0 |           550.0
Unused/Overage Credit - Total    |          1,000.0 |            142.9 |           350.0 |           450.0
---------------------------------+------------------+------------------+-----------------+----------------
    Required Consumption - Daily |            100.0 |            100.0 |           100.0 |           100.0
  Forecasted Consumption - Daily |            200.0 |            114.3 |            65.0 |            55.0
   Unused/Overage Credit - Daily |            100.0 |             14.3 |            35.0 |            45.0
---------------------------------+------------------+------------------+-----------------+----------------
  Required Consumption - Monthly |          3,100.0 |          3,100.0 |         3,100.0 |         3,100.0
Forecasted Consumption - Monthly |          6,200.0 |          3,542.9 |         2,015.0 |         1,705.0
 Unused/Overage Credit - Monthly |          3,100.0 |            442.9 |         1,085.0 |         1,395.0
---------------------------------+------------------+------------------+-----------------+----------------
Days to horizon                  |        10.0 Days |        10.0 Days |       10.0 Days |       10.0 Days
Coverage                         |              1/1 |              7/7 |           30/30 |           90/90
Forecast outcome                 | Overage estimate | Overage estimate | Unused estimate | Unused estimate

Missing daily records treated as zero: Previous day: 0 days | Last 7 days: 0 days | Last 30 days: 0 days | Last 90 days: 0 days.
Averages use the full baseline window; dates before service start are also zero-filled.

Consumption trend: 7-day average 114.3 EUR/day vs 90-day average 55.0 EUR/day -> 107.8% higher; 2.1x the 90-day average.
```

| Issue | Check |
| --- | --- |
| Missing `OCI_TENANCY` | Run in Cloud Shell or set the tenancy OCID. |
| Region discovery denied | Supply the known home region with `--region`. |
| Home-region error | Verify the selected region and Cloud Shell network access. |
| Missing command / authorization | Check OCI CLI support and read permissions. |
| Missing forecast / overage | Check request errors and coverage. Missing forecast days are zero-filled and counted; reported balances and overage remain unavailable when absent. |

Failures do not stop other subscriptions. Exit code `1` means a request error/partial failure; `0` means requests succeeded, not that billing data is complete.

## Validation

```bash
python3 -m unittest discover -v
```

The suite includes seven end-to-end scenarios using a temporary fake OCI CLI: overage, unused, balanced, mixed, exhausted credit with existing overage, zero consumption and missing records. It runs the real report and subprocess path without connecting to OCI.

See [overage test report](overage-test-report.md), [full overage output](examples/sample-output-overage.txt) and [exhausted-credit output](examples/sample-output-exhausted.txt).

Version **2.4** · ahmet.bakkal@oracle.com
