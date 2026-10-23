#!/usr/bin/env python3
"""Read subscription balances using the existing OCI CLI session."""
import json
import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation


def cli(*args):
    result = subprocess.run(
        ["oci", *args, "--output", "json"], capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "OCI CLI call failed.")
    try:
        body = json.loads(result.stdout)
        data = body["data"]
        if not isinstance(data, list):
            raise ValueError("Expected an array response.")
        return data
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"Could not read the API response: {exc}") from exc


def shown(value):
    return "—" if value is None or str(value).strip().lower() in ("", "null", "none") else str(value)


def number(value):
    if shown(value) == "—":
        return "—"
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return shown(value)
        return format(amount, ",.2f")
    except InvalidOperation:
        return shown(value)


def date(value):
    return shown(value).split("T")[0]


def table(headers, rows):
    widths = [max(len(str(row[i])) for row in [headers, *rows]) for i in range(len(headers))]
    def line(row):
        return " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(line(row))


def render(subscription_id, summaries):
    for summary in summaries:
        currency = (summary.get("currency") or {}).get("iso-code")
        print("\n" + "=" * 78)
        print(f"SUBSCRIPTION {subscription_id} | {shown(summary.get('status'))} | {shown(currency)}")
        print("=" * 78)
        services = summary.get("subscribed-services") or []
        if not services:
            print("No service records returned.")
        for index, service in enumerate(services, 1):
            product = service.get("product") or {}
            print(f"\n{index}. {shown(product.get('name'))}")
            print(f"SKU: {shown(product.get('part-number'))} | Status: {shown(service.get('status'))}")
            print(f"Program: {shown(service.get('program-type'))} | Model: {shown(service.get('pricing-model'))}")
            print(f"Period (UTC): {date(service.get('time-start'))} → {date(service.get('time-end'))}")
            print()
            fields = [
                ("Promotional credit", "original-promo-amount"),
                ("Service total value", "total-value"),
                ("Funded allocation", "funded-allocation-value"),
                ("Consumed", "used-amount"),
                ("REMAINING BALANCE", "available-amount"),
            ]
            table(["Amount", shown(currency)], [[label, number(service.get(key))] for label, key in fields])
            commitments = service.get("commitment-services") or []
            print(f"\nCommitment periods: {len(commitments)}")
            if commitments:
                table(
                    ["Start UTC", "End UTC", "Quantity", "Net amount", "Funded", "Consumed", "Remaining"],
                    [[date(c.get("time-start")), date(c.get("time-end")),
                      *[number(c.get(key)) for key in ("quantity", "line-net-amount", "funded-allocation-value", "used-amount", "available-amount")]]
                     for c in commitments],
                )


def main():
    tenancy = os.environ.get("OCI_TENANCY")
    if not tenancy:
        print("ERROR: OCI_TENANCY is missing. Run this script in OCI Cloud Shell.", file=sys.stderr)
        return 1
    try:
        subscriptions = cli("onesubscription", "organization-subscription", "organization-subscription", "list", "--compartment-id", tenancy, "--all")
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ids = list(dict.fromkeys(s["id"] for s in subscriptions if s.get("id")))
    if not ids:
        print("No accessible subscriptions found.")
        return 0
    print("OCI SUBSCRIPTION AND BALANCE REPORT")
    print("— = No value returned by the API. Service and commitment amounts are not added together.")
    failed = 0
    for subscription_id in ids:
        try:
            summaries = cli("onesubscription", "subscription", "subscription", "list", "--compartment-id", tenancy, "--subscription-id", str(subscription_id), "--is-commit-info-required", "true", "--all")
            if not summaries:
                raise RuntimeError("No subscription details returned.")
            render(subscription_id, summaries)
        except (RuntimeError, OSError) as exc:
            failed += 1
            print(f"\nERROR [{subscription_id}]: {exc}", file=sys.stderr)
    print(f"\nSubscriptions: {len(ids)} | Successful: {len(ids) - failed} | Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
