"""Offline end-to-end checks: the real report invokes a temporary fake OCI CLI.

No OCI connection, credentials, or configuration changes are made.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


REFERENCE = datetime(2026, 10, 23, tzinfo=timezone.utc)


def fixture(balance="1000", rates=("200", "200", "200"), actual_overage="0", missing_day=False):
    """rates are previous-day, preceding six days and preceding 83 days."""
    daily, costs = [], []
    total = 0
    for offset in range(1, 91):
        if missing_day and offset == 1:
            continue
        cost = rates[0] if offset == 1 else rates[1] if offset <= 7 else rates[2]
        start = REFERENCE - timedelta(days=offset)
        costs.append({"subscription-id": "SYNTHETIC-SUBSCRIPTION", "currency": "EUR",
                      "computed-amount": cost, "time-usage-started": start.isoformat(),
                      "time-usage-ended": (start + timedelta(days=1)).isoformat()})
        daily.append({"type": "USAGE", "cost-unrounded": cost, "time-metered-on": start.isoformat()})
        total += int(cost)
    consumed = total + int(actual_overage)
    net = total + int(balance)
    current = {"time-start": "2026-01-01T00:00:00Z", "time-end": "2026-11-02T00:00:00Z",
               "line-net-amount": str(net), "quantity": str(net), "used-amount": str(consumed),
               "available-amount": balance}
    future = {"time-start": "2026-11-02T00:00:00Z", "time-end": "2027-11-02T00:00:00Z",
              "line-net-amount": "7000", "quantity": "7000", "available-amount": "7000"}
    service = {"id": "synthetic-service", "status": "ACTIVE", "pricing-model": "Annual",
               "product": {"part-number": "EXAMPLE", "name": "Synthetic credits"},
               "time-start": current["time-start"], "time-end": future["time-end"],
               "total-value": str(net + 7000), "used-amount": str(consumed),
               "available-amount": str(int(balance) + 7000), "commitment-services": [current, future]}
    if actual_overage != "0":
        daily.append({"type": "OVERAGE", "cost-unrounded": actual_overage,
                      "time-metered-on": "2026-10-22T00:00:00Z"})
    return {"summaries": [{"status": "ACTIVE", "currency": {"iso-code": "EUR"},
                           "subscribed-services": [service]}], "costs": costs,
            "usage": [{"parent-subscribed-service-id": "synthetic-service", "currency-code": "EUR",
                       "aggregated-computed-usages": daily}]}


FAKE_CLI = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["OCI_TEST_FIXTURE"]) as source:
    fixture = json.load(source)
args = sys.argv[1:]
if "tenancy" in args and "get" in args:
    response = {"data": {"name": "Synthetic Test Tenant"}}
elif "region-subscription" in args:
    response = {"data": [{"is-home-region": True, "region-name": "eu-frankfurt-1"}]}
elif "organization-subscription" in args:
    response = {"data": [{"id": "SYNTHETIC-SUBSCRIPTION"}]}
elif "usage-api" in args:
    response = {"data": {"items": fixture["costs"]}}
elif "computed-usage" in args:
    response = {"data": fixture["usage"]}
elif "subscription" in args:
    response = {"data": fixture["summaries"]}
else:
    sys.exit("Unexpected fake OCI command: " + str(args))
print(json.dumps(response))
'''


def run_report(data):
    with tempfile.TemporaryDirectory(prefix="oci-overage-test-") as folder:
        root = Path(folder)
        command = root / "oci"
        command.write_text(FAKE_CLI)
        command.chmod(0o755)
        source = root / "fixture.json"
        source.write_text(json.dumps(data))
        env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get("PATH", ""),
                   OCI_TEST_FIXTURE=str(source), OCI_TENANCY="ocid1.tenancy.oc1..synthetic",
                   NO_COLOR="1")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("oci_balance.py")),
                                 "--as-of", "2026-10-23"], env=env, capture_output=True, text=True)
    return result


def forecast_cells(output):
    start = output.find("Metric (EUR)")
    if start < 0:
        return {}
    cells = {}
    for line in output[start:].splitlines():
        if "|" in line:
            parts = [cell.strip() for cell in line.split("|")]
            cells[parts[0]] = parts[1:]
        if line.startswith("Forecast outcome"):
            break
    return cells


class OverageEndToEndTests(unittest.TestCase):
    def check_run(self, data):
        result = run_report(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("OCI SUBSCRIPTION AND BALANCE REPORT (Synthetic Test Tenant)", result.stdout)
        if forecast_cells(result.stdout):
            self.assertIn("Horizon: Active commitment end - 2026-11-02", result.stdout)
        self.assertIn("Subscriptions: 1 | Successful: 1 | Failed: 0", result.stdout)
        self.assertRegex(result.stdout, r"\*END OF THE REPORT\* \(.+ UTC\)")
        return result.stdout, forecast_cells(result.stdout)

    def test_all_baselines_forecast_overage(self):
        output, cells = self.check_run(fixture())
        expected = {
            "Remaining Credit": "1,000.0", "Future Consumption": "2,000.0",
            "Unused/Overage Credit - Total": "1,000.0",
            "Actual Consumption - Daily": "200.0", "Required Consumption - Daily": "100.0",
            "Unused/Overage Credit - Daily": "100.0", "Actual Consumption - Monthly": "6,200.0",
            "Required Consumption - Monthly": "3,100.0", "Unused/Overage Credit - Monthly": "3,100.0",
            "Days to horizon": "10.0 Days", "Forecast outcome": "Overage estimate"}
        for metric, value in expected.items():
            self.assertEqual(cells[metric], [value] * 4, metric)
        self.assertEqual(cells["Coverage"], ["1/1", "7/7", "30/30", "90/90"])
        self.assertNotIn("Result", cells)
        self.assertNotIn("Forecast outcome:", output)
        self.assertNotIn("2027-11-02 (", output.split("FORECAST (EUR)")[1])

    def test_mixed_baselines_keep_their_own_outcome_and_monthly_values(self):
        _, cells = self.check_run(fixture(rates=("200", "100", "50")))
        self.assertEqual(cells["Future Consumption"], ["2,000.0", "1,142.9", "650.0", "550.0"])
        self.assertEqual(cells["Unused/Overage Credit - Total"], ["1,000.0", "142.9", "350.0", "450.0"])
        self.assertEqual(cells["Unused/Overage Credit - Daily"], ["100.0", "14.3", "35.0", "45.0"])
        self.assertEqual(cells["Unused/Overage Credit - Monthly"], ["3,100.0", "442.9", "1,085.0", "1,395.0"])
        self.assertEqual(cells["Forecast outcome"], ["Overage estimate", "Overage estimate", "Unused estimate", "Unused estimate"])

    def test_all_baselines_forecast_unused_credit(self):
        _, cells = self.check_run(fixture(balance="10000"))
        self.assertEqual(cells["Unused/Overage Credit - Total"], ["8,000.0"] * 4)
        self.assertEqual(cells["Forecast outcome"], ["Unused estimate"] * 4)

    def test_exact_credit_exhaustion_is_balanced(self):
        _, cells = self.check_run(fixture(balance="2000"))
        self.assertEqual(cells["Unused/Overage Credit - Total"], ["0.0"] * 4)
        self.assertEqual(cells["Unused/Overage Credit - Monthly"], ["0.0"] * 4)
        self.assertEqual(cells["Forecast outcome"], ["Balanced estimate"] * 4)

    def test_already_reported_overage_is_not_added_to_future_overage(self):
        output, cells = self.check_run(fixture(balance="0", actual_overage="100"))
        self.assertEqual(cells["Remaining Credit"], ["0.0"] * 4)
        self.assertEqual(cells["Required Consumption - Daily"], ["0.0"] * 4)
        self.assertEqual(cells["Unused/Overage Credit - Total"], ["2,000.0"] * 4)
        self.assertEqual(cells["Unused/Overage Credit - Monthly"], ["6,200.0"] * 4)
        self.assertEqual(cells["Forecast outcome"], ["Overage estimate"] * 4)
        # The reported 100 remains in balances; future overage is 2,000, not 2,100.
        balance_line = next(line for line in output.splitlines() if line.lstrip().startswith("—") and "|" in line)
        self.assertEqual(balance_line.split("|")[-1].strip(), "100.0")
        active_line = next(line for line in output.splitlines() if line.startswith("active"))
        self.assertEqual(active_line.split("|")[1].strip(), "Overage credit")

    def test_zero_consumption_keeps_unused_credit(self):
        _, cells = self.check_run(fixture(rates=("0", "0", "0")))
        self.assertEqual(cells["Actual Consumption - Daily"], ["0.0"] * 4)
        self.assertEqual(cells["Future Consumption"], ["0.0"] * 4)
        self.assertEqual(cells["Unused/Overage Credit - Total"], ["1,000.0"] * 4)
        self.assertEqual(cells["Forecast outcome"], ["Unused estimate"] * 4)

    def test_missing_day_does_not_produce_false_overage(self):
        output, cells = self.check_run(fixture(missing_day=True))
        self.assertFalse(cells)
        self.assertIn("Forecast unavailable (EUR): Missing daily usage records.", output)


if __name__ == "__main__":
    unittest.main()
