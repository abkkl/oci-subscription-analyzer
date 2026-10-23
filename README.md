# OCI Subscription Analyzer

A read-only command-line report for OCI subscriptions, promotional credits, service balances, and commitment periods. Uses the OCI CLI's existing authentication, including the native session in OCI Cloud Shell.

## Run in OCI Cloud Shell

Open **OCI Console → Cloud Shell** and paste:

**Use your tenancy's home region for billing and usage operations.** The script discovers the home region using IAM region subscriptions and explicitly selects it for subsequent API calls. If region discovery fails, the script stops with an explanation rather than guessing a region. Cloud Shell network access must also permit calls to that region; starting Cloud Shell in the home region is recommended.

```bash
curl -fsSL https://raw.githubusercontent.com/abkkl/oci-subscription-analyzer/main/oci_balance.py -o oci_balance.py && python3 oci_balance.py
```

Or clone the repository:

```bash
git clone https://github.com/abkkl/oci-subscription-analyzer.git
cd oci-subscription-analyzer
python3 oci_balance.py
```

No password, API key setup, Python packages, or `config.ini` file is required in Cloud Shell. The script invokes the pre-authenticated `oci` CLI and reads the tenancy OCID from `OCI_TENANCY`. Your user still needs permission to read subscription information. Downloading from GitHub also requires public internet access from Cloud Shell.

## What the report includes

- Every subscription returned for the current tenancy, with all API pages fetched.
- All returned subscribed services are inspected without hard-coded IDs or SKUs. Empty zero-credit companion lines are summarized in a note rather than a separate section.
- Subscription status and currency; service name, SKU, program, pricing model, and dates.
- Promotional credit, service total value, funded allocation, consumption, and available balance as separate fields.
- Every returned commitment period, including its quantity, net amount, funded allocation, consumption, and available balance.
- English labels and two-decimal amounts, for example `8,750.00`. Dates are displayed in UTC as `YYYY-MM-DD`.
- Three unused-credit forecasts based on the last 30 complete days, last 7 complete days, and the previous complete day's consumption.
- The last completed UTC calendar date and the latest completed usage date actually returned by OCI, shown separately.

The same report handles PoC and production records. The fields populated by OCI depend on the subscription and service type; successful execution does not imply that every billing field will be populated. The three scenarios are combined in one compact forecast table, with a blank line after the `FORECAST` heading. Numeric amounts are right-aligned. Service names have distinct section headings. Terminal headings use subtle color when stdout is a terminal; set `NO_COLOR=1` to disable color.

## Example output

The following output uses fictional data:

```text
==============================================================================
SUBSCRIPTION example | ACTIVE | TRY
==============================================================================
Contract end (UTC): 2026-11-02 | 0 months 10 days remaining (10 days total)
End date based on reported service contract dates.

Note: STANDARD — Example credits omitted: zero reported credit and consumption
(including commitment amounts).

──────────────────────────────────────────────────────────────────────────────
SERVICE 1 | PROMO
Example credits
──────────────────────────────────────────────────────────────────────────────
Status: ACTIVE
Program: — | Model: —
Period (UTC): 2026-08-01 → 2026-11-02
Contract end (UTC): 2026-11-02 | 0 months 10 days remaining (10 days total)

BALANCES (TRY)
Promo credit | Service total | Funded | Consumed | Remaining | Overage
-------------+---------------+--------+----------+-----------+--------
   10,000.00 |             — |      — |        — |  9,000.00 |    0.00

Commitment periods: 0

FORECAST (TRY) | Horizon: Service contract end - 2026-11-02

Balance snapshot UTC: 2026-10-23 00:00:00
Latest reported completed usage day (UTC): 2026-10-22

Baseline                               | Avg/day Consumption | Remaining Credit | Future Consumption | Unused Credit at End - Total | Unused Credit at End - Daily | Overage Credit at End | Contract days left | Coverage | Result
---------------------------------------+---------------------+------------------+--------------------+------------------------------+------------------------------+-----------------------+--------------------+----------+---------
Last 30 days (2026-09-23 - 2026-10-22) |               10.00 |         9,000.00 |             100.00 |                     8,900.00 |                       890.00 |                  0.00 | 10                 | 30/30    | Estimate
Last 7 days (2026-10-16 - 2026-10-22)  |               10.00 |         9,000.00 |             100.00 |                     8,900.00 |                       890.00 |                  0.00 | 10                 | 7/7      | Estimate
Previous day (2026-10-22 - 2026-10-22) |               10.00 |         9,000.00 |             100.00 |                     8,900.00 |                       890.00 |                  0.00 | 10                 | 1/1      | Estimate

Estimate = remaining credit - future consumption, minimum zero.
Missing days are not treated as zero.
Reported usage may still be delayed or revised.
```

Nonzero services appear under distinct `SERVICE` headings, including the full service name. Each service has one consolidated balances table, one commitment table if periods exist, and one three-row forecast table. Empty companion services are represented only by an omission note.

## How to read the amounts

| Report field | OCI response field | Meaning |
| --- | --- | --- |
| Promotional credit | `original-promo-amount` | Original promotional credit reported for the service. |
| Service total value | `total-value` | Total value reported for the service; can be zero even when promotional credit exists. |
| Funded allocation | `funded-allocation-value` | Funded allocation reported for the service. |
| Consumed | `used-amount` | Reported consumption. |
| REMAINING BALANCE | `available-amount` | Reported available balance for that service. |

`—` means the API did not return a value. Explicit zeros remain `0.00`. Missing values, including the literal string `"null"`, are never converted to zero.

Service amounts and commitment-period amounts may describe overlapping balances, so the report does **not** add them together. It also does not sum currencies or infer a monetary balance from a commitment's quantity. Displayed balances come from OneSubscription. Cost Analysis is used only for the consumption rates in the separately labelled forecast.

## Consumption forecasts

The report requests the previous 30 complete UTC days from two sources, explicitly using the detected home region:

1. **Cost Analysis (Usage API)** returns daily `computed-amount` grouped and filtered by subscription ID. Response rows are checked again for the exact subscription ID, currency, and completed daily intervals. Pagination is followed.
2. **OneSubscription computed usage** provides service-level records matched by exact parent subscribed service ID and currency, using `cost-unrounded` per metered day.

When exactly one service in a currency is identified as a credit pool (reported promotional, funded, service-total, consumed, available, or commitment-available amount is positive), the report can use matching Cost Analysis daily costs. This is explicitly labelled a **subscription-level estimate**, with the assumption that all reported subscription costs consume that pool. One positive pool is not proof of billing allocation. Differences between subscription costs and credit-eligible consumption can affect the estimate.

Zero-valued companion service rows do not prevent that scenario. This handles PoC records whose credit balance and computed usage appear on different service lines. No SKU or subscription ID is hard-coded. A service is omitted only when its reported available and consumed amounts are explicitly zero and no nonzero credit or commitment amounts are present. Previously funded but exhausted services and services with unknown amounts remain visible.

When multiple credit pools exist, the script does not assign the entire subscription's cost to each pool. It falls back to exact service-level computed usage. Missing service-level data leaves the forecast unavailable. A tenancy-wide total is never assigned to a subscription or service, and currencies are never mixed.

The report shows three independent scenarios:

| Baseline | Daily rate |
| --- | --- |
| Last 30 days | Reported net consumption over the last 30 complete UTC days divided by 30. |
| Last 7 days | Reported net consumption over the last 7 complete UTC days divided by 7. |
| Previous day | Reported net consumption on the previous complete UTC day. |

"One month" means a rolling 30-day window, not the previous calendar month. The current incomplete day is excluded from all three baselines. For a run on October 23, the last completed calendar day is October 22 (UTC).

Each scenario projects:

```text
Additional consumption = daily rate × fractional days until the forecast horizon
Unused credit at end   = max(0, current reported remaining balance − additional consumption)
Overage          = max(0, additional consumption − current reported remaining balance)
```

`Overage` is an estimate of consumption exceeding the credit, not a prediction of an invoice or confirmation that the account can continue running after credits are exhausted. The model assumes a constant daily rate, with no new credits or changes to pricing, workload, allocation, or expiry terms. Forecasts are estimates and are printed separately from reported balances.

### Forecast horizon

- For services without commitment periods, the horizon is the service's reported end date, using its reported available balance.
- For services with commitment periods, the horizon is the **one currently active commitment period's end date**, using that period's available balance. Recent consumption from the same service can span earlier commitment periods. The report does not assume monthly credit rolls over, forecast future renewals, or add future commitments to the current balance.
- If there is no unique active commitment, no finite end date, or no valid available balance, the report leaves the projected amount unavailable. Non-active services are also not forecast.

The output labels the horizon explicitly; a commitment-period forecast must not be interpreted as a full-contract forecast when their end dates differ.

### Complete calendar day versus available billing data

```text
Latest reported completed usage day (UTC): 2026-10-21
```

The latest reported date can precede the previous complete UTC day because billing data may arrive later. The latest reported date is for the matching service and currency within the requested 30-day range. The report does not silently replace yesterday with an older day.

Each scenario includes a `Coverage` column, such as `7/7`. If a daily record is missing, the window's forecast is unavailable instead of assuming zero spend. An explicit zero-cost record is valid. This conservative rule means a genuinely idle day with no record is also unavailable. Even `7/7` proves only that each date has a record, not that OCI has finished processing every charge; values may be revised later.

If the service has not existed for the full window, or net consumption is negative, that scenario is also unavailable. A usage request failure leaves the balance report visible and returns exit status `1`; an alternate source can still produce explicitly labelled estimates where matching data is available.

### Confirm which version is running

This revision prints `Report version: 1.6` near the top. If you see three separate forecast tables or a separate empty zero-credit service section, you are running an earlier version. Until you publish your updated files to GitHub, downloading from the repository's `main` URL will continue to fetch the previously published version. Upload the revised `oci_balance.py` to Cloud Shell and run `python3 ~/oci_balance.py` to test it first.

For a reproducible reference date:

```bash
python3 oci_balance.py --as-of 2026-10-23
```

`--as-of` sets the window boundary and projection reference to midnight UTC on that date. Balances are still fetched live; this is **not a historical balance report**. Use a balance snapshot corresponding to the reference date when evaluating historical projections. Without the option, the script uses the current UTC time.

## Requirements and scope

- Python 3.7 or later, using only the standard library.
- OCI CLI with the `onesubscription` commands below.
- `OCI_TENANCY` set to the target tenancy OCID (provided by Cloud Shell).
- An authenticated OCI CLI session and permission to read tenancy region subscriptions, target subscriptions, and computed usage.

Outside Cloud Shell, configure the OCI CLI using your preferred supported authentication method, then set `OCI_TENANCY` before running the script. The script inherits the CLI's profile and authentication settings, and explicitly selects the discovered home region for billing calls. It does not modify your CLI configuration or create credentials.

"All subscriptions" means all subscriptions returned to the current identity for the selected tenancy. It does not automatically sign in to other tenancies or enumerate every tenancy in an organization.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `OCI_TENANCY is missing` | Run inside Cloud Shell or explicitly set the target tenancy OCID. |
| `oci` is not found | Install the OCI CLI or use Cloud Shell. |
| `No such command` | Check whether the installed CLI supports the documented `onesubscription` commands. |
| Authorization error | Confirm the CLI identity and its access to the tenancy's subscription data. |
| Download or connection error | Check network access, the configured CLI region, and service availability. |
| `Please go to your home region to execute this operation` | Run the operation with `--region` set to the tenancy home region. The script now discovers this automatically. Start Cloud Shell in the home region if cross-region network access is restricted. |
| A zero balance beside promotional credit | Read the individual service rows and SKUs. A standard service row can be zero while a separate promotional service row holds the credit. |
| Empty or missing balance fields | Compare the subscription details in the Console; the script cannot display amounts the API does not return. |

If one subscription fails, the report continues with the others, writes the error to stderr, and reports the failure count. Exit status is `1` for an error or partial failure, and `0` for a successful run, including a successful empty subscription list.

## Validation

Run the offline regression checks:

```bash
python3 -m unittest discover -v
```

These checks cover mixed promotional and standard service rows, production commitment periods, three independent forecast windows, date boundaries, missing days versus explicit zero spend, credit overrun, service/currency isolation, commitment horizons, and continuing after a subscription failure. They use fictional fixtures and do not call OCI. Live behavior still depends on the target tenancy, CLI version, and permissions.

## OCI APIs used

Home region discovery uses [List region subscriptions](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/iam/region-subscription/list.html).

1. [List organization subscriptions](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/organization-subscription/organization-subscription/list.html) to discover subscription IDs.
2. [List subscription details](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/subscription/subscription/list.html) with `--is-commit-info-required true` to retrieve service and commitment data.
3. [List aggregated computed usage](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/computed-usage/aggregated-computed-usage-summary/list-aggregated-computed-usages.html) with `--grouping DAILY` to calculate the three recent-consumption scenarios.
4. [Request summarized usage](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/usage-api/usage-summary/request-summarized-usages.html) with `--query-type COST`, `--granularity DAILY`, and subscription ID grouping/filtering for the subscription-level forecast scenario.

Contract countdowns use UTC calendar dates: whole calendar months plus remaining days, with the total day count also shown. Today is excluded from the total. When the subscription API does not return an end date, a common service contract end date is used; differing service end dates are shown separately. Expired contracts and contracts ending today are labeled explicitly. This countdown does not change the forecast horizon or its fractional-day calculation.

### Actual overage

In each balances table, `Overage` sums only explicit `OVERAGE` usage records for that service and currency, requested from the service contract start through the report snapshot. Other usage types (including PAY_AS_YOU_GO) are not classified as overage. Signed adjustments are retained. This is the net overage in records returned by OCI, not a certified invoice total; API retention, delayed records, or revisions can affect it. Missing or untyped matching records show `—`, not zero. The forecast `Overage Credit at End` column estimates additional future consumption beyond the remaining credit; it does not add already reported actual overage. Long contracts can take longer to retrieve because all usage pages are requested.

The usage type and amount fields are documented in [Oracle ComputedUsageAggregation](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/osub_usage/models/oci.osub_usage.models.ComputedUsageAggregation.html).

Forecast layout: `Coverage` shows available daily records for each baseline. `Contract days left` shows whole UTC calendar days from the report date to the service contract end, excluding today (zero for expired contracts). This can differ from the active commitment horizon explicitly shown above the forecast. `Overage Credit at End` remains max(0, daily rate × fractional days to the stated forecast horizon − reported remaining credit); it is future overage through that horizon and excludes actual overage already shown in balances.

### Forecast columns

Each baseline includes its complete UTC date range. The heading includes the forecast horizon, end date and currency. `Avg/day Consumption` is the baseline daily average; `Remaining Credit` is the reported balance of the forecast pool (the active commitment when applicable). `Future Consumption` uses that average times the fractional days remaining to the stated forecast horizon. `Unused Credit at End - Total` is max(0, remaining credit minus future consumption). `Unused Credit at End - Daily` divides that total by `Contract days left`, which uses UTC calendar dates and the service contract end; it is unavailable when no days remain or the date is missing. `Overage Credit at End` is max(0, future consumption minus remaining credit), excluding previously reported actual overage. `Contract days left` appears before `Coverage`. The full table requires a wide terminal.

When all three forecast scenarios are unavailable, the report prints only `Forecast unavailable (CURRENCY): reason.` instead of an empty table. Inactive services and unavailable commitment horizons take precedence in the reason. If at least one scenario is calculable, the forecast table remains visible, with unavailable rows marked N/A.

### Loading indicator

After the home region is shown, interactive terminals display a cyan animated spinner with the current API stage, subscription identifier where applicable, and elapsed seconds per request. It clears when the request completes, including on errors. Output redirected to files or pipes and TERM=dumb omit the animation; NO_COLOR disables its color.

Version 1.6 includes animated loading. The indicator uses stdout when it is a terminal, otherwise stderr if that is a terminal. If both streams are redirected or TERM=dumb, animation is suppressed. Verify the report starts with `Report version: 1.6 | Animated loading, balances and forecasts` after replacing the script.
