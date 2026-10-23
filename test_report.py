"""Offline regression checks using fictional billing data."""
import contextlib
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import oci_balance as report


def service(sku, **values):
    return dict({"product": {"name": "Example credits", "part-number": sku}}, **values)


class LayoutAndMetadataTests(unittest.TestCase):
    def test_tenant_name_is_read_and_metadata_failure_does_not_stop_report(self):
        with patch.object(report, "cli_payload", return_value={"data": {"name": "Example Tenant"}}) as api:
            self.assertEqual(report.tenancy_name("ocid-example", "eu-frankfurt-1"), "Example Tenant")
        self.assertEqual(api.call_args[0], ("iam", "tenancy", "get", "--tenancy-id", "ocid-example", "--region", "eu-frankfurt-1"))
        with patch.object(report, "cli_payload", side_effect=RuntimeError("denied")):
            self.assertEqual(report.tenancy_name("ocid-example"), "Tenant name unavailable")

    def test_commitment_status_and_days_cover_past_active_and_future(self):
        now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        def period(start, end):
            return {"time-start": start, "time-end": end}
        self.assertEqual(report.commitment_state(period("2025-11-04T00:00:00Z", "2026-11-03T23:59:59Z"), now), ("active", 11))
        self.assertEqual(report.commitment_state(period("2024-11-04T00:00:00Z", "2025-11-03T23:59:59Z"), now), ("past", 0))
        self.assertEqual(report.commitment_state(period("2026-11-04T00:00:00Z", "2027-11-03T23:59:59Z"), now), ("future", 365))
        self.assertEqual(report.commitment_state(period("2028-01-01T00:00:00Z", "2028-12-31T23:59:59Z"), now), ("future", 366))
        self.assertEqual(report.commitment_state(period("2026-11-01T00:00:00Z", "2026-11-30T23:59:59Z"), now), ("future", 30))
        self.assertEqual(report.commitment_state({}, now), ("—", "—"))

    def test_contract_countdown_shows_years_months_days(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.assertEqual(report.contract_countdown("2028-11-03T23:59:59Z", now),
                         "2028-11-03 | 2 years 11 days remaining (742 days total)")

    def test_trend_comment_is_one_line_in_requested_format(self):
        # Raw API rates round to 24.1 and 19.7 with a 22.2% increase.
        comment = report.consumption_trend([{"rate": Decimal("19.72")}, {"rate": Decimal("24.10")}], "EUR")
        self.assertEqual(comment, "Comment: Consumption trend: 7-day average 24.1 EUR/day vs 30-day average 19.7 EUR/day -> 22.2% higher; 1.2x the 30-day average.")

    def test_report_audit_and_comment_spacing_and_separator_width(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        fixture = CostAnalysisTests()
        fixture.now = now
        summary = fixture.summaries()
        output = io.StringIO()
        with patch.object(report.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))), contextlib.redirect_stdout(output):
            report.render("example", summary, now, cost_usage=fixture.costs())
        text = output.getvalue()
        self.assertIn("\n" + "=" * 79 + "\nSUBSCRIPTION", text)
        self.assertRegex(text, r"\n\nOverage audit \(UTC\):[^\n]+\n\nCommitment periods")
        self.assertRegex(text, r"Comment: Consumption trend:[^\n]+\n\nEstimate =")

    def test_colored_footer_has_completion_timestamp_and_blank_line(self):
        output = io.StringIO()
        with patch.object(output, "isatty", return_value=True), patch.dict(os.environ, {"TERM": "xterm"}), \
                contextlib.redirect_stdout(output):
            with patch.dict(os.environ):
                os.environ.pop("NO_COLOR", None)
                report.end_report()
        self.assertRegex(output.getvalue(), r"^\n\x1b\[1;36m\*END OF THE REPORT\* \(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC\)\x1b\[0m\n$")


class ReportTests(unittest.TestCase):
    def test_commitment_consumption_distinguishes_reported_and_derived_values(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        commitment = {"time-start": "2026-01-01T00:00:00Z", "time-end": "2026-12-31T23:59:59Z",
                      "line-net-amount": "90000", "available-amount": "34567.89"}
        self.assertEqual(report.commitment_consumed(commitment, now), "55,432.1*")
        self.assertEqual(report.commitment_consumed(dict(commitment, **{"used-amount": "50000"}), now), "50,000.0")
        expired = dict(commitment, **{"time-end": "2026-01-01T00:00:00Z", "available-amount": "0"})
        self.assertEqual(report.commitment_consumed(expired, now), "—")
        future = dict(commitment, **{"time-start": "2026-12-01T00:00:00Z"})
        self.assertEqual(report.commitment_consumed(future, now), "—")
        self.assertEqual(report.commitment_consumed(dict(commitment, **{"line-net-amount": None}), now), "—")
        self.assertEqual(report.commitment_consumed(dict(commitment, **{"available-amount": "1000000"}), now), "—")
        self.assertEqual(report.commitment_consumed(dict(commitment, **{"funded-allocation-value": "500"}), now), "—")

    def test_history_is_summarized_by_default_and_can_be_expanded(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        past = service("PAST", id="past", status="EXPIRED", **{
            "time-start": "2025-01-01T00:00:00Z", "time-end": "2025-12-31T23:59:59Z",
            "used-amount": "500", "available-amount": "0", "commitment-services": [
                {"time-start": "2025-01-01T00:00:00Z", "time-end": "2025-12-31T23:59:59Z", "quantity": "500"}]})
        summary = {"currency": {"iso-code": "TRY"}, "subscribed-services": [past]}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render("example", [summary], now)
        self.assertIn("HISTORY SUMMARY (TRY)", output.getvalue())
        self.assertIn("PAST", output.getvalue())
        self.assertNotIn("Commitment periods", output.getvalue())
        self.assertNotIn("Forecast unavailable", output.getvalue())
        expanded = io.StringIO()
        with contextlib.redirect_stdout(expanded):
            report.render("example", [summary], now, include_history=True)
        self.assertNotIn("HISTORY SUMMARY", expanded.getvalue())
        self.assertIn("Commitment periods: 1", expanded.getvalue())
        self.assertIn("Forecast unavailable", expanded.getvalue())

    def test_overage_audit_exposes_incomplete_historical_date_coverage(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        record = {"id": "old", "time-start": "2025-01-01T00:00:00Z", "time-end": "2025-12-31T23:59:59Z"}
        groups = [{"parent-subscribed-service-id": "old", "currency-code": "TRY",
                   "aggregated-computed-usages": [{"type": "OVERAGE", "cost-unrounded": "4.69",
                                                    "time-metered-on": "2025-12-03T00:00:00Z"}]}]
        audit = report.overage_audit(record, "TRY", groups, now)
        self.assertEqual(audit["amount"], Decimal("4.69"))
        self.assertEqual(audit["expected_days"], 365)
        self.assertEqual(audit["days"], 1)
        self.assertEqual(audit["first"], "2025-12-03")
        self.assertEqual(audit["overage_rows"], 1)
        self.assertIsNone(report.overage_audit(record, "TRY", [], now)["amount"])

    def test_one_decimal_formatting_does_not_change_forecast_precision(self):
        self.assertEqual(report.number("1234.56789"), "1,234.6")
        self.assertEqual(report.number("0"), "0.0")
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        record = {"time-start": "2026-01-01T00:00:00Z", "time-end": "2026-10-24T00:00:00Z", "available-amount": "1.23456"}
        daily = {(now - timedelta(days=i)).date(): Decimal("0.12345") for i in range(1, 31)}
        self.assertEqual(report.forecast_rows(record, daily, now)[0]["unused"], Decimal("1.11111"))

    def test_actual_overage_uses_only_explicit_matching_records(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        record = {"id": "svc", "time-start": "2026-08-01T00:00:00Z"}
        def group(sid, currency, rows):
            return {"parent-subscribed-service-id": sid, "currency-code": currency,
                    "aggregated-computed-usages": rows}
        def row(kind, amount, day="2026-08-02T00:00:00Z"):
            return {"type": kind, "cost-unrounded": amount, "time-metered-on": day}
        groups = [group("svc", "TRY", [row("OVERAGE", "25.50"), row("OVERAGE", "-2"),
                      row("USAGE", "900"), row("OVERAGE", "700", "2026-10-24T00:00:00Z")]),
                  group("other", "TRY", [row("OVERAGE", "400")]),
                  group("svc", "EUR", [row("OVERAGE", "600")])]
        self.assertEqual(report.actual_overage(record, "TRY", groups, now), Decimal("23.5"))
        self.assertIsNone(report.actual_overage(record, "TRY", [], now))
        self.assertEqual(report.actual_overage(record, "TRY", [group("svc", "TRY", [row("USAGE", "10")])], now), 0)
        self.assertIsNone(report.actual_overage(record, "TRY", [group("svc", "TRY", [row(None, "10")])], now))

    def test_subscription_header_and_contract_countdown_are_colored_on_terminal(self):
        output = io.StringIO()
        with patch.object(output, "isatty", return_value=True), \
                patch.dict(os.environ, {"TERM": "xterm"}), \
                contextlib.redirect_stdout(output):
            with patch.dict(os.environ):
                os.environ.pop("NO_COLOR", None)
                report.render("example", [{"time-end": "2027-01-15T23:59:59Z"}])
        self.assertIn("\033[1;36mSUBSCRIPTION example", output.getvalue())
        self.assertIn("\033[1;36mContract end", output.getvalue())

    def test_contract_countdown_uses_calendar_months_and_total_utc_days(self):
        now = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)
        self.assertEqual(report.contract_countdown("2027-01-15T23:59:59Z", now),
                         "2027-01-15 | 2 months 23 days remaining (84 days total)")
        self.assertIn("Ends today", report.contract_countdown("2026-10-23T23:59:59Z", now))
        self.assertIn("Expired", report.contract_countdown("2026-10-22T23:59:59Z", now))
        self.assertEqual(report.contract_countdown(None, now), "Unavailable")
        self.assertIn("1 month remaining", report.contract_countdown(
            "2027-02-28T23:59:59Z", datetime(2027, 1, 31, tzinfo=timezone.utc)))

    def setUp(self):
        patcher = patch.object(report, "fetch_cost_usage", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        tenant = patch.object(report, "tenancy_name", return_value="Example Tenant")
        tenant.start()
        self.addCleanup(tenant.stop)

    def test_poc_credit_is_preserved_alongside_zero_standard_service(self):
        summary = {
            "currency": {"iso-code": "USD"}, "status": "ACTIVE",
            "subscribed-services": [
                service("B89010", **{
                    "original-promo-amount": "10000", "total-value": "0",
                    "used-amount": "1250.001", "available-amount": "8749.999",
                    "funded-allocation-value": "null", "commitment-services": [],
                }),
                service("B88206", **{"used-amount": "0", "available-amount": "0"}),
            ],
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render("example-poc", [summary])
        text = output.getvalue()
        self.assertIn("10,000.0", text)
        self.assertIn("8,750.0", text)
        self.assertIn("1,250.0", text)
        self.assertIn("B89010", text)
        self.assertIn("B88206", text)
        self.assertIn("0.0", text)
        self.assertEqual(report.number("null"), "—")
        self.assertEqual(report.number(None), "—")

    def test_all_production_commitment_periods_are_shown(self):
        summary = {"currency": {"iso-code": "EUR"}, "subscribed-services": [
            service("EXAMPLE", **{"commitment-services": [
                {"time-start": "2026-01-01T00:00:00Z", "time-end": "2026-06-30T23:59:59Z", "quantity": "5000", "available-amount": "0"},
                {"time-start": "2026-07-01T00:00:00Z", "time-end": "2026-12-31T23:59:59Z", "quantity": "5000", "available-amount": "4500"},
            ]}),
        ]}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render("example-prod", [summary])
        text = output.getvalue()
        self.assertIn("Commitment periods: 2", text)
        self.assertIn("2026-01-01", text)
        self.assertIn("2026-07-01", text)
        self.assertIn("4,500.0", text)

    def test_subscription_failure_is_reported_without_stopping_other_subscriptions(self):
        def fake_cli(*args):
            if "region-subscription" in args:
                return [{"region-name": "eu-amsterdam-1", "is-home-region": True}]
            if "organization-subscription" in args:
                return [{"id": "denied"}, {"id": "allowed"}]
            subscription = args[args.index("--subscription-id") + 1]
            if subscription == "denied":
                raise RuntimeError("Example permission error")
            return [{"status": "ACTIVE", "subscribed-services": []}]

        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"OCI_TENANCY": "example-tenancy"}), \
                patch.object(report, "cli", side_effect=fake_cli), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = report.main([])
        self.assertEqual(status, 1)
        self.assertIn("SUBSCRIPTION allowed", output.getvalue())
        self.assertIn("Successful: 1 | Failed: 1", output.getvalue())
        self.assertIn("ERROR [denied]", errors.getvalue())

    def test_explicit_region_skips_discovery_and_history_flag_reaches_renderer(self):
        calls = []
        def fake_cli(*args):
            calls.append(args)
            if "organization-subscription" in args:
                return [{"id": "example"}]
            if "subscription" in args:
                return [{"currency": {"iso-code": "TRY"}, "subscribed-services": []}]
            return []
        with patch.dict(os.environ, {"OCI_TENANCY": "example-tenancy"}), \
                patch.object(report, "home_region") as discover, \
                patch.object(report, "cli", side_effect=fake_cli), \
                patch.object(report, "render") as render, contextlib.redirect_stdout(io.StringIO()):
            result = report.main(["--region", "eu-frankfurt-1", "--include-history"])
        self.assertEqual(result, 0)
        discover.assert_not_called()
        self.assertEqual(report.CLI_REGION, "eu-frankfurt-1")
        self.assertTrue(render.call_args[0][-1])

    def test_history_reminder_appears_once_before_subscription_counts(self):
        for has_history, expanded in [(True, False), (True, True), (False, False)]:
            with self.subTest(has_history=has_history, expanded=expanded):
                def fake_cli(*args):
                    if "organization-subscription" in args:
                        return [{"id": "first"}, {"id": "second"}]
                    if "subscription" in args:
                        return [{"subscribed-services": [{"status": "EXPIRED" if has_history else "ACTIVE"}]}]
                    return []
                output = io.StringIO()
                options = ["--region", "eu-frankfurt-1"] + (["--include-history"] if expanded else [])
                with patch.dict(os.environ, {"OCI_TENANCY": "example-tenancy"}), \
                        patch.object(report, "cli", side_effect=fake_cli), \
                        patch.object(report, "render", side_effect=lambda *args: print("Rendered report")), \
                        contextlib.redirect_stdout(output):
                    self.assertEqual(report.main(options), 0)
                text = output.getvalue()
                message = "History found. Run with --include-history to view details."
                self.assertEqual(text.count(message), int(has_history and not expanded))
                if has_history and not expanded:
                    self.assertIn("Rendered report\n\n" + message + "\nSubscriptions: 2", text)


class ForecastTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(report, "fetch_cost_usage", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        tenant = patch.object(report, "tenancy_name", return_value="Example Tenant")
        tenant.start()
        self.addCleanup(tenant.stop)
        self.now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.record = {"id": "example-service", "time-start": "2026-09-01T00:00:00Z",
                       "time-end": "2026-11-02T00:00:00Z", "available-amount": "10000"}
        self.daily = {}
        for offset in range(1, 31):
            self.daily[(self.now - timedelta(days=offset)).date()] = Decimal(100 if offset == 1 else 20 if offset <= 7 else 10)

    def test_three_independent_forecasts_and_exact_window_dates(self):
        month, week, previous = report.forecast_rows(self.record, self.daily, self.now)
        self.assertEqual(month["rate"], Decimal(15))
        self.assertEqual(month["unused"], Decimal(9850))
        self.assertEqual(week["rate"], Decimal(220) / Decimal(7))
        self.assertEqual(previous["rate"], Decimal(100))
        self.assertEqual(previous["unused"], Decimal(9000))
        self.assertEqual(str(month["first"]), "2026-09-23")
        self.assertEqual(str(previous["last"]), "2026-10-22")

    def test_compact_forecast_column_and_metric_order(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(self.record, "EUR", self.now, [], daily_override=self.daily)
        lines = output.getvalue().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("Metric"))
        stop = next(i for i in range(start, len(lines)) if lines[i].startswith("Result"))
        block = lines[start:stop + 1]
        self.assertEqual([c.strip() for c in block[0].split("|")],
                         ["Metric", "Previous day", "Last 7 days", "Last 30 days"])
        self.assertEqual([line.split("|")[0].strip() for line in block[2:]], [
            "Avg/day Consumption", "Required/day Consumption", "Remaining Credit", "Future Consumption",
            "Unused Credit at End - Total", "Unused Credit at End - Daily", "Overage Credit at End",
            "Days to horizon", "Coverage", "Result"])
        self.assertEqual([c.strip() for c in block[2].split("|")][1:], ["100.0", "31.4", "15.0"])
        self.assertEqual([c.strip() for c in block[-1].split("|")][1:], ["Estimate"] * 3)
        self.assertTrue(all(len(line) <= 80 for line in block))

    def test_missing_previous_day_is_not_zero_consumption(self):
        del self.daily[(self.now - timedelta(days=1)).date()]
        rows = report.forecast_rows(self.record, self.daily, self.now)
        self.assertTrue(all(r["unused"] is None for r in rows))
        self.assertEqual(rows[-1]["coverage"], "0/1")

    def test_explicit_zero_is_valid_and_overrun_is_separate(self):
        yesterday = (self.now - timedelta(days=1)).date()
        self.daily[yesterday] = Decimal(0)
        self.assertEqual(report.forecast_rows(self.record, self.daily, self.now)[-1]["unused"], Decimal(10000))
        self.daily[yesterday] = Decimal(2000)
        row = report.forecast_rows(self.record, self.daily, self.now)[-1]
        self.assertEqual(row["unused"], Decimal(0))
        self.assertEqual(row["beyond"], Decimal(10000))

    def test_service_currency_and_incomplete_day_are_excluded(self):
        def group(service_id, currency, metered, cost):
            return {"parent-subscribed-service-id": service_id, "currency-code": currency,
                    "aggregated-computed-usages": [{"time-metered-on": metered, "cost-unrounded": cost}]}
        groups = [group("example-service", "TRY", "2026-10-22T00:00:00Z", "25"),
                  group("other", "TRY", "2026-10-22T00:00:00Z", "500"),
                  group("example-service", "EUR", "2026-10-22T00:00:00Z", "500"),
                  group("example-service", "TRY", "2026-10-23T00:00:00Z", "500")]
        actual = report.daily_usage(groups, "example-service", "TRY", self.now)
        self.assertEqual(actual, {(self.now - timedelta(days=1)).date(): Decimal(25)})

    def test_report_distinguishes_calendar_day_from_latest_reported_day(self):
        groups = [{"parent-subscribed-service-id": "example-service", "currency-code": "TRY",
                   "aggregated-computed-usages": [{"time-metered-on": "2026-10-21T00:00:00Z", "cost-unrounded": "10"}]}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(self.record, "TRY", self.now, groups)
        self.assertNotIn("Last completed calendar day", output.getvalue())
        self.assertIn("Forecast unavailable (TRY)", output.getvalue())
        self.assertNotIn("Baseline", output.getvalue())
        self.assertIn("Missing daily usage records", output.getvalue())

    def test_commitment_horizon_does_not_use_contract_end(self):
        service_record = dict(self.record, **{"commitment-services": [
            {"time-start": "2026-10-01T00:00:00Z", "time-end": "2026-11-01T00:00:00Z", "available-amount": "500"}]})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(service_record, "EUR", self.now, [], daily_override=self.daily)
        self.assertIn("FORECAST (EUR) | Horizon: Active commitment end - 2026-11-01", output.getvalue())
        self.assertIn("Overage Credit at End", output.getvalue())
        self.assertIn("Days to horizon", output.getvalue())
        forecast_lines = [line for line in output.getvalue().splitlines() if line.startswith("Days to horizon")]
        self.assertEqual(forecast_lines[0].split("|")[-1].strip(), "9.0")

    def test_daily_values_share_the_fractional_commitment_horizon(self):
        record = dict(self.record, **{"time-end": "2028-11-03T23:59:59Z", "commitment-services": [
            {"time-start": "2026-01-01T00:00:00Z", "time-end": "2026-10-24T00:00:00Z", "available-amount": "100"}]})
        now = self.now.replace(hour=12)
        daily = {day: Decimal(10) for day in self.daily}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(record, "TRY", now, [], daily_override=daily)
        lines = output.getvalue().splitlines()
        cells = {line.split("|")[0].strip(): line.split("|")[-1].strip() for line in lines if "|" in line}
        self.assertEqual(cells["Days to horizon"], "0.5")
        self.assertEqual(cells["Required/day Consumption"], "200.0")
        self.assertEqual(cells["Future Consumption"], "5.0")
        self.assertEqual(cells["Unused Credit at End - Total"], "95.0")
        self.assertEqual(cells["Unused Credit at End - Daily"], "190.0")
        self.assertNotIn("Contract days left", output.getvalue())

    def test_trend_comment_handles_increase_decrease_zero_and_missing_data(self):
        def comment(month, week):
            return report.consumption_trend([{"rate": month}, {"rate": week}], "EUR")
        self.assertIn("200.0% higher; 3.0x", comment(Decimal(10), Decimal(30)))
        self.assertIn("50.0% lower", comment(Decimal(20), Decimal(10)))
        self.assertIn("unchanged", comment(Decimal(10), Decimal(10)))
        self.assertIn("no consumption", comment(Decimal(0), Decimal(0)))
        self.assertIn("unavailable", comment(None, Decimal(10)))

    def test_inactive_service_shows_only_unavailable_note(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(dict(self.record, status="EXPIRED"), "AED", self.now, [])
        self.assertEqual(output.getvalue().strip(), "Forecast unavailable (AED): service is not ACTIVE.")

    def test_partial_forecast_keeps_table(self):
        output = io.StringIO()
        yesterday = (self.now - timedelta(days=1)).date()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(self.record, "EUR", self.now, [],
                                          daily_override={yesterday: Decimal(10)})
        self.assertIn("Metric", output.getvalue())
        self.assertIn("Previous day", output.getvalue())
        self.assertIn("Estimate", output.getvalue())
        self.assertNotIn("Forecast unavailable", output.getvalue())

    def test_main_requests_daily_usage_and_keeps_balance_on_usage_failure(self):
        calls = []
        def fake_cli(*args):
            calls.append(args)
            if "region-subscription" in args:
                return [{"region-name": "eu-amsterdam-1", "is-home-region": True}]
            if "organization-subscription" in args:
                return [{"id": "example"}]
            if "list-aggregated-computed-usages" in args:
                raise RuntimeError("Example usage access denied")
            return [{"currency": {"iso-code": "TRY"}, "status": "ACTIVE",
                     "subscribed-services": [dict(self.record, product={"name": "Example", "part-number": "EXAMPLE"})]}]
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"OCI_TENANCY": "example-tenancy"}), \
                patch.object(report, "cli", side_effect=fake_cli), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = report.main(["--as-of", "2026-10-23"])
        usage_call = next(c for c in calls if "list-aggregated-computed-usages" in c)
        self.assertIn("DAILY", usage_call)
        self.assertIn("2026-09-01T00:00:00+00:00", usage_call)
        self.assertIn("2026-10-23T00:00:00+00:00", usage_call)
        self.assertEqual(code, 1)
        self.assertIn("10,000.0", output.getvalue())
        self.assertIn("BALANCES (TRY)", output.getvalue())
        self.assertIn("Remaining", output.getvalue())
        self.assertIn("Usage request failed", output.getvalue())
        self.assertIn("usage request failed", errors.getvalue())

    def test_expired_and_ambiguous_periods_do_not_produce_forecasts(self):
        expired = dict(self.record, **{"time-end": "2026-10-01T00:00:00Z"})
        self.assertTrue(all(r["unused"] is None for r in report.forecast_rows(expired, self.daily, self.now)))
        active_period = {"time-start": "2026-09-01T00:00:00Z", "time-end": "2026-11-01T00:00:00Z", "available-amount": "1000"}
        ambiguous = dict(self.record, **{"commitment-services": [active_period, dict(active_period)]})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(ambiguous, "TRY", self.now, [])
        self.assertIn("no unique active commitment period", output.getvalue())


class CostAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, tzinfo=timezone.utc)

    def costs(self, subscription="example", currency="TRY"):
        return [{"subscription-id": subscription, "currency": currency,
                 "computed-amount": "10", "time-usage-started": (self.now - timedelta(days=i)).isoformat(),
                 "time-usage-ended": (self.now - timedelta(days=i-1)).isoformat()}
                for i in range(1, 31)]

    def summaries(self):
        return [{"currency": {"iso-code": "TRY"}, "status": "ACTIVE", "subscribed-services": [
            service("PROMO", id="credit", **{"status": "ACTIVE", "original-promo-amount": "10000", "available-amount": "9000",
                "time-start": "2026-08-01T00:00:00Z", "time-end": "2026-11-02T00:00:00Z"}),
            service("STANDARD", id="zero", **{"available-amount": "0", "used-amount": "0"}),
        ]}]

    def test_subscription_costs_forecast_single_poc_pool_without_service_usage(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report.render("example", self.summaries(), self.now, cost_usage=self.costs())
        text = out.getvalue()
        self.assertIn("8,900.0", text)
        self.assertIn("30/30", text)
        self.assertIn("Latest reported completed usage day (UTC): 2026-10-22", text)
        self.assertNotIn("Source:", text)
        self.assertNotIn("Scope:", text)
        self.assertNotIn("Assumption:", text)
        self.assertIn("FORECAST (TRY) | Horizon: Service contract end - 2026-11-02\n\nBalance snapshot", text)
        self.assertEqual(text.count("FORECAST (TRY) | Horizon:"), 1)
        self.assertEqual(sum(line.startswith("Metric") for line in text.splitlines()), 1)
        self.assertIn("Last 30 days (UTC): 2026-09-23 - 2026-10-22", text)
        self.assertNotIn("Windows start", text)
        self.assertNotIn("Amounts:", text)
        cells = {line.split("|")[0].strip(): line.split("|")[-1].strip() for line in text.splitlines() if "|" in line}
        self.assertEqual(cells["Future Consumption"], "100.0")
        self.assertEqual(cells["Remaining Credit"], "9,000.0")
        self.assertEqual(cells["Unused Credit at End - Total"], "8,900.0")
        self.assertEqual(cells["Unused Credit at End - Daily"], "890.0")
        self.assertNotIn("SERVICE 2", text)
        self.assertIn("STANDARD — Example credits omitted", text)

    def test_exhausted_credit_is_retained_but_empty_companion_line_is_omitted(self):
        self.assertFalse(report.is_zero_credit_service({
            "original-promo-amount": "1000", "used-amount": "1000", "available-amount": "0"}))
        self.assertTrue(report.is_zero_credit_service({
            "total-value": "0", "used-amount": "0.0", "available-amount": "0.0",
            "commitment-services": [{"quantity": "0", "available-amount": "0"}]}))
        self.assertFalse(report.is_zero_credit_service({"available-amount": "0"}))

    def test_multiple_pools_are_not_assigned_whole_subscription_cost(self):
        summaries = self.summaries()
        summaries[0]["subscribed-services"][1]["available-amount"] = "1000"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report.render("example", summaries, self.now, cost_usage=self.costs())
        self.assertNotIn("Scope: Subscription-level estimate", out.getvalue())
        self.assertIn("multiple credit pools", out.getvalue())

    def test_cost_records_exclude_other_subscription_currency_and_future_values(self):
        rows = self.costs() + self.costs("other") + self.costs(currency="EUR")
        result = report.subscription_daily_usage(rows, "example", "TRY", self.now)
        self.assertEqual(len(result), 30)
        self.assertEqual(sum(result.values()), Decimal(300))

    def test_pagination_is_followed(self):
        with patch.object(report, "cli_payload", side_effect=[
            {"data": {"items": [self.costs()[0]]}, "opc-next-page": "page-2"},
            {"data": {"items": [self.costs()[1]]}},
        ]) as mock_cli:
            result = report.fetch_cost_usage("example-tenancy", "example", self.now)
        self.assertEqual(len(result), 2)
        self.assertIn("--page", mock_cli.call_args_list[1][0])

    def test_home_region_is_discovered_and_explicit_in_command(self):
        with patch.object(report, "cli", return_value=[
            {"region-name": "eu-frankfurt-1", "is-home-region": False},
            {"region-name": "eu-amsterdam-1", "is-home-region": True},
        ]):
            self.assertEqual(report.home_region("example"), "eu-amsterdam-1")
        completed = type("Completed", (), {"returncode": 0, "stdout": '{"data": []}'})()
        with patch.object(report, "CLI_REGION", "eu-amsterdam-1"), \
                patch.object(report.subprocess, "run", return_value=completed) as run:
            report.cli("example")
        self.assertEqual(run.call_args[0][0][:3], ["oci", "--region", "eu-amsterdam-1"])


if __name__ == "__main__":
    unittest.main()
