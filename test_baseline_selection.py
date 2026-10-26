"""Offline checks for delayed and maximum-cost baseline selection."""
import contextlib
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import oci_balance as report


class BaselineSelectionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, 15, tzinfo=timezone.utc)
        self.today = self.now.date()
        self.record = {"id": "svc", "status": "ACTIVE", "time-start": "2026-01-01T00:00:00Z",
                       "time-end": "2026-11-26T00:00:00Z", "available-amount": "1000"}
        self.daily = {self.today - timedelta(days=i): Decimal(10 + i) for i in range(100)}
        patcher = patch.object(report, "USAGE_DELAY_HOURS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_maximum_is_limited_to_five_days_and_shared_by_all_windows(self):
        self.daily[self.today - timedelta(days=5)] = Decimal(999)
        rows = report.forecast_rows(self.record, self.daily, self.now)
        selected = self.today - timedelta(days=4)
        self.assertTrue(all(row["last"] == selected for row in rows))
        self.assertEqual(rows[-1]["rate"], Decimal(14))
        for row, days in zip(rows, (90, 30, 7, 1)):
            self.assertEqual((row["last"] - row["first"]).days + 1, days)

    def test_equal_amounts_choose_today_and_include_partial_today(self):
        daily = {self.today - timedelta(days=i): Decimal(10) for i in range(5)}
        rows = report.forecast_rows(self.record, daily, self.now)
        self.assertEqual(rows[-1]["last"], self.today)
        self.assertEqual(rows[-1]["coverage"], "1/1")

    def test_missing_today_does_not_become_zero(self):
        day = self.today - timedelta(days=3)
        rows = report.forecast_rows(self.record, {day: Decimal(0)}, self.now)
        self.assertEqual(rows[-1]["last"], day)
        self.assertEqual(rows[-1]["rate"], Decimal(0))
        self.assertIsNone(rows[-1]["reason"])

    def test_no_recent_records_does_not_fallback_to_old_usage(self):
        rows = report.forecast_rows(self.record, {self.today - timedelta(days=6): Decimal(10)}, self.now)
        self.assertTrue(all(row["reason"] for row in rows))
        self.assertIsNone(rows[-1]["selected"])

    def test_delay_uses_end_of_day_elapsed_hours_not_maximum(self):
        for hours, days_ago in [(1, 1), (15, 1), (16, 2), (48, 3), (72, 4), (240, 11)]:
            with self.subTest(hours=hours), patch.object(report, "USAGE_DELAY_HOURS", hours):
                rows = report.forecast_rows(self.record, self.daily, self.now)
                expected = self.today - timedelta(days=days_ago)
                self.assertTrue(all(row["last"] == expected for row in rows))
                self.assertEqual(rows[-1]["rate"], self.daily[expected])

    def test_missing_delayed_day_is_unavailable_without_switching_dates(self):
        with patch.object(report, "USAGE_DELAY_HOURS", 48):
            day = self.today - timedelta(days=3)
            del self.daily[day]
            rows = report.forecast_rows(self.record, self.daily, self.now)
        self.assertEqual(rows[-1]["last"], day)
        self.assertIsNone(rows[-1]["rate"])
        self.assertEqual(rows[-1]["coverage"], "0/1")
        self.assertIsNone(rows[0]["reason"])

    def test_delay_selection_crosses_year_and_leap_day(self):
        for now, expected in [(datetime(2027, 1, 1, tzinfo=timezone.utc), "2026-12-29"),
                              (datetime(2028, 3, 2, tzinfo=timezone.utc), "2028-02-28")]:
            with patch.object(report, "USAGE_DELAY_HOURS", 48):
                self.assertEqual(str(report.baseline_selection({}, now)[0]), expected)

    def test_today_is_ingested_from_both_usage_sources(self):
        next_midnight = self.now.replace(hour=0) + timedelta(days=1)
        costs = [{"subscription-id": "sub", "currency": "TRY", "computed-amount": "12",
                  "time-usage-started": "2026-10-26T00:00:00Z", "time-usage-ended": "2026-10-27T00:00:00Z"}]
        self.assertEqual(report.subscription_daily_usage(costs, "sub", "TRY", next_midnight)[self.today], 12)
        groups = [{"parent-subscribed-service-id": "svc", "currency-code": "TRY",
                   "aggregated-computed-usages": [{"time-metered-on": "2026-10-26T00:00:00Z", "cost-unrounded": "12"}]}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.render_recent_forecast(self.record, "TRY", self.now, groups)
        self.assertIn("2026-10-26 |                 12.0 | Selected", output.getvalue())
        self.assertIn("Latest reported completed usage day (UTC): No matching usage returned", output.getvalue())

    def test_delay_expands_query_to_cover_ninety_day_window(self):
        with patch.object(report, "USAGE_DELAY_HOURS", 240), patch.object(report, "cli_payload", return_value={"data": {"items": []}}) as api:
            report.fetch_cost_usage("tenant", "sub", self.now.replace(hour=0) + timedelta(days=1))
        args = api.call_args_list[0][0]
        first = report.timestamp(args[args.index("--time-usage-started") + 1])
        selected = self.today - timedelta(days=11)
        self.assertLessEqual(first.date(), selected - timedelta(days=89))

    def test_selection_reason_and_five_rows_even_when_forecast_unavailable(self):
        for hours in [0, 240]:
            output = io.StringIO()
            with patch.object(report, "USAGE_DELAY_HOURS", hours), contextlib.redirect_stdout(output):
                report.render_recent_forecast(dict(self.record, status="EXPIRED"), "EUR", self.now, [], daily_override=self.daily)
            text = output.getvalue()
            self.assertIn(f"Selection: --usage-delay-hours {hours}:", text)
            self.assertEqual(sum(line.startswith("2026-") for line in text.splitlines()), 5)
            self.assertIn("Forecast unavailable", text)
            self.assertNotIn("Metric (EUR)", text)
            if hours:
                self.assertIn("outside the displayed 5-day window", text)

    def test_negative_delay_rejected_before_api_calls(self):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(report, "cli_payload") as api:
            with self.assertRaises(SystemExit):
                report.main(["--usage-delay-hours", "-1"])
            api.assert_not_called()

    def test_service_start_limits_selection(self):
        selected, _, _ = report.baseline_selection(self.daily, self.now, self.now)
        self.assertEqual(selected, self.today)

    def test_cli_delay_applies_to_html_and_terminal(self):
        from test_overage import fixture, run_report, forecast_cells
        result = run_report(fixture(rates=("200", "100", "50")), ["--usage-delay-hours", "48"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("All baseline windows end on: 2026-10-20 (UTC)", result.stdout)
        self.assertIn("Selected day (UTC): 2026-10-20 - 2026-10-20", result.html_report)
        self.assertEqual(forecast_cells(result.stdout)["Forecasted Consumption - Daily"][0], "100.0")

    def test_cli_today_can_win_and_is_labeled_partial(self):
        from test_overage import fixture, run_report, forecast_cells
        data = fixture()
        data["costs"].append({"subscription-id": "SYNTHETIC-SUBSCRIPTION", "currency": "EUR",
            "computed-amount": "500", "time-usage-started": "2026-10-23T00:00:00Z",
            "time-usage-ended": "2026-10-24T00:00:00Z"})
        result = run_report(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("All baseline windows end on: 2026-10-23 (UTC)", result.stdout)
        self.assertEqual(forecast_cells(result.stdout)["Forecasted Consumption - Daily"][0], "500.0")
        self.assertIn("Today's amount is partial", result.stdout)


    def test_daily_api_query_boundaries_remain_midnight_for_non_daily_delay(self):
        for hours in (1, 25, 73):
            with patch.object(report, "USAGE_DELAY_HOURS", hours), patch.object(report, "cli_payload", return_value={"data": {"items": []}}) as api:
                report.fetch_cost_usage("tenant", "sub", self.now.replace(hour=0) + timedelta(days=1))
            args = api.call_args[0]
            start = report.timestamp(args[args.index("--time-usage-started") + 1])
            self.assertEqual((start.hour, start.minute, start.second), (0, 0, 0))

    def test_subscription_rules_fill_the_frame_without_exceeding_terminal(self):
        for columns in (40, 80, 120):
            with patch.object(report.shutil, "get_terminal_size", return_value=os.terminal_size((columns, 24))):
                framed = report.boxed_report("=" * 200 + "\nMetric | Value\n-------+------\nDownload: " + "a" * 100 + ".html\n")
            lines = framed.strip("\n").splitlines()
            self.assertTrue(all(len(line) <= columns for line in lines))
            self.assertEqual(lines[1][2:-2], "=" * (len(lines[0]) - 4))

    def test_cost_query_chunks_cover_full_range_once_and_respect_daily_limit(self):
        for delay in (0, 1, 48, 2400):
            calls = []
            def api(*args):
                first = report.timestamp(args[args.index("--time-usage-started") + 1])
                last = report.timestamp(args[args.index("--time-usage-ended") + 1])
                self.assertLessEqual(last - first, timedelta(days=93))
                self.assertEqual(first.hour, 0)
                self.assertEqual(last.hour, 0)
                calls.append((first, last))
                return {"data": {"items": [{"date": (first + timedelta(days=i)).date().isoformat()}
                    for i in range((last-first).days)]}}
            cutoff = self.now.replace(hour=0) + timedelta(days=1)
            with patch.object(report, "USAGE_DELAY_HOURS", delay), patch.object(report, "cli_payload", side_effect=api):
                rows = report.fetch_cost_usage("tenant", "sub", cutoff)
            expected = 95 + report.math.ceil(delay / 24)
            self.assertEqual(len(rows), expected)
            self.assertEqual(len({row["date"] for row in rows}), expected)
            self.assertEqual(calls[0][0], cutoff - timedelta(days=expected))
            self.assertEqual(calls[-1][1], cutoff)
            self.assertTrue(all(previous[1] == following[0] for previous, following in zip(calls, calls[1:])))

    def test_each_chunk_has_independent_pagination_tokens(self):
        replies = [
            {"data": {"items": [1]}, "opc-next-page": "next"},
            {"data": {"items": [2]}},
            {"data": {"items": [3]}, "opc-next-page": "next"},
            {"data": {"items": [4]}}]
        with patch.object(report, "cli_payload", side_effect=replies) as api:
            rows = report.fetch_cost_usage("tenant", "sub", self.now.replace(hour=0))
        self.assertEqual(rows, [1, 2, 3, 4])
        for index in (0, 2):
            self.assertNotIn("--page", api.call_args_list[index][0])
            self.assertIn("--page", api.call_args_list[index + 1][0])

    def test_repeated_pagination_token_is_rejected_within_chunk(self):
        reply = {"data": {"items": []}, "opc-next-page": "repeat"}
        with patch.object(report, "cli_payload", return_value=reply):
            with self.assertRaisesRegex(RuntimeError, "repeated a pagination token"):
                report.fetch_cost_usage("tenant", "sub", self.now.replace(hour=0))

    def test_later_chunk_failure_is_not_returned_as_successful_partial_data(self):
        with patch.object(report, "cli_payload", side_effect=[{"data": {"items": [1]}}, RuntimeError("denied")]):
            with self.assertRaisesRegex(RuntimeError, "denied"):
                report.fetch_cost_usage("tenant", "sub", self.now.replace(hour=0))
