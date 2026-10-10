"""Bản Windows song song: kiểm tra CDP thật trên trang mô phỏng, không gửi phiếu thật."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
import test_open_incognito as form_fixture


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "open_incognito_windows_parallel.py"


class CommandTests(unittest.TestCase):
    def test_dry_run_shows_distinct_profiles_without_creating_them(self):
        with tempfile.TemporaryDirectory(prefix="windows parallel ") as directory:
            profiles = Path(directory) / "profiles"
            result = subprocess.run([sys.executable, str(SCRIPT), "--workers", "3",
                                     "--profiles-dir", str(profiles), "--dry-run"],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            for number in (1, 2, 3):
                self.assertIn(f"worker-{number}", result.stdout)
            self.assertFalse(profiles.exists())

    def test_rejects_invalid_counts_and_nonfinite_timeouts(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có bản Windows song song.")
        for flag, values in (("--workers", ("0", "-1")),
                             ("--timeout", ("0", "-1", "nan", "inf")),
                             ("--cdp-timeout", ("0", "-1", "nan", "inf")),
                             ("--captcha-timeout", ("0", "nan")),
                             ("--response-timeout", ("0", "inf"))):
            for value in values:
                with self.subTest(flag=flag, value=value):
                    result = subprocess.run([sys.executable, str(SCRIPT), flag, value, "--dry-run"],
                                            capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(flag, result.stderr)


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có bản Windows song song.")
        self.helper = importlib.import_module("open_incognito_windows_parallel")

    def test_profile_lease_excludes_another_process_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "worker-1"
            child = ("import pathlib,sys; from open_incognito_windows_parallel import ProfileLease; "
                     "\nwith ProfileLease(pathlib.Path(sys.argv[1])): print('acquired')")
            with self.helper.ProfileLease(profile):
                result = subprocess.run([sys.executable, "-X", "utf8", "-c", child, str(profile)],
                                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("acquired", result.stdout)
            result = subprocess.run([sys.executable, "-X", "utf8", "-c", child, str(profile)],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("acquired", result.stdout)

    def test_eight_workers_wait_concurrently_after_two_at_a_time_startup(self):
        starting = threading.Barrier(2, timeout=3)
        waiting = threading.Barrier(8, timeout=8)
        profiles = set()
        guard = threading.Lock()
        active, maximum = 0, 0
        # Chỉ thay biên Chrome; luồng thực, phân bổ hồ sơ và điều phối giữ nguyên.
        class Browser:
            def __init__(browser, profile, chrome, stop):
                browser.profile = profile
                browser.pid = 1
                browser.stop = stop
            def start(browser):
                nonlocal active, maximum
                with guard:
                    profiles.add(browser.profile)
                    active += 1
                    maximum = max(maximum, active)
                starting.wait()
                with guard:
                    active -= 1
            def navigate(browser, timeout):
                pass
            def close(browser, keep_open=False):
                pass
        def poll(browser, name, desired, *unused):
            if name == "submit-form.js":
                waiting.wait()
            return {"state": desired, "message": "fixture"}
        args = self.helper.parse_args(["--workers", "8"])
        with patch.object(self.helper, "ChromeSession", Browser), \
                patch.object(self.helper, "wait_state", side_effect=poll), redirect_stdout(io.StringIO()):
            self.assertEqual(self.helper.run_parallel(args), 0)
        self.assertEqual(maximum, 2)
        self.assertEqual({profile.name for profile in profiles}, {f"worker-{n}" for n in range(1, 9)})

    def test_six_success_two_captcha_failures_leave_no_browser_even_after_cleanup_error(self):
        sessions = []
        class Browser:
            def __init__(browser, profile, chrome, stop):
                browser.profile, browser.pid = profile, len(sessions) + 1
                browser.alive, browser.close_attempts = False, 0
                sessions.append(browser)
            def start(browser):
                browser.alive = True
            def navigate(browser, timeout):
                pass
            def close(browser, keep_open=False):
                browser.close_attempts += 1
                if browser.profile.name == "worker-4" and browser.close_attempts == 1:
                    raise RuntimeError("Lỗi dọn dẹp tạm thời.")
                if not keep_open:
                    browser.alive = False
        def poll(browser, name, desired, *unused):
            if name == "read-vote-result.js" and browser.profile.name in ("worker-4", "worker-7"):
                raise self.helper.CaptchaRejectedError("Trang từ chối CAPTCHA.")
            return {"state": desired, "message": "fixture"}
        args = self.helper.parse_args(["--workers", "8"])
        output = io.StringIO()
        with patch.object(self.helper, "ChromeSession", Browser), \
                patch.object(self.helper, "wait_state", side_effect=poll), redirect_stdout(output):
            self.assertEqual(self.helper.run_parallel(args), 1)
        self.assertIn("Kết quả: 6/8 worker hoàn tất.", output.getvalue())
        self.assertEqual(len(sessions), 8)
        self.assertFalse(any(browser.alive for browser in sessions))

    def test_cancelled_worker_does_not_wait_for_a_startup_slot(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(self.helper.Cancelled):
            with self.helper.startup_slot(threading.BoundedSemaphore(0), stop):
                self.fail("Không được khởi động khi đã hủy.")

    def test_cancellation_prevents_chrome_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            stop.set()
            session = self.helper.ChromeSession(Path(directory) / "worker-1", "missing-chrome", stop)
            with self.assertRaises(self.helper.Cancelled):
                session.start()
            self.assertIsNone(session.process)
            self.assertFalse(session.profile.exists())

    def test_windows_forced_cleanup_targets_only_the_owned_process_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.helper.ChromeSession(directory, "chrome.exe", threading.Event())
            class Process:
                pid = 12345
                closed = False
                def poll(process):
                    return 0 if process.closed else None
                def wait(process, timeout):
                    if not process.closed:
                        raise subprocess.TimeoutExpired("chrome.exe", timeout)
                    return 0
                def terminate(process):
                    process.closed = True
                def kill(process):
                    process.closed = True
            session.process = Process()
            commands = []
            def run_command(command, **kwargs):
                commands.append(command)
                session.process.closed = True
                return subprocess.CompletedProcess(command, 0)
            with patch.object(self.helper.os, "name", "nt"), \
                    patch.object(self.helper.subprocess, "run", side_effect=run_command):
                session.close()
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][1:], ["/PID", "12345", "/T", "/F"])
            self.assertIsNotNone(session.process.poll())

    def test_taskkill_error_waits_for_parent_exit_before_reporting_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.helper.ChromeSession(directory, "chrome.exe", threading.Event())
            class Process:
                pid = 12345
                closed = False
                waits = 0
                def poll(process):
                    return 0 if process.closed else None
                def wait(process, timeout):
                    process.waits += 1
                    if process.waits == 1:
                        raise subprocess.TimeoutExpired("chrome.exe", timeout)
                    process.closed = True
                    return 0
            session.process = Process()
            with patch.object(self.helper.os, "name", "nt"), \
                    patch.object(self.helper.subprocess, "run", return_value=
                                 subprocess.CompletedProcess("taskkill", 1)):
                session.close()
            self.assertEqual(session.process.waits, 2)
            self.assertIsNotNone(session.process.poll())


class CdpDiagnosticTests(unittest.TestCase):
    def test_interleaved_events_keep_only_turnstile_code_for_correct_session(self):
        from open_incognito_windows import CdpConnection
        connection = CdpConnection.__new__(CdpConnection)
        connection.next_id = 0
        connection.command_timeout = 20
        connection.turnstile_errors = {}
        connection.socket_error = OSError
        connection.socket_timeout = TimeoutError
        replies = iter([
            {"method": "Runtime.consoleAPICalled", "sessionId": "other", "params": {
                "args": [{"value": "[Cloudflare Turnstile] Error: 200500."}]}},
            {"method": "Runtime.consoleAPICalled", "sessionId": "owned", "params": {
                "args": [{"value": "private-token"},
                         {"value": "[Cloudflare Turnstile] Error: 600010."}]}},
            {"method": "Runtime.consoleAPICalled", "sessionId": "owned", "params": {
                "args": [{"value": "Unrelated Error: 123456"}]}},
            {"id": 1, "result": {"result": {"value": "waiting"}}},
        ])
        class Socket:
            def send(self, value):
                pass
            def settimeout(self, value):
                pass
            def recv(self):
                return json.dumps(next(replies))
        connection.socket = Socket()
        self.assertEqual(connection.call("Runtime.evaluate")["result"]["value"], "waiting")
        self.assertEqual(connection.turnstile_error("owned"), "600010")
        self.assertEqual(connection.turnstile_error("other"), "200500")
        self.assertIsNone(connection.turnstile_error("unknown"))
        self.assertNotIn("private-token", json.dumps(connection.turnstile_errors))

    def test_slow_cdp_response_uses_configured_timeout_without_resending(self):
        from open_incognito_windows import CdpConnection, CdpTimeout
        connection = CdpConnection.__new__(CdpConnection)
        connection.next_id = 0
        connection.command_timeout = 20
        connection.socket_error = OSError
        connection.socket_timeout = TimeoutError
        class Socket:
            sent = []
            def send(self, value):
                self.sent.append(json.loads(value))
            def settimeout(self, value):
                self.timeout = value
            def recv(self):
                # Phản hồi sau 6 giây: timeout 5 giây cũ sẽ không chờ được.
                if self.timeout < 6:
                    raise TimeoutError()
                return json.dumps({"id": 1, "result": {"value": 42}})
        connection.socket = Socket()
        with patch("open_incognito_windows.time.monotonic", side_effect=[0, 0, 6]):
            self.assertEqual(connection.call("Runtime.evaluate")["value"], 42)
        self.assertEqual(len(connection.socket.sent), 1)
        connection.command_timeout = 3
        with self.assertRaisesRegex(CdpTimeout, "Runtime.evaluate.*3"):
            connection.call("Runtime.evaluate")
        self.assertEqual(len(connection.socket.sent), 2, "Không tự gửi lại lệnh bị timeout.")


@unittest.skipUnless(os.environ.get("RUN_NATIVE_CHROME_TESTS") == "1", "Bật RUN_NATIVE_CHROME_TESTS=1")
class NativeChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()

    @classmethod
    def tearDownClass(cls):
        cls.playwright.stop()

    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Chưa có bản Windows song song.")
        self.helper = importlib.import_module("open_incognito_windows_parallel")
        self.directory = tempfile.TemporaryDirectory(prefix="windows parallel chrome ")
        self.addCleanup(self.directory.cleanup)
        self.stop = threading.Event()
        self.sessions = []
        self.chrome = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                       if sys.platform == "darwin" else str(self.helper.find_chrome()))
        self.popen = subprocess.Popen
        self.addCleanup(self.close_sessions)

    def close_sessions(self):
        for session in self.sessions:
            session.close()

    def new_session(self, number):
        session = self.helper.ChromeSession(Path(self.directory.name) / f"worker-{number}",
                                            self.chrome, self.stop)
        self.sessions.append(session)
        return session

    def start_headless(self, sessions):
        with patch.object(self.helper.subprocess, "Popen", side_effect=self.launch_headless):
            with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
                list(executor.map(lambda session: session.start(timeout=15), sessions))

    def launch_headless(self, command, **kwargs):
        # subprocess.run(taskkill) cũng gọi Popen trên Windows. Chỉ thêm cờ cho
        # Chrome, tránh làm hỏng lệnh dọn dẹp bằng tham số --headless=new.
        if Path(command[0]) == Path(self.chrome):
            command = [*command, "--headless=new"]
        return self.popen(command, **kwargs)

    def connect_form(self, session, **options):
        browser = self.playwright.chromium.connect_over_cdp(session.tab.http_endpoint)
        self.page = next(page for context in browser.contexts for page in context.pages
                         if page.url == session.start_page)
        self.page.set_default_timeout(2000)
        self.requests = []
        form_fixture.PrepareVoteFormTests.load_form(self, **options)
        return self.page

    def poll(self, session, name, desired, timeout=2):
        native_evaluate = session.tab.evaluate
        def dispatch(source):
            result = native_evaluate(source)
            self.page.wait_for_timeout(10)
            return result
        with patch.object(session.tab, "evaluate", side_effect=dispatch):
            return self.helper.wait_state(session, name, desired, timeout, self.stop, lambda _: None)

    def test_two_parallel_chromes_isolate_cookies_storage_and_closing(self):
        one, two = self.new_session(1), self.new_session(2)
        self.start_headless([one, two])
        self.assertNotEqual(one.pid, two.pid)
        self.assertNotEqual(one.tab.http_endpoint, two.tab.http_endpoint)
        for session in (one, two):
            self.connect_form(session)
        one.tab.evaluate("document.cookie='worker=one';localStorage.setItem('worker','one')")
        self.assertEqual(two.tab.evaluate("document.cookie"), "")
        self.assertIsNone(two.tab.evaluate("localStorage.getItem('worker')"))
        one.close()
        self.assertIsNotNone(one.process.poll())
        self.assertEqual(two.tab.evaluate("2+2"), 4)
        self.assertIsNone(two.process.poll())

    def test_two_visible_workers_use_distinct_ports_and_normal_browser_mode(self):
        one, two = self.new_session(1), self.new_session(2)
        # Không dùng headless: cờ headless tự bật webdriver, che mất lỗi cần bắt.
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda session: session.start(timeout=15), (one, two)))
        self.assertNotEqual(one.tab.http_endpoint, two.tab.http_endpoint)
        for session in (one, two):
            self.assertFalse(session.tab.evaluate("navigator.webdriver"))
            self.assertTrue(self.helper.endpoint_is_alive(session.profile))

    def test_port_collision_never_closes_another_workers_browser(self):
        one, two = self.new_session(1), self.new_session(2)
        self.start_headless([one])
        port = int(one.tab.http_endpoint.rsplit(":", 1)[1])
        with patch.object(self.helper, "choose_debugging_port", return_value=port):
            with self.assertRaises(RuntimeError):
                self.start_headless_with_timeout(two, 1)
        self.assertIsNotNone(two.process.poll())
        self.assertIsNone(two.connection)
        self.assertIsNone(one.process.poll())
        self.assertEqual(one.tab.evaluate("2+2"), 4)

    def test_eight_visible_workers_keep_their_cdp_sessions_under_parallel_load(self):
        sessions = []
        base = self.helper.ChromeSession
        waiting = threading.Barrier(8, timeout=45)
        class Session(base):
            def __init__(session, *args):
                super().__init__(*args)
                sessions.append(session)
            def navigate(session, timeout):
                self.assertEqual(session.tab.evaluate("2+2"), 4)
        def poll(session, name, desired, *unused):
            if name == "submit-form.js":
                waiting.wait()
                self.assertFalse(session.tab.evaluate("navigator.webdriver"))
                for _ in range(8):
                    self.assertEqual(session.tab.evaluate("2+2"), 4)
            return {"state": desired, "message": "Biểu mẫu mô phỏng; không gửi bình chọn."}
        args = self.helper.parse_args(["--workers", "8", "--profiles-dir", self.directory.name])
        args.chrome = self.chrome
        with patch.object(self.helper, "ChromeSession", Session), \
                patch.object(self.helper, "wait_state", side_effect=poll), redirect_stdout(io.StringIO()):
            try:
                self.assertEqual(self.helper.run_parallel(args), 0)
            finally:
                self.sessions.extend(sessions)
        self.assertEqual(len({session.tab.http_endpoint for session in sessions}), 8)
        for session in sessions:
            self.assertIsNotNone(session.process.poll())

    def test_ratings_and_manual_captcha_submit_only_once(self):
        session = self.new_session(1)
        self.start_headless([session])
        page = self.connect_form(session, captcha="")
        self.poll(session, "prepare-form.js", "ready")
        self.assertEqual(page.locator("select.rating").evaluate_all(
            "items => items.map(item => item.value)"), ["5"] * 8)
        with self.assertRaisesRegex(RuntimeError, "CAPTCHA"):
            self.poll(session, "submit-form.js", "clicked", timeout=0.1)
        self.assertEqual(page.evaluate("window.submitClicks"), 0)
        page.evaluate("window.fixtureVerifyCaptcha('fixture-confirmed')")
        self.poll(session, "submit-form.js", "clicked")
        self.poll(session, "submit-form.js", "clicked")
        self.poll(session, "read-vote-result.js", "success")
        self.assertEqual(page.evaluate("window.submitClicks"), 1)
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_open_profile_is_rejected_after_manual_mode_releases_lock(self):
        session = self.new_session(1)
        self.start_headless([session])
        session.close(keep_open=True)
        self.assertIsNone(session.process.poll())
        duplicate = self.new_session(1)
        with self.assertRaisesRegex(RuntimeError, "vẫn mở"):
            duplicate.start(timeout=1)
        self.assertIsNone(duplicate.process)
        self.assertIsNone(session.process.poll())

    def test_startup_failure_closes_the_process_and_releases_profile(self):
        session = self.new_session(1)
        # Chrome thật khởi động, nhưng kết nối CDP bị lỗi ở biên bên ngoài.
        with patch.object(self.helper, "CdpConnection", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                self.start_headless_with_timeout(session, 1)
        self.assertIsNotNone(session.process.poll())
        with self.helper.ProfileLease(session.profile):
            pass

    def start_headless_with_timeout(self, session, timeout):
        with patch.object(self.helper.subprocess, "Popen", side_effect=self.launch_headless):
            session.start(timeout=timeout)

    def test_cancellation_stops_waiting_without_submitting(self):
        session = self.new_session(1)
        self.start_headless([session])
        page = self.connect_form(session, captcha="")
        self.poll(session, "prepare-form.js", "ready")
        self.stop.set()
        with self.assertRaises(self.helper.Cancelled):
            self.poll(session, "submit-form.js", "clicked")
        self.assertEqual(page.evaluate("window.submitClicks"), 0)

    def run_preloaded_worker(self, session, **options):
        args = self.helper.parse_args(["--profiles-dir", self.directory.name])
        args.captcha_timeout = 0.1
        args.response_timeout = 0.2
        for name, value in options.items():
            setattr(args, name, value)
        native_evaluate = session.tab.evaluate
        def dispatch(source):
            result = native_evaluate(source)
            self.page.wait_for_timeout(10)
            return result
        with patch.object(self.helper, "ChromeSession", return_value=session), \
                patch.object(session, "start"), patch.object(session, "navigate"), \
                patch.object(session.tab, "evaluate", side_effect=dispatch), \
                redirect_stdout(io.StringIO()):
            return self.helper.run_worker(1, args, self.stop)

    def test_worker_success_closes_own_chrome_after_one_submission(self):
        session = self.new_session(1)
        self.start_headless([session])
        self.connect_form(session)
        self.assertEqual(self.run_preloaded_worker(session), 0)
        self.assertIsNotNone(session.process.poll())
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_uncertain_result_closes_chrome_without_retry(self):
        session = self.new_session(1)
        self.start_headless([session])
        self.connect_form(session, status=500)
        self.assertEqual(self.run_preloaded_worker(session), 1)
        self.assertIsNotNone(session.process.poll())
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_server_captcha_rejection_closes_chrome_after_exactly_one_submission(self):
        session = self.new_session(1)
        self.start_headless([session])
        page = self.connect_form(session, response="3")
        with page.expect_event("close"):
            self.assertEqual(self.run_preloaded_worker(session, response_timeout=1), 1)
        self.assertIsNotNone(session.process.poll())
        self.assertTrue(page.is_closed())
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])
        with self.helper.ProfileLease(session.profile):
            pass

    def test_cloudflare_failure_reports_code_and_closes_chrome_without_submitting(self):
        session = self.new_session(1)
        self.start_headless([session])
        page = self.connect_form(session, captcha="")
        page.evaluate("console.error('[Cloudflare Turnstile] Error: 600010.')")
        self.poll(session, "prepare-form.js", "ready")
        with self.assertRaisesRegex(self.helper.CaptchaVerificationError, "600010"):
            self.poll(session, "submit-form.js", "clicked", timeout=0.1)
        with page.expect_event("close"):
            self.assertEqual(self.run_preloaded_worker(session), 1)
        self.assertIsNotNone(session.process.poll())
        self.assertTrue(page.is_closed())
        self.assertEqual([method for method, _ in self.requests], ["GET"])
        with self.helper.ProfileLease(session.profile):
            pass

    def test_historical_cloudflare_error_does_not_block_later_valid_verification(self):
        session = self.new_session(1)
        self.start_headless([session])
        page = self.connect_form(session)
        page.evaluate("console.error('[Cloudflare Turnstile] Error: 600010.')")
        self.assertEqual(self.run_preloaded_worker(session), 0)
        self.assertIsNotNone(session.process.poll())
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_select_only_retains_chrome_with_ratings_and_no_submission(self):
        session = self.new_session(1)
        self.start_headless([session])
        page = self.connect_form(session)
        self.assertEqual(self.run_preloaded_worker(session, select_only=True), 0)
        self.assertIsNone(session.process.poll())
        self.assertEqual(page.locator("select.rating").evaluate_all(
            "items => items.map(item => item.value)"), ["5"] * 8)
        self.assertEqual(page.evaluate("window.submitClicks"), 0)

    def test_interrupt_closes_manual_worker_that_finished_before_other_worker(self):
        sessions = []
        base = self.helper.ChromeSession
        navigated = threading.Barrier(2, timeout=15)
        class TrackingSession(base):
            def __init__(session, *args):
                super().__init__(*args)
                sessions.append(session)
            def navigate(session, timeout):
                navigated.wait()
                if session.profile.name == "worker-2":
                    session.stop.wait(10)
                    session.check_cancelled()
                    raise RuntimeError("Điều phối không hủy worker đang chờ.")
        native_completed = self.helper.as_completed
        def interrupt_when_first_worker_finishes(futures):
            for future in native_completed(futures):
                yield future
                raise KeyboardInterrupt
        args = self.helper.parse_args(["--profiles-dir", self.directory.name, "--open-only"])
        args.chrome = self.chrome
        with patch.object(self.helper, "ChromeSession", TrackingSession), \
                patch.object(self.helper, "as_completed", interrupt_when_first_worker_finishes), \
                patch.object(self.helper.subprocess, "Popen", side_effect=self.launch_headless), \
                redirect_stdout(io.StringIO()):
            try:
                self.assertEqual(self.helper.run_parallel(args), 130)
            finally:
                self.sessions.extend(sessions)
        self.assertEqual(len(sessions), 2)
        for session in sessions:
            self.assertIsNotNone(session.process.poll())
            with self.helper.ProfileLease(session.profile):
                pass

    def test_interrupt_during_final_cleanup_closes_previously_released_manual_chrome(self):
        sessions = []
        closing = 0
        base = self.helper.ChromeSession
        class TrackingSession(base):
            def __init__(session, *args):
                super().__init__(*args)
                sessions.append(session)
            def navigate(session, timeout):
                pass  # Giữ trang dữ liệu cục bộ, không truy cập trang bình chọn.
            def close(session, keep_open=False):
                nonlocal closing
                if keep_open:
                    closing += 1
                    if closing == 2:
                        raise KeyboardInterrupt
                return super().close(keep_open=keep_open)
        args = self.helper.parse_args(["--profiles-dir", self.directory.name, "--open-only"])
        args.chrome = self.chrome
        with patch.object(self.helper, "ChromeSession", TrackingSession), \
                patch.object(self.helper.subprocess, "Popen", side_effect=self.launch_headless), \
                redirect_stdout(io.StringIO()):
            try:
                try:
                    result = self.helper.run_parallel(args)
                except KeyboardInterrupt:
                    self.fail("Ctrl+C trong bước dọn dẹp phải tiếp tục đóng tất cả worker.")
                self.assertEqual(result, 130)
            finally:
                self.sessions.extend(sessions)
        self.assertEqual(len(sessions), 2)
        for session in sessions:
            self.assertIsNotNone(session.process.poll())


if __name__ == "__main__":
    unittest.main()
