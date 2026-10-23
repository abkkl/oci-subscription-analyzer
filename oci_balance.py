#!/usr/bin/env python3
"""Read subscription balances using the existing OCI CLI session."""
import json
import argparse
import os
import subprocess
import sys
import re
import textwrap
import calendar
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

CLI_REGION = None


def cli_payload(*args):
    region_args = ["--region", CLI_REGION] if CLI_REGION else []
    result = subprocess.run(
        ["oci", *region_args, *args, "--output", "json"], capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "OCI CLI call failed.")
    try:
        body = json.loads(result.stdout)
        return body
    except ValueError as exc:
        raise RuntimeError(f"Could not read the API response: {exc}") from exc


def cli(*args):
    try:
        data = cli_payload(*args)["data"]
        if not isinstance(data, list):
            raise ValueError("Expected an array response.")
        return data
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"Could not read the API response: {exc}") from exc


def home_region(tenancy):
    regions = cli("iam", "region-subscription", "list", "--tenancy-id", tenancy, "--all")
    homes = [r.get("region-name") for r in regions if r.get("is-home-region") is True and r.get("region-name")]
    if len(homes) != 1:
        raise RuntimeError("Could not identify one home region. Run Cloud Shell in the tenancy home region and check IAM region-subscription read access.")
    return homes[0]


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


def contract_countdown(value, as_of):
    end = timestamp(value)
    if end is None:
        return "Unavailable"
    today, last = as_of.astimezone(timezone.utc).date(), end.date()
    days = (last - today).days
    if end <= as_of:
        return f"{last} | Expired"
    if days == 0:
        return f"{last} | Ends today (0 days remaining)"
    months = (last.year - today.year) * 12 + last.month - today.month
    def anniversary(count):
        year, month = divmod(today.year * 12 + today.month - 1 + count, 12)
        month += 1
        return today.replace(year=year, month=month,
                             day=min(today.day, calendar.monthrange(year, month)[1]))
    if anniversary(months) > last:
        months -= 1
    remainder = (last - anniversary(months)).days
    return f"{last} | {months} months {remainder} days remaining ({days} days total)"


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


def fetch_cost_usage(tenancy, subscription_id, cutoff):
    """Fetch Cost Analysis daily costs in the detected home region, including pages."""
    rows, page, seen = [], None, set()
    while True:
        args = ["usage-api", "usage-summary", "request-summarized-usages",
                "--tenant-id", tenancy, "--granularity", "DAILY", "--query-type", "COST",
                "--time-usage-started", (cutoff - timedelta(days=30)).isoformat(),
                "--time-usage-ended", cutoff.isoformat(), "--group-by", '["subscriptionId"]',
                "--filter", json.dumps({"operator": "AND", "dimensions": [
                    {"key": "subscriptionId", "value": str(subscription_id)}]}),
                "--is-aggregate-by-time", "false", "--limit", "1000"]
        if page:
            args.extend(["--page", page])
        payload = cli_payload(*args)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise RuntimeError("Cost Analysis returned an unexpected response shape.")
        rows.extend(data["items"])
        page = payload.get("opc-next-page")
        if not page:
            return rows
        if page in seen:
            raise RuntimeError("Cost Analysis repeated a pagination token.")
        seen.add(page)


def subscription_daily_usage(rows, subscription_id, currency, cutoff):
    totals = {}
    for row in rows:
        if str(row.get("subscription-id")) != str(subscription_id) or row.get("currency") != currency:
            continue
        if row.get("is-forecast") is True:
            continue
        start = timestamp(row.get("time-usage-started"))
        end = timestamp(row.get("time-usage-ended"))
        if start is None or end is None:
            raise ValueError("Cost Analysis returned a matching record without valid dates.")
        if start < cutoff - timedelta(days=30) or end > cutoff or start >= cutoff:
            continue
        if start.time() != datetime.min.time() or end - start != timedelta(days=1):
            raise ValueError("Cost Analysis returned a non-daily usage interval.")
        cost = decimal_value(row.get("computed-amount"))
        if cost is None:
            raise ValueError("Cost Analysis returned a matching record without a valid amount.")
        totals[start.date()] = totals.get(start.date(), Decimal(0)) + cost
    return totals


def credit_pool_ids(summaries, currency):
    ids = set()
    for summary in summaries:
        if (summary.get("currency") or {}).get("iso-code") != currency:
            continue
        for service in summary.get("subscribed-services") or []:
            if not service.get("id") or service.get("status") not in (None, "ACTIVE"):
                continue
            amounts = [decimal_value(service.get(key)) for key in (
                "original-promo-amount", "total-value", "funded-allocation-value", "used-amount", "available-amount")]
            amounts += [decimal_value(c.get("available-amount")) for c in service.get("commitment-services") or []]
            if any(amount is not None and amount > 0 for amount in amounts):
                ids.add(service["id"])
    return ids


def is_zero_credit_service(service):
    """Hide empty companion lines, retaining exhausted or unknown credit pools."""
    keys = ("original-promo-amount", "total-value", "funded-allocation-value", "used-amount", "available-amount")
    amounts = [decimal_value(service.get(key)) for key in keys]
    for commitment in service.get("commitment-services") or []:
        amounts += [decimal_value(commitment.get(key)) for key in (
            "quantity", "line-net-amount", "funded-allocation-value", "used-amount", "available-amount")]
    if any(value is not None and value != 0 for value in amounts):
        return False
    return decimal_value(service.get("available-amount")) == 0 and decimal_value(service.get("used-amount")) == 0


def heading(title):
    use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    print(f"\033[1;36m{title}\033[0m" if use_color else title)


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


def render_recent_forecast(service, currency, as_of, groups, usage_error=None, daily_override=None):
    cutoff = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    print()
    heading("FORECAST")
    print()
    print(f"Balance snapshot UTC: {as_of.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Last completed calendar day (UTC): {(cutoff - timedelta(days=1)).date()}")
    try:
        if daily_override is not None:
            daily = daily_override
            usage_error = None
        else:
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
            scope = "Active commitment end"
        else:
            target = {}
            scope = "Unavailable: no unique active commitment period"
    if service.get("status") not in (None, "ACTIVE"):
        target = {}
        scope = "Unavailable: service is not ACTIVE"
    print(f"Forecast horizon: {scope}")
    print(f"Horizon end (UTC): {date(target.get('time-end'))}")
    if commitments:
        print("Future renewals and credit rollover are not forecast.")
    print(f"Amounts: {shown(currency)} | 1 month = 30 complete UTC days.")
    rows = forecast_rows(target, daily, as_of, timestamp(service.get("time-start")))
    if usage_error:
        print(f"Usage unavailable: {usage_error}")
        for row in rows:
            row.update(rate=None, unused=None, beyond=None, reason="Usage request failed")
    print(f"Windows start (UTC): 30 days = {rows[0]['first']} | 7 days = {rows[1]['first']}")
    print()
    table(
        ["Baseline", "Avg/day", "Unused at end", "Beyond credit", "Days", "Result"],
        [[row["label"], number(row["rate"]), number(row["unused"]),
          number(row["beyond"]), row["coverage"], "N/A" if row["reason"] else "Estimate"]
         for row in rows],
    )
    reasons = {}
    for row in rows:
        if row["reason"]:
            reasons.setdefault(row["reason"], []).append(row["label"])
    for reason, labels in reasons.items():
        print(textwrap.fill(f"N/A ({', '.join(labels)}): {reason}", width=78))
    print()
    print("Estimate = remaining credit - future consumption, minimum zero.")
    print("Missing days are not treated as zero.")
    print("Reported usage may still be delayed or revised.")


def table(headers, rows):
    widths = [max(len(str(row[i])) for row in [headers, *rows]) for i in range(len(headers))]
    numeric_columns = [all(str(row[i]) == "—" or re.fullmatch(r"-?[\d,]+\.\d{2}", str(row[i])) for row in rows)
                       for i in range(len(headers))]
    def line(row, is_header=False):
        return " | ".join(str(cell).rjust(widths[i]) if numeric_columns[i] and not is_header
                          else str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
    print(line(headers, True))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(line(row))


def render(subscription_id, summaries, as_of=None, usage=None, usage_error=None, cost_usage=None, cost_error=None):
    as_of = as_of or datetime.now(timezone.utc)
    for summary in summaries:
        currency = (summary.get("currency") or {}).get("iso-code")
        print("\n" + "=" * 78)
        print(f"SUBSCRIPTION {subscription_id} | {shown(summary.get('status'))} | {shown(currency)}")
        print("=" * 78)
        services = summary.get("subscribed-services") or []
        if timestamp(summary.get("time-end")) is not None:
            print(f"Contract end (UTC): {contract_countdown(summary['time-end'], as_of)}")
        else:
            ends = sorted({timestamp(s.get("time-end")) for s in services
                           if timestamp(s.get("time-end")) is not None})
            if len(ends) == 1:
                print(f"Contract end (UTC): {contract_countdown(ends[0].isoformat(), as_of)}")
                print("End date based on reported service contract dates.")
            elif ends:
                print("Contract end (UTC): Multiple service end dates; see each service below.")
            else:
                print("Contract end (UTC): Unavailable")
        if not services:
            print("No service records returned.")
        omitted = [service for service in services if is_zero_credit_service(service)]
        if omitted:
            print()
            for service in omitted:
                product = service.get("product") or {}
                print(textwrap.fill(
                    f"Note: {shown(product.get('part-number'))} — {shown(product.get('name'))} omitted: "
                    "zero reported credit and consumption (including commitment amounts).", width=78))
        for index, service in enumerate(services, 1):
            if is_zero_credit_service(service):
                continue
            product = service.get("product") or {}
            print("\n" + "─" * 78)
            heading(f"SERVICE {index} | {shown(product.get('part-number'))}")
            heading(shown(product.get("name")))
            print("─" * 78)
            print(f"Status: {shown(service.get('status'))}")
            print(f"Program: {shown(service.get('program-type'))} | Model: {shown(service.get('pricing-model'))}")
            print(f"Period (UTC): {date(service.get('time-start'))} → {date(service.get('time-end'))}")
            print(f"Contract end (UTC): {contract_countdown(service.get('time-end'), as_of)}")
            print()
            heading(f"BALANCES ({shown(currency)})")
            table(["Promo credit", "Service total", "Funded", "Consumed", "Remaining"],
                  [[number(service.get(key)) for key in (
                      "original-promo-amount", "total-value", "funded-allocation-value", "used-amount", "available-amount")]])
            commitments = service.get("commitment-services") or []
            print(f"\nCommitment periods: {len(commitments)}")
            if commitments:
                table(
                    ["Start UTC", "End UTC", "Quantity", "Net amount", "Funded", "Consumed", "Remaining"],
                    [[date(c.get("time-start")), date(c.get("time-end")),
                      *[number(c.get(key)) for key in ("quantity", "line-net-amount", "funded-allocation-value", "used-amount", "available-amount")]]
                     for c in commitments],
                )
            daily_override = None
            candidates = credit_pool_ids(summaries, currency)
            if cost_usage is not None and candidates == {service.get("id")}:
                try:
                    cutoff = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
                    daily = subscription_daily_usage(cost_usage, subscription_id, currency, cutoff)
                    if daily:
                        daily_override = daily
                except ValueError as exc:
                    cost_error = str(exc)
            if cost_error:
                print(f"\nCost Analysis unavailable: {cost_error}")
            elif len(candidates) > 1:
                print("\nSubscription costs are not allocated: multiple credit pools exist.")
            render_recent_forecast(service, currency, as_of, usage, usage_error, daily_override)


def main(argv=None):
    global CLI_REGION
    CLI_REGION = None
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
    print("OCI SUBSCRIPTION AND BALANCE REPORT")
    print("Report version: 1.2 | Consolidated tables and credit forecasts")
    print("Region note: Run Cloud Shell in the tenancy home region.")
    try:
        CLI_REGION = home_region(tenancy)
        print(f"Home region: {CLI_REGION} (selected automatically for API calls)")
        subscriptions = cli("onesubscription", "organization-subscription", "organization-subscription", "list", "--compartment-id", tenancy, "--all")
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ids = list(dict.fromkeys(s["id"] for s in subscriptions if s.get("id")))
    if not ids:
        print("No accessible subscriptions found.")
        return 0
    print("— = No value returned by the API. Service and commitment amounts are not added together.")
    failed = 0
    for subscription_id in ids:
        try:
            summaries = cli("onesubscription", "subscription", "subscription", "list", "--compartment-id", tenancy, "--subscription-id", str(subscription_id), "--is-commit-info-required", "true", "--all")
            if not summaries:
                raise RuntimeError("No subscription details returned.")
            cutoff = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
            cost_usage, cost_error = None, None
            try:
                cost_usage = fetch_cost_usage(tenancy, subscription_id, cutoff)
            except (RuntimeError, OSError) as exc:
                cost_error = str(exc)
                print(f"WARNING [{subscription_id}]: Cost Analysis request failed: {exc}", file=sys.stderr)
            usage, usage_error = [], None
            try:
                usage = cli("onesubscription", "computed-usage", "aggregated-computed-usage-summary", "list-aggregated-computed-usages",
                            "--compartment-id", tenancy, "--subscription-id", str(subscription_id),
                            "--time-from", (cutoff - timedelta(days=30)).isoformat(),
                            "--time-to", cutoff.isoformat(), "--grouping", "DAILY", "--all")
            except (RuntimeError, OSError) as exc:
                usage_error = str(exc)
                print(f"WARNING [{subscription_id}]: usage request failed: {exc}", file=sys.stderr)
            render(subscription_id, summaries, as_of, usage, usage_error, cost_usage, cost_error)
            if usage_error or cost_error:
                failed += 1
        except (RuntimeError, OSError) as exc:
            failed += 1
            print(f"\nERROR [{subscription_id}]: {exc}", file=sys.stderr)
    print(f"\nSubscriptions: {len(ids)} | Successful: {len(ids) - failed} | Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
