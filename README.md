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

- Colored tenant/subscription/service headings and contract countdowns in years, months and days.
- Balances, reported overage and commitment periods with active/past/future status and remaining days.
- Three forecast scenarios: last 30 complete UTC days, last 7 days and previous day.
- Consumption trend: 7-day versus 30-day average.
- Summarized history and omission notes for empty zero-credit services. When history exists, one reminder to use `--include-history` appears just before the final subscription counts.

Amounts use one decimal place; calculations retain full precision. `—` means unavailable, not zero. Service and commitment balances are not added together; currencies are never combined.

## Forecast calculations

The horizon is the **unique active commitment's end**, or the service contract end when there are no commitments. It may be earlier than the overall contract end.

Let `B` = remaining credit, `R` = baseline daily consumption and `D` = fractional days to the forecast horizon:

| Column | Meaning |
| --- | --- |
| Avg/day Consumption | `R`, from the baseline's complete daily records. |
| Required/day Consumption | `B / D`, needed to use all credit by the horizon. |
| Remaining Credit | `B`, for the selected service or active commitment. |
| Future Consumption | `R × D`. |
| Unused Credit at End - Total | `max(0, B − R × D)`. |
| Unused Credit at End - Daily | Unused total divided by `D`. |
| Overage Credit at End | `max(0, R × D − B)`; additional future overage, excluding already reported overage. |
| Days to horizon | `D`; all forecast calculations use this same duration. |
| Coverage | Reported dates / required dates, such as `7/7`. |
| Result | Estimate or N/A. |

Cost Analysis supplies subscription-level daily costs only when a single active credit pool is identified in that currency, assuming those costs consume that pool. Otherwise, exact service-level OneSubscription usage is used.

Missing days are not zero. Incomplete windows, inactive services or invalid horizons make forecasts unavailable. If all scenarios are unavailable, a short note replaces the table. Estimates assume steady consumption and no new credits, renewals or rollover; they are not invoice predictions. Usage can be delayed or revised.

Commitment `Remaining days`: past = 0; active = UTC end date minus today; future = the full period duration, rounded up to whole days (normally 365 for an annual period, 366 in a leap year). Invalid dates show `—`.

## Consumption and overage notes

**Commitment Consumed:** use API `used-amount` when available. For eligible active periods, `net amount − remaining` is shown with `*` as a balance-based estimate that may include adjustments. Future/expired periods are not inferred; zero after expiry does not prove consumption.

**Overage (records):** sums explicit `OVERAGE` records for the matching service, currency and contract dates, retaining signed adjustments. The report shows returned date coverage. This is a returned-record subtotal, not a verified lifetime or invoice total. Missing records show `—`; `0.0` only describes the available typed records. Long histories can take longer to retrieve.

## Examples and troubleshooting

Fictional examples: [default report](sample-output.txt) · [expanded history](sample-output-history.txt).

Report excerpt (fictional data; full output linked above):

```text
OCI SUBSCRIPTION AND BALANCE REPORT (Example Tenant)

Report version: 1.8 | ahmet.bakkal@oracle.com
...
Contract end (UTC): 2027-11-03 | 1 years 0 months 11 days remaining (376 days total)

Commitment periods: 3
Status | Start UTC  | End UTC    | Remaining days
-------+------------+------------+---------------
past   | 2024-11-04 | 2025-11-03 |              0
active | 2025-11-04 | 2026-11-03 |             11
future | 2026-11-04 | 2027-11-03 |            365

FORECAST (TRY) | Horizon: Active commitment end - 2026-11-03
...
Comment: Consumption trend: 7-day average 1,028.6 TRY/day vs 30-day average 470.0 TRY/day -> 118.8% higher; 2.2x the 30-day average.

...
History found. Run with --include-history to view details.
Subscriptions: 2 | Successful: 2 | Failed: 0

*END OF THE REPORT* (2026-10-23 12:00:05 UTC)
```


| Issue | Check |
| --- | --- |
| Missing `OCI_TENANCY` | Run in Cloud Shell or set the tenancy OCID. |
| Region discovery denied | Supply the known home region with `--region`. |
| Home-region error | Verify the selected region and Cloud Shell network access. |
| Missing command / authorization | Check OCI CLI support and read permissions. |
| Missing forecast / overage | Check usage dates and coverage; missing data is not zero. |

Failures do not stop other subscriptions. Exit code `1` means a request error/partial failure; `0` means requests succeeded, not that billing data is complete.

## Validation

```bash
python3 -m unittest discover -v
```

Tests use fictional data and do not call OCI.

Version **1.8** · ahmet.bakkal@oracle.com
