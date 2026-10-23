# OCI Subscription Analyzer

A read-only OCI Cloud Shell report for subscriptions, balances, commitment periods, reported overage and credit forecasts. Uses the OCI CLI's existing authentication and Python's standard library. Report language is English; currency comes from OCI.

## Run in OCI Cloud Shell

Open **OCI Console → Cloud Shell**, then download and run:

```bash
curl -fsSL https://raw.githubusercontent.com/abkkl/oci-subscription-analyzer/main/oci_balance.py -o oci_balance.py && python3 oci_balance.py
```

The GitHub command downloads the version currently published on `main`. Until version 1.7 is published, upload the updated `oci_balance.py` to Cloud Shell and run `python3 ~/oci_balance.py` instead.

Use the tenancy home region for billing and usage APIs. By default the script discovers it through IAM and selects it explicitly for subsequent OCI calls. Cloud Shell network access must permit access to that region. No API key file, password or additional Python package is required in Cloud Shell. `OCI_TENANCY` and the existing authenticated OCI CLI session are used; read permissions are still required.

### All script options

| Option | Default | Description | Example |
| --- | --- | --- | --- |
| `--region REGION` | Automatically detected tenancy home region. | Use the supplied region for every OCI call and skip IAM home-region discovery. The value must be the tenancy home region; it is a manual selection and is not verified by IAM. Billing APIs may reject any other region. Useful when the home region is known but region discovery is unavailable. | `python3 oci_balance.py --region eu-frankfurt-1` |
| `--include-history` | Past services appear in one summary table per subscription/currency. | Expand past service balances and every returned commitment period. Inactive services still have no forecast. Does not hide active services. | `python3 oci_balance.py --include-history` |
| `--as-of YYYY-MM-DD` | Current UTC time. | Set the forecast reference and usage request end to midnight UTC on the specified date. Balances are still fetched live: this does not retrieve historical balances. Do not interpret it as a historical financial report. | `python3 oci_balance.py --as-of 2026-10-23` |
| `--help`, `-h` | Run the report. | Print all accepted arguments and exit without calling OCI. | `python3 oci_balance.py --help` |

Options can be combined:

```bash
python3 oci_balance.py --region eu-frankfurt-1 --include-history --as-of 2026-10-23
```

Download and run with a manually selected home region:

```bash
curl -fsSL https://raw.githubusercontent.com/abkkl/oci-subscription-analyzer/main/oci_balance.py -o oci_balance.py && python3 oci_balance.py --region eu-frankfurt-1
```

These are script arguments. The script supplies OCI CLI flags such as `--all`, `--subscription-id`, `--grouping DAILY` and `--query-type COST` internally; they are not additional arguments accepted by `oci_balance.py`.

`NO_COLOR=1 python3 oci_balance.py` disables color. An animated loading line shows the current API stage, subscription ID where available and elapsed time per request after the home region is selected. It clears after each request, including on errors. The animation uses stdout if attached to a terminal, otherwise stderr if that is a terminal. When both are redirected, or `TERM=dumb`, animation is suppressed.

## What version 1.7 shows

- Every accessible subscription, independently, using all API pages. Currency amounts are never combined across currencies.
- Colored subscription and service headings, UTC dates, and contract countdowns in calendar months/days and total UTC calendar days.
- One balances table per detailed service: promo credit, service total, funded allocation, consumed, remaining and `Overage (records)`.
- Empty companion services with explicitly zero available and consumed amounts and no nonzero credit/commitment amounts are represented by an omission note. Exhausted credit pools and unknown amounts are retained. A nonzero reported overage also retains the service.
- Past services, identified by `EXPIRED` status or a past contract end, are summarized by default. `--include-history` restores full details.
- All returned commitment periods for detailed services. Amounts at service and commitment level can overlap and are not added together.
- One consolidated forecast table with 30-day, 7-day and previous-day scenarios, plus a consumption trend comment.
- One decimal place for monetary amounts, rates, percentages and fractional forecast days. Arithmetic keeps full Decimal precision; rounding is only for display. English separators are used, for example `12,345.7`.

`—` means unavailable, not zero. Explicit zero is `0.0`. Future credit/renewals and rollover are not assumed. Current permissions determine which subscriptions are visible; the tool does not sign in to other tenancies.

## Forecast horizon and columns

The heading is `FORECAST (CURRENCY) | Horizon: description - YYYY-MM-DD`.

Without commitments, the forecast uses the service's reported available balance and end date. With commitments, it uses the available balance and end date of the **one currently active commitment**. Multiple overlapping active commitments, no active commitment, missing dates/balance and inactive services leave the forecast unavailable.

The contract countdown above the table can cover a longer period than the active commitment. Forecast arithmetic always uses its own stated horizon. `Days to horizon` is fractional days from the exact UTC snapshot to that end timestamp, not calendar days until the overall contract ends. For example, a half-day horizon is `0.5`, even if the contract continues for two years.

Let `D` be those fractional days, `B` the reported balance of the selected pool and `R` the baseline average daily consumption:

| Column | Calculation or meaning |
| --- | --- |
| Baseline | Rolling last 30 complete UTC days, last 7 complete UTC days, or previous complete UTC day, with the exact date range. |
| Avg/day Consumption | Sum of reported daily costs in the baseline divided by 30, 7 or 1. |
| Required/day Consumption | `B / D`: the daily consumption needed to use all remaining credit by the forecast horizon. |
| Remaining Credit | `B`; this can be the active commitment balance rather than the whole service balance. |
| Future Consumption | `R × D`. |
| Unused Credit at End - Total | `max(0, B − R × D)`. |
| Unused Credit at End - Daily | `Unused Credit at End - Total / D`: additional daily consumption needed above that scenario's rate to use the projected surplus. Uses the same horizon as every other forecast amount. |
| Overage Credit at End | `max(0, R × D − B)`: additional future consumption exceeding current credit; excludes overage already reported in balances. It is not an invoice prediction. |
| Days to horizon | `D`, displayed to one decimal; arithmetic uses the unrounded value. |
| Coverage | Dates with reported daily records / dates required by the baseline, such as `7/7`. |
| Result | Estimate, or N/A for an unavailable scenario. |

All three scenarios unavailable: only `Forecast unavailable (CURRENCY): reason.` is printed. If any scenario is calculable, the table remains and unavailable rows show N/A.

The trend comment compares the 7-day average against the 30-day average, showing the percent change and ratio. It requires complete baselines, handles a zero baseline without division by zero, and describes observed averages rather than predicting that a trend will persist.

### Daily usage sources and coverage

Cost Analysis is queried for the last 30 complete UTC days with `--query-type COST`, grouped and filtered by subscription ID. Rows are checked again for exact subscription ID, currency and completed daily intervals; pagination is followed. When there is exactly one identified active credit pool in a currency, matching subscription costs can supply its daily rates. This assumes those costs consume that pool; one positive pool does not prove billing allocation. The source assumption is documented here rather than repeated in the report.

With multiple credit pools, subscription-wide costs are not assigned to each pool. The fallback is OneSubscription daily computed usage matched by exact parent service ID and currency. The completed 30-day window is selected from that response. The latest reported completed usage date is shown; an older date does not silently replace yesterday.

Missing daily records are not zero. A baseline is unavailable when records for any required day are absent, the service is younger than the window or net costs are negative. Explicit zero-cost records are valid. Even full date coverage does not certify that all charges have arrived: usage may be delayed or revised.

## Why commitment Consumed can be unavailable

The subscription response can contain commitment net amount and available balance without `used-amount`. The report never substitutes zero for a missing used amount.

1. If OCI returns a numeric `used-amount`, show it directly.
2. Otherwise, only within a currently active finite period, show `line-net-amount − available-amount` followed by `*` when both are valid monetary amounts, available is between zero and net, and funded allocation is absent/zero or agrees with net.
3. The star identifies a **balance-based estimate** that may include adjustments, rather than metered usage. Quantity is not used as a substitute monetary amount.
4. Future and expired periods are not inferred. In particular, an expired period's zero available balance can reflect credit expiry rather than consumption. Missing/ambiguous inputs remain `—`.

See Oracle's [CommitmentSummary fields](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/onesubscription/models/oci.onesubscription.models.CommitmentSummary.html).

## Reported overage and historical coverage

The script requests OneSubscription daily computed usage from the earliest service start (or the start of the forecast window if earlier) through the reference timestamp, with all pages fetched. For each service/currency, it sums only explicit `OVERAGE` records metered within that service's contract and before the reference timestamp. Signed adjustments are retained. `PAY_AS_YOU_GO` and other types are not reclassified as overage.

`Overage (records)` deliberately means **the net overage in returned records**, not a certified lifetime or invoice total. The detailed service view shows the first/last matching metered dates, distinct returned dates versus dates requested for the service period, and number of OVERAGE rows. The history summary shows the returned date range and explicitly states that full historical coverage is unverified.

- An absent or invalid matching typed response shows `—`.
- Typed usage with no OVERAGE rows shows `0.0` **for those returned records**, not proof of zero lifetime overage.
- Missing historical dates are not treated as zero; retention, delayed ingestion and revisions can limit the data. Even a record on every day does not certify complete charges.
- The tool does not infer actual overage by subtracting service total from consumed or by summing commitment and service balances: those fields can have different billing scope.

A successful API response means the call succeeded, not that all historical billing data exists. Long contracts can take longer to retrieve. Validate billing totals against the corresponding OCI billing records before treating a returned subtotal as the full contractual amount.

Field definitions: [ComputedUsageAggregation](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/osub_usage/models/oci.osub_usage.models.ComputedUsageAggregation.html).

## Example outputs

All example amounts and identifiers are fictional:

- [Default summary and active forecast](sample-output.txt).
- [Expanded historical details](sample-output-history.txt).

## Requirements and troubleshooting

Python 3.7+, an OCI CLI with the `onesubscription` commands, an authenticated session, `OCI_TENANCY` and read access to subscription and usage data. Outside Cloud Shell, configure normal OCI CLI authentication and set the tenancy environment variable. The tool inherits CLI authentication/profile settings and does not modify credentials or tenancy configuration.

| Symptom | Action |
| --- | --- |
| `OCI_TENANCY is missing` | Run in Cloud Shell or set the target tenancy OCID explicitly. |
| IAM home-region discovery denied | If you know the tenancy home region, specify it with `--region`. |
| Please go to your home region | Verify the home region selected automatically or supplied with `--region`; ensure Cloud Shell can reach it. |
| No such command | Check the installed OCI CLI supports the required commands. |
| Authorization error | Check read access for the current identity and target subscription. |
| Missing forecast or overage | Inspect record coverage and the returned dates; missing data is not zero. |
| Zero balance beside promo credit | Check individual service lines: an empty standard companion can coexist with a promotional credit pool. |

One subscription failure does not stop the others. Errors go to stderr. Exit status 1 indicates a request error/partial failure, while 0 indicates successful requests, including an empty result. Missing data can leave a forecast unavailable despite successful requests. The final subscription counts reflect request success, not verified billing completeness.

The version header is `Report version: 1.7 | ahmet.bakkal@oracle.com`.

## Validation

```bash
python3 -m unittest discover -v
```

Offline tests use fictional data and cover multiple subscriptions, currencies, PoC and production pools, date coverage, fractional commitment horizons, required consumption, trend comments, reported/derived commitment consumption, historical summaries, overage scope, errors, pagination and explicit/automatic region selection. They do not execute live OCI calls.

## APIs

- [IAM region subscriptions](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/iam/region-subscription/list.html), unless `--region` is supplied.
- [Organization subscriptions](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/organization-subscription/organization-subscription/list.html).
- [Subscription details](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/subscription/subscription/list.html) with `--is-commit-info-required true`.
- [Aggregated computed usage](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/computed-usage/aggregated-computed-usage-summary/list-aggregated-computed-usages.html) with `--grouping DAILY` and `--all`.
- [Cost Analysis](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/usage-api/usage-summary/request-summarized-usages.html) with COST/DAILY subscription grouping and pagination.
