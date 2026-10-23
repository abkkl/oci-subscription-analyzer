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
- Every subscribed service, without hard-coded subscription IDs, SKU filters, or status filters.
- Subscription status and currency; service name, SKU, program, pricing model, and dates.
- Promotional credit, service total value, funded allocation, consumption, and available balance as separate fields.
- Every returned commitment period, including its quantity, net amount, funded allocation, consumption, and available balance.
- English labels and two-decimal amounts, for example `8,750.00`. Dates are displayed in UTC as `YYYY-MM-DD`.
- Three unused-credit forecasts based on the last 30 complete days, last 7 complete days, and the previous complete day's consumption.
- The last completed UTC calendar date and the latest completed usage date actually returned by OCI, shown separately.

The same report handles PoC and production records. The fields populated by OCI depend on the subscription and service type; successful execution does not imply that every billing field will be populated. Forecasts are printed as three separate compact blocks with a blank line after the `FORECAST` heading to avoid a very wide table wrapping in Cloud Shell.

## Example output

The following balance excerpt uses fictional data:

```text
OCI SUBSCRIPTION AND BALANCE REPORT
— = No value returned by the API. Service and commitment amounts are not added together.

==============================================================================
SUBSCRIPTION example-subscription | ACTIVE | USD
==============================================================================

1. Oracle Cloud Program - Universal Credits
SKU: B89010 | Status: ACTIVE
Program: BYINVITE-POC-STD | Model: Pay As You Go
Period (UTC): 2026-01-01 → 2026-12-31

Amount              | USD
--------------------+----------
Promotional credit  | 10,000.00
Service total value | 0.00
Funded allocation   | —
Consumed            | 1,250.00
REMAINING BALANCE   | 8,750.00

Commitment periods: 0

Subscriptions: 1 | Successful: 1 | Failed: 0
```

When commitment records are returned, each service also includes a table:

```text
Start UTC  | End UTC    | Quantity  | Net amount | Funded | Consumed | Remaining
-----------+------------+-----------+------------+--------+----------+----------
2026-01-01 | 2026-12-31 | 10,000.00 | 10,000.00  | —      | 1,250.00 | 8,750.00
```

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

Zero-valued companion service rows do not prevent that scenario. This handles PoC records whose credit balance and computed usage appear on different service lines. No SKU or subscription ID is hard-coded.

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
Beyond credit          = max(0, additional consumption − current reported remaining balance)
```

`Beyond credit` is an estimate of consumption exceeding the credit, not a prediction of an invoice or confirmation that the account can continue running after credits are exhausted. The model assumes a constant daily rate, with no new credits or changes to pricing, workload, allocation, or expiry terms. Forecasts are estimates and are printed separately from reported balances.

### Forecast horizon

- For services without commitment periods, the horizon is the service's reported end date, using its reported available balance.
- For services with commitment periods, the horizon is the **one currently active commitment period's end date**, using that period's available balance. Recent consumption from the same service can span earlier commitment periods. The report does not assume monthly credit rolls over, forecast future renewals, or add future commitments to the current balance.
- If there is no unique active commitment, no finite end date, or no valid available balance, the report leaves the projected amount unavailable. Non-active services are also not forecast.

The output labels the horizon explicitly; a commitment-period forecast must not be interpreted as a full-contract forecast when their end dates differ.

### Complete calendar day versus available billing data

```text
Last completed calendar day (UTC): 2026-10-22
Latest reported completed usage day (UTC): 2026-10-21
```

These dates can differ because billing data may arrive later. The latest reported date is for the matching service and currency within the requested 30-day range. The report does not silently replace yesterday with an older day.

Each scenario includes a `Days` coverage column, such as `7/7`. If a daily record is missing, the window's forecast is unavailable instead of assuming zero spend. An explicit zero-cost record is valid. This conservative rule means a genuinely idle day with no record is also unavailable. Even `7/7` proves only that each date has a record, not that OCI has finished processing every charge; values may be revised later.

If the service has not existed for the full window, or net consumption is negative, that scenario is also unavailable. A usage request failure leaves the balance report visible and returns exit status `1`; an alternate source can still produce explicitly labelled estimates where matching data is available.

### Confirm which version is running

This revision prints `Report version: 1.1` near the top. If you see the old wide forecast table, you are running an earlier version. Until you publish your updated files to GitHub, downloading from the repository's `main` URL will continue to fetch the previously published version. Upload the revised `oci_balance.py` to Cloud Shell and run `python3 ~/oci_balance.py` to test it first.

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
