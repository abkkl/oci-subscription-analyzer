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


class ReportTests(unittest.TestCase):
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
        self.assertEqual(report.actual_overage(record, "TRY", groups, now), Decimal("23.50"))
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
        self.assertIn("1 months 0 days", report.contract_countdown(
            "2027-02-28T23:59:59Z", datetime(2027, 1, 31, tzinfo=timezone.utc)))

    def setUp(self):
        patcher = patch.object(report, "fetch_cost_usage", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

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
        self.assertIn("10,000.00", text)
        self.assertIn("8,750.00", text)
        self.assertIn("1,250.00", text)
        self.assertIn("B89010", text)
        self.assertIn("B88206", text)
        self.assertIn("0.00", text)
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
        self.assertIn("4,500.00", text)

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


class ForecastTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(report, "fetch_cost_usage", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertIn("Latest reported completed usage day (UTC): 2026-10-21", output.getvalue())
        self.assertIn("Missing daily usage records", output.getvalue())

    def test_commitment_horizon_does_not_use_contract_end(self):
        service_record = dict(self.record, **{"commitment-services": [
            {"time-start": "2026-10-01T00:00:00Z", "time-end": "2026-11-01T00:00:00Z", "available-amount": "500"}]})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(service_record, "EUR", self.now, [])
        self.assertIn("Forecast horizon: Active commitment end | 2026-11-01 (UTC)", output.getvalue())

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
        self.assertIn("10,000.00", output.getvalue())
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
        self.assertIn("8,900.00", text)
        self.assertIn("30/30", text)
        self.assertIn("Latest reported completed usage day (UTC): 2026-10-22", text)
        self.assertNotIn("Source:", text)
        self.assertNotIn("Scope:", text)
        self.assertNotIn("Assumption:", text)
        self.assertIn("FORECAST\n\nBalance snapshot", text)
        self.assertEqual(text.count("FORECAST\n"), 1)
        self.assertEqual(text.count("Baseline     |"), 1)
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
