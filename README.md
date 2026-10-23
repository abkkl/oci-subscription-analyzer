# OCI Subscription Analyzer

A read-only command-line report for OCI subscriptions, promotional credits, service balances, and commitment periods. Uses the OCI CLI's existing authentication, including the native session in OCI Cloud Shell.

## Run in OCI Cloud Shell

Open **OCI Console → Cloud Shell** and paste:

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

The same report handles PoC and production records. The fields populated by OCI depend on the subscription and service type; successful execution does not imply that every billing field will be populated.

## Example output

The following data is fictional:

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

Service amounts and commitment-period amounts may describe overlapping balances, so the report does **not** add them together. It also does not sum currencies or infer a monetary balance from a commitment's quantity. All amounts come from the API; there is no fallback estimate based on Cost Analysis.

## Requirements and scope

- Python 3.7 or later, using only the standard library.
- OCI CLI with the `onesubscription` commands below.
- `OCI_TENANCY` set to the target tenancy OCID (provided by Cloud Shell).
- An authenticated OCI CLI session and permission to read the target subscriptions.

Outside Cloud Shell, configure the OCI CLI using your preferred supported authentication method, then set `OCI_TENANCY` before running the script. The script inherits the CLI's profile, region, and authentication settings; it does not create or modify credentials.

"All subscriptions" means all subscriptions returned to the current identity for the selected tenancy. It does not automatically sign in to other tenancies or enumerate every tenancy in an organization.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `OCI_TENANCY is missing` | Run inside Cloud Shell or explicitly set the target tenancy OCID. |
| `oci` is not found | Install the OCI CLI or use Cloud Shell. |
| `No such command` | Check whether the installed CLI supports the documented `onesubscription` commands. |
| Authorization error | Confirm the CLI identity and its access to the tenancy's subscription data. |
| Download or connection error | Check network access, the configured CLI region, and service availability. |
| A zero balance beside promotional credit | Read the individual service rows and SKUs. A standard service row can be zero while a separate promotional service row holds the credit. |
| Empty or missing balance fields | Compare the subscription details in the Console; the script cannot display amounts the API does not return. |

If one subscription fails, the report continues with the others, writes the error to stderr, and reports the failure count. Exit status is `1` for an error or partial failure, and `0` for a successful run, including a successful empty subscription list.

## Validation

Run the offline regression checks:

```bash
python3 -m unittest discover -v
```

These checks cover mixed promotional and standard service rows, production commitment periods, explicit zero versus missing values, and continuing after a subscription failure. They use fictional fixtures and do not call OCI. Live behavior still depends on the target tenancy, CLI version, and permissions.

## OCI APIs used

1. [List organization subscriptions](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/organization-subscription/organization-subscription/list.html) to discover subscription IDs.
2. [List subscription details](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/onesubscription/subscription/subscription/list.html) with `--is-commit-info-required true` to retrieve service and commitment data.
