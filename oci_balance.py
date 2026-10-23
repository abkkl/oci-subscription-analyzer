#!/usr/bin/env python3
"""Read subscription balances using the existing OCI CLI session."""
import json
import argparse
import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone


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


def decimal_value(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def daily_usage(groups, service_id, currency, cutoff):
    """Match exact service and currency; never substitute another service's spend."""
    totals = {}
    for group in groups:
        if group.get("parent-subscribed-service-id") != service_id:
            continue
        if not currency or group.get("currency-code") != currency:
            continue
        for row in group.get("aggregated-computed-usages") or []:
            metered = timestamp(row.get("time-metered-on"))
            if metered is None:
                raise ValueError("A matching usage record has no valid metered date.")
            if metered >= cutoff or metered < cutoff - timedelta(days=30):
                continue
            cost = decimal_value(row.get("cost-unrounded"))
            if cost is None:
                raise ValueError("A matching usage record has no valid cost-unrounded amount.")
            day = metered.date()
            totals[day] = totals.get(day, Decimal(0)) + cost
    return totals


def forecast_rows(record, daily, as_of, history_start=None):
    """Use fixed 30/7/1-day windows, excluding the current incomplete UTC day."""
    start = timestamp(record.get("time-start"))
    history_start = history_start or start
    end = timestamp(record.get("time-end"))
    available = decimal_value(record.get("available-amount"))
    cutoff = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_error = None
    if start is None or end is None or not start < as_of < end:
        horizon_error = "No active finite forecast period"
    elif available is None or available < 0:
        horizon_error = "Missing/non-negative balance required"
    result = []
    for days, label in ((30, "Last 30 days"), (7, "Last 7 days"), (1, "Previous day")):
        first = cutoff - timedelta(days=days)
        dates = [(first + timedelta(days=i)).date() for i in range(days)]
        covered = sum(day in daily for day in dates)
        reason = horizon_error
        if history_start is not None and history_start > first:
            reason = "Service history shorter than window"
        if covered != days:
            reason = "Missing daily usage records"
        total = sum((daily.get(day, Decimal(0)) for day in dates), Decimal(0))
        if total < 0:
            reason = "Negative net consumption"
        rate = total / Decimal(days) if covered == days and total >= 0 and (history_start is None or history_start <= first) else None
        unused = beyond = None
        if reason is None:
            remaining_days = Decimal(str((end - as_of).total_seconds())) / Decimal(86400)
            extra = rate * remaining_days
            unused = max(Decimal(0), available - extra)
            beyond = max(Decimal(0), extra - available)
        result.append({"label": label, "first": first.date(), "last": dates[-1],
                       "coverage": f"{covered}/{days}", "rate": rate,
                       "unused": unused, "beyond": beyond, "reason": reason})
    return result


def render_recent_forecast(service, currency, as_of, groups, usage_error=None):
    cutoff = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"\nFORECAST | Balance snapshot UTC: {as_of.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Last completed calendar day (UTC): {(cutoff - timedelta(days=1)).date()}")
    try:
        daily = daily_usage(groups or [], service.get("id"), currency, cutoff) if service.get("id") else {}
    except ValueError as exc:
        daily, usage_error = {}, str(exc)
    latest = max(daily).isoformat() if daily else "No matching usage returned"
    print(f"Latest reported completed usage day (UTC): {latest}")
    target = service
    scope = "Service contract end"
    commitments = service.get("commitment-services") or []
    if commitments:
        active = [c for c in commitments if timestamp(c.get("time-start")) is not None
                  and timestamp(c.get("time-end")) is not None
                  and timestamp(c["time-start"]) <= as_of < timestamp(c["time-end"])]
        if len(active) == 1:
            target = active[0]
            scope = "Active commitment end (future renewals are not forecast)"
        else:
            target = {}
            scope = "Unavailable: no unique active commitment period"
    if service.get("status") not in (None, "ACTIVE"):
        target = {}
        scope = "Unavailable: service is not ACTIVE"
    print(f"Forecast horizon: {scope} | {date(target.get('time-end'))}")
    print(f"Amounts: {shown(currency)} | 1 month = 30 complete UTC days; no currency conversion.")
    rows = forecast_rows(target, daily, as_of, timestamp(service.get("time-start")))
    if usage_error:
        print(f"Usage unavailable: {usage_error}")
        for row in rows:
            row.update(rate=None, unused=None, beyond=None, reason="Usage request failed")
    table(
        ["Baseline", "From UTC", "Through UTC", "Days", "Avg/day", "Unused at end", "Beyond credit", "Status"],
        [[r["label"], r["first"], r["last"], r["coverage"], number(r["rate"]),
          number(r["unused"]), number(r["beyond"]), r["reason"] or "Estimate"] for r in rows],
    )
    print("Estimate = max(0, reported remaining credit - daily rate x days to horizon).")
    print("Missing days are not treated as zero; reported usage may still be delayed or revised.")


def table(headers, rows):
    widths = [max(len(str(row[i])) for row in [headers, *rows]) for i in range(len(headers))]
    def line(row):
        return " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(line(row))


def render(subscription_id, summaries, as_of=None, usage=None, usage_error=None):
    as_of = as_of or datetime.now(timezone.utc)
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
            render_recent_forecast(service, currency, as_of, usage, usage_error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="Forecast reference date at 00:00 UTC; defaults to the current UTC time. Uses current API balances; this option does not retrieve historical balances.")
    args = parser.parse_args(argv)
    as_of = datetime.now(timezone.utc)
    if args.as_of:
        try:
            as_of = datetime.strptime(args.as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            parser.error("--as-of must be a valid date in YYYY-MM-DD format.")
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
            cutoff = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
            usage, usage_error = [], None
            try:
                usage = cli("onesubscription", "computed-usage", "aggregated-computed-usage-summary", "list-aggregated-computed-usages",
                            "--compartment-id", tenancy, "--subscription-id", str(subscription_id),
                            "--time-from", (cutoff - timedelta(days=30)).isoformat(),
                            "--time-to", cutoff.isoformat(), "--grouping", "DAILY", "--all")
            except (RuntimeError, OSError) as exc:
                usage_error = str(exc)
                failed += 1
                print(f"WARNING [{subscription_id}]: usage request failed: {exc}", file=sys.stderr)
            render(subscription_id, summaries, as_of, usage, usage_error)
        except (RuntimeError, OSError) as exc:
            failed += 1
            print(f"\nERROR [{subscription_id}]: {exc}", file=sys.stderr)
    print(f"\nSubscriptions: {len(ids)} | Successful: {len(ids) - failed} | Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
