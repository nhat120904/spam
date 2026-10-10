"""Kiểm thử bản Windows qua CDP thật và biểu mẫu mô phỏng, không gửi phiếu thật."""

import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import test_open_incognito as form_fixture


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "open_incognito_windows.py"


class WindowsChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()

    @classmethod
    def tearDownClass(cls):
        cls.playwright.stop()

    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có script chạy trên Windows.")
        self.helper = importlib.import_module("open_incognito_windows")
        self.directory = tempfile.TemporaryDirectory(prefix="windows-helper-")
        self.addCleanup(self.directory.cleanup)
        self.profile = Path(self.directory.name) / "chrome-profile"
        chrome = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                  if sys.platform == "darwin" else str(self.helper.find_chrome()))
        native_popen = subprocess.Popen

        def launch_headless(command, **kwargs):
            self.assertIn("--headless=new", command)
            process = native_popen(command, **kwargs)
            self.addCleanup(self.stop_owned_process, process)
            return process

        with patch.object(self.helper.subprocess, "Popen", side_effect=launch_headless):
            self.tab = self.helper.ChromeTab.launch(chrome, self.profile, timeout=15, headless=True)
        self.addCleanup(self.stop_chrome)
        self.browser = self.playwright.chromium.connect_over_cdp(self.tab.http_endpoint)
        self.context = self.browser.contexts[0]
        self.page = next(page for page in self.context.pages if page.url == self.helper.START_PAGE)
        self.page.set_default_timeout(2000)
        self.requests = []

    def stop_owned_process(self, process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

    def stop_chrome(self):
        try:
            self.tab.connection.call("Browser.close")
        except (RuntimeError, OSError):
            pass
        self.tab.disconnect()
        self.tab.process.wait(timeout=10)

    def load_form(self, **options):
        form_fixture.PrepareVoteFormTests.load_form(self, **options)

    def run_flow(self, **options):
        native_evaluate = self.tab.evaluate

        def evaluate_with_fixture_dispatch(source):
            result = native_evaluate(source)
            # Playwright chỉ phục vụ route mô phỏng khi vòng sự kiện được chạy.
            self.page.wait_for_timeout(10)
            return result

        with redirect_stdout(io.StringIO()), \
                patch.object(self.tab, "evaluate", side_effect=evaluate_with_fixture_dispatch):
            return self.helper.run_workflow(
                self.tab, timeout=3, captcha_timeout=options.pop("captcha_timeout", 0.1),
                response_timeout=options.pop("response_timeout", 0.8), **options,
            )

    def test_success_selects_eight_ratings_sends_once_and_closes_only_own_tab(self):
        self.load_form()
        self.page.goto(self.helper.START_PAGE)
        self.requests.clear()
        # Điều hướng CDP thật; luồng chính chỉ phục vụ route mô phỏng.
        with ThreadPoolExecutor(max_workers=1) as executor:
            navigation = executor.submit(self.tab.navigate)
            while not navigation.done():
                self.page.wait_for_timeout(10)
            navigation.result()
        other = self.context.new_page()
        self.run_flow()
        if not self.page.is_closed():
            self.page.wait_for_event("close", timeout=2000)
        self.assertTrue(self.page.is_closed())
        self.assertFalse(other.is_closed())
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_select_only_keeps_tab_open_with_eight_five_star_ratings(self):
        self.load_form()
        self.run_flow(select_only=True)
        self.assertEqual(self.page.locator("select.rating").evaluate_all(
            "elements => elements.map(element => element.value)"), ["5"] * 8)
        self.assertEqual(self.page.evaluate("window.submitClicks"), 0)
        self.assertFalse(self.page.is_closed())

    def test_captcha_timeout_closes_own_tab_and_does_not_send(self):
        self.load_form(captcha="")
        other = self.context.new_page()
        with self.assertRaisesRegex(RuntimeError, "CAPTCHA"):
            self.run_flow()
        other.wait_for_timeout(10)
        self.assertTrue(self.page.is_closed())
        self.assertFalse(other.is_closed())
        self.assertEqual([method for method, _ in self.requests], ["GET"])

    def test_failure_and_unknown_response_close_tab_without_retry(self):
        other = self.context.new_page()
        for options in ({"response": "0"}, {"status": 500}):
            with self.subTest(options=options):
                self.load_form(**options)
                with self.assertRaises(RuntimeError):
                    self.run_flow()
                self.assertNotIn(self.tab.target_id, {
                    target["targetId"] for target in self.tab.connection.call("Target.getTargets")["targetInfos"]
                })
                if not self.page.is_closed():
                    self.page.wait_for_event("close", timeout=2000)
                self.assertTrue(self.page.is_closed())
                self.assertFalse(other.is_closed())
                self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])
                self.requests.clear()
                self.page = self.context.new_page()
                target = self.context.new_cdp_session(self.page).send("Target.getTargetInfo")["targetInfo"]
                self.tab.target_id = target["targetId"]
                self.tab.session_id = self.tab.connection.call("Target.attachToTarget", {
                    "targetId": self.tab.target_id, "flatten": True,
                })["sessionId"]

    def test_does_not_start_another_browser_when_helper_profile_is_open(self):
        with self.assertRaisesRegex(RuntimeError, "vẫn mở"):
            self.helper.ChromeTab.launch("must-not-launch", self.profile, timeout=1)

    def check_headless_main_cleanup(self, error=None):
        # Giữ Chrome/CDP thật, thay workflow để không truy cập website bình chọn.
        with patch.dict(os.environ, {"LOCALAPPDATA": self.directory.name}), \
                patch.object(self.helper.ChromeTab, "launch", return_value=self.tab) as launch, \
                patch.object(self.helper, "run_workflow", side_effect=error) as workflow, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(self.helper.main(["--headless"]), 1 if error else 0)
        self.assertTrue(launch.call_args.kwargs["headless"])
        self.assertEqual(launch.call_args.args[1].name, "ChromeProfileHeadless")
        self.assertTrue(workflow.call_args.kwargs["headless"])
        self.assertIsNotNone(self.tab.process.poll())

    def test_headless_main_closes_browser_after_success(self):
        self.check_headless_main_cleanup()

    def test_headless_main_closes_browser_after_failure(self):
        self.check_headless_main_cleanup(RuntimeError("fixture CAPTCHA timeout"))

    def test_error_after_navigation_closes_same_tab_and_keeps_other_tabs(self):
        self.load_form()
        other = self.context.new_page()
        self.page.evaluate("history.replaceState(null, '', '/other-page')")
        with self.assertRaises(RuntimeError):
            self.run_flow()
        other.wait_for_timeout(10)
        self.assertTrue(self.page.is_closed())
        self.assertFalse(other.is_closed())

    def test_navigation_failure_closes_tab_before_form_opens(self):
        other = self.context.new_page()
        with patch.object(self.tab, "navigate", side_effect=RuntimeError("fixture navigation error")):
            with self.assertRaisesRegex(RuntimeError, "fixture navigation error"):
                self.run_flow(navigate=True)
        other.wait_for_timeout(10)
        self.assertTrue(self.page.is_closed())
        self.assertFalse(other.is_closed())


class WindowsCommandTests(unittest.TestCase):
    def test_headless_dry_run_explains_captcha_and_cleanup(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--headless", "--dry-run"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--headless=new", result.stdout)
        self.assertIn("chưa gửi", result.stdout)
        self.assertIn("đóng Chrome riêng", result.stdout)

    def test_headless_rejects_manual_modes(self):
        for mode in ("--open-only", "--select-only"):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, str(SCRIPT), "--headless", mode, "--dry-run"],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)

    def test_dry_run_runs_without_windows_or_opening_chrome(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có script chạy trên Windows.")
        result = subprocess.run([sys.executable, str(SCRIPT), "--dry-run"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CAPTCHA", result.stdout)
        self.assertIn("10 giây", result.stdout)

    def test_invalid_timeouts_are_rejected(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có script chạy trên Windows.")
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--dry-run", "--timeout", value],
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 2, result.stdout)

    def test_finds_chrome_in_windows_install_location_with_spaces(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có script chạy trên Windows.")
        helper = importlib.import_module("open_incognito_windows")
        with tempfile.TemporaryDirectory(prefix="Program Files ") as directory:
            chrome = Path(directory) / "Google" / "Chrome" / "Application" / "chrome.exe"
            chrome.parent.mkdir(parents=True)
            chrome.touch()
            with patch.dict(os.environ, {"PROGRAMFILES": directory}, clear=True):
                self.assertEqual(helper.find_chrome(), chrome)


if __name__ == "__main__":
    unittest.main()
