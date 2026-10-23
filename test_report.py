"""Offline regression checks using fictional billing data."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

import oci_balance as report


def service(sku, **values):
    return dict({"product": {"name": "Example credits", "part-number": sku}}, **values)


class ReportTests(unittest.TestCase):
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
            status = report.main()
        self.assertEqual(status, 1)
        self.assertIn("SUBSCRIPTION allowed", output.getvalue())
        self.assertIn("Successful: 1 | Failed: 1", output.getvalue())
        self.assertIn("ERROR [denied]", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
