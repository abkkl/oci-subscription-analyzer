"""Offline HTML export, download-path and transcript checks."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import oci_balance as report


class HtmlExportTests(unittest.TestCase):
    def test_real_report_tty_frame_export_and_matching_subscription_rule_width(self):
        from test_overage import fixture
        data = fixture()
        def fake_api(*args):
            if "tenancy" in args:
                return {"data": {"name": "Example Tenant"}}
            if "region-subscription" in args:
                return {"data": [{"is-home-region": True, "region-name": "eu-frankfurt-1"}]}
            if "organization-subscription" in args:
                return {"data": [{"id": "SYNTHETIC-SUBSCRIPTION"}]}
            if "usage-api" in args:
                start = args[args.index("--time-usage-started") + 1]
                end = args[args.index("--time-usage-ended") + 1]
                return {"data": {"items": [row for row in data["costs"]
                    if start <= row["time-usage-started"] < end]}}
            if "computed-usage" in args:
                return {"data": data["usage"]}
            return {"data": data["summaries"]}
        terminal, errors = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"OCI_TENANCY": "example", "TERM": "xterm"}), \
                patch.object(report.Path, "home", return_value=Path(folder)), \
                patch.object(terminal, "isatty", return_value=True), \
                patch.object(report, "cli_payload", side_effect=fake_api), \
                contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(errors):
            with patch.dict(os.environ):
                os.environ.pop("NO_COLOR", None)
                self.assertEqual(report.main(["--as-of", "2026-10-23"]), 0)
            files = list((Path(folder) / "oci-subscription-analyzer-reports").glob("*.html"))
            self.assertEqual(len(files), 1)
            document = files[0].read_text()
        self.assertEqual(errors.getvalue(), "")
        lines = report.SGR.sub("", terminal.getvalue()).strip("\n").splitlines()
        self.assertEqual(len({len(line) for line in lines}), 1)
        content = [line[2:-2].rstrip() for line in lines[1:-1]]
        rule = next(line for line in content if line and set(line) == {"="})
        metric_index = next(i for i, line in enumerate(content) if line.startswith("Metric (EUR)"))
        self.assertEqual(len(rule), len(lines[0]) - 4)
        self.assertLessEqual(len(rule), max(76, len("Download: oci-subscription-analyzer-reports/oci-report-20261023-150000-123456.html")))
        self.assertIn('<section class="report-frame">', document)
        self.assertIn('<span class="overage">Overage estimate</span>', document)
        self.assertNotIn("Loading", document)

    def test_complete_frame_has_equal_width_lines_and_retains_plain_table_content(self):
        source = ("Title\nMetric | Value\n-------+------\nCredit | 100.0\n"
                  + "Long explanation " * 8 + "\n\033[1;31mOverage estimate\033[0m\n")
        framed = report.boxed_report(source)
        plain = report.SGR.sub("", framed).strip("\n").splitlines()
        self.assertTrue(plain[0].startswith("+"))
        self.assertEqual(plain[0], plain[-1])
        self.assertEqual(len({len(line) for line in plain}), 1)
        self.assertTrue(all(line.startswith("| ") and line.endswith(" |") for line in plain[1:-1]))
        self.assertIn("Credit | 100.0", framed)

    def test_tty_main_prints_one_complete_frame_and_no_html_option_still_works(self):
        terminal = io.StringIO()
        def fake_report(*args):
            print("Framed report")
            return 0
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"OCI_TENANCY": "example", "TERM": "xterm"}), \
                patch.object(report.Path, "home", return_value=Path(folder)), \
                patch.object(terminal, "isatty", return_value=True), \
                patch.object(report, "run_terminal_report", side_effect=fake_report), \
                contextlib.redirect_stdout(terminal):
            self.assertEqual(report.main(["--no-html"]), 0)
        text = report.SGR.sub("", terminal.getvalue()).strip("\n").splitlines()
        self.assertEqual(text[0], text[-1])
        self.assertTrue(text[0].startswith("+"))
        self.assertEqual(len({len(line) for line in text}), 1)
        self.assertEqual(terminal.getvalue().count("Framed report"), 1)

    def test_narrow_terminal_wraps_long_path_without_expanding_frame(self):
        path = "oci-subscription-analyzer-reports/oci-report-20261023-150000-123456.html"
        with patch.object(report.shutil, "get_terminal_size", return_value=os.terminal_size((40, 24))):
            framed = report.boxed_report("Done\n" + path + "\n")
        lines = framed.strip("\n").splitlines()
        self.assertTrue(all(len(line) <= 40 for line in lines))
        content = "".join(line[2:-2].rstrip() for line in lines[1:-1])
        self.assertIn(path, content)

    def run_local(self, root, options=(), partial=False):
        def fake_report(args, as_of, tenancy):
            report.heading("OCI SUBSCRIPTION AND BALANCE REPORT (Example Tenant)")
            print("Subscription report: 1,000.0 EUR")
            if partial:
                print("WARNING: synthetic usage error", file=report.sys.stderr)
            return int(partial)
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"OCI_TENANCY": "example-tenancy", "TERM": "xterm"}), \
                patch.object(report.Path, "home", return_value=root), \
                patch.object(report, "run_terminal_report", side_effect=fake_report), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with patch.dict(os.environ):
                os.environ.pop("NO_COLOR", None)
                status = report.main(list(options))
        return status, output.getvalue(), errors.getvalue()

    def test_default_export_and_only_copyable_home_relative_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status, output, errors = self.run_local(root)
            self.assertEqual(status, 0)
            self.assertEqual(errors, "")
            files = list((root / "oci-subscription-analyzer-reports").glob("*.html"))
            self.assertEqual(len(files), 1)
            relative = files[0].relative_to(root).as_posix()
            self.assertIn("\n\nDownload: " + relative + "\n\n*END OF THE REPORT*", output)
            self.assertNotIn(str(root), output)
            self.assertFalse(relative.startswith(("/", "~/")))
            self.assertNotIn("\033", output)
            document = files[0].read_text()
            self.assertIn('class="cyan"', document)
            self.assertIn("Subscription report: 1,000.0 EUR", document)
            self.assertIn(relative, document)
            self.assertIn("*END OF THE REPORT*", document)
            self.assertIn('onclick="window.print()"', document)
            self.assertIn('<meta charset="utf-8">', document)
            self.assertIn('<section class="report-frame">', document)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)

    def test_custom_relative_output_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status, output, _ = self.run_local(root, ["--output-dir", "customer-reports"])
            self.assertEqual(status, 0)
            self.assertEqual(len(list((root / "customer-reports").glob("*.html"))), 1)
            self.assertIn("\nDownload: customer-reports/oci-report-", output)
            self.assertFalse((root / "oci-subscription-analyzer-reports").exists())

    def test_no_html_does_not_create_an_output_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status, output, _ = self.run_local(root, ["--no-html"])
            self.assertEqual(status, 0)
            self.assertEqual(list(root.iterdir()), [])
            self.assertIn("*END OF THE REPORT*", output)
            self.assertNotIn(".html", output)

    def test_export_error_keeps_terminal_report_without_false_download_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blocked = root / "not-a-folder"
            blocked.write_text("keep this file")
            status, output, errors = self.run_local(root, ["--output-dir", str(blocked)])
            self.assertEqual(status, 1)
            self.assertIn("HTML export failed", errors)
            self.assertIn("Subscription report: 1,000.0 EUR", output)
            self.assertIn("*END OF THE REPORT*", output)
            self.assertNotIn(".html", output)
            self.assertEqual(blocked.read_text(), "keep this file")

    def test_partial_report_includes_warning_and_preserves_failure_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status, _, errors = self.run_local(root, partial=True)
            self.assertEqual(status, 1)
            self.assertIn("synthetic usage error", errors)
            file = next((root / "oci-subscription-analyzer-reports").glob("*.html"))
            self.assertIn("synthetic usage error", file.read_text())

    def test_html_escapes_tenant_or_report_text_and_retains_colors(self):
        converted = report.ansi_html('\033[1;31m<script>alert("x")</script> & <img src=x>\033[0m')
        self.assertIn('<span class="overage">', converted)
        self.assertIn("&lt;script&gt;", converted)
        self.assertIn("&amp;", converted)
        self.assertNotIn("<script>", converted)
        self.assertNotIn("<img", converted)
        self.assertNotIn("\033", converted)

    def test_existing_export_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "report.html"
            report.write_html(target, "first")
            original = target.read_text()
            with self.assertRaises(FileExistsError):
                report.write_html(target, "second")
            self.assertEqual(target.read_text(), original)

    def test_spinner_frames_are_not_recorded_in_html_transcript(self):
        terminal = io.StringIO()
        transcript = io.StringIO()
        with patch.object(terminal, "isatty", return_value=True), \
                patch.dict(os.environ, {"TERM": "xterm"}), \
                contextlib.redirect_stdout(report.ReportStream(terminal, transcript)):
            with report.loading("Synthetic stage"):
                pass
        self.assertEqual(transcript.getvalue(), "")
        self.assertIn("\033[2K", terminal.getvalue())


if __name__ == "__main__":
    unittest.main()
