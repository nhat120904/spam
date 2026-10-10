"""Parallel ownership/workflow tests; desktop Chrome tests require opt-in."""

from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import os
import signal
import time

try:
    import open_incognito_parallel as helper
except ModuleNotFoundError:
    helper = None


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(helper, "Chưa có lệnh chạy Chrome song song.")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name) / "worker-1"

    def args(self, *extra):
        return helper.parse_args(["--profiles-dir", self.temp.name, *extra])

    def test_profile_cannot_be_reserved_twice(self):
        with helper.ProfileLease(self.profile):
            with self.assertRaisesRegex(RuntimeError, "đang"):
                with helper.ProfileLease(self.profile):
                    self.fail("Hai worker đã dùng chung hồ sơ.")
        with helper.ProfileLease(self.profile):
            pass

    def test_stale_owner_does_not_reserve_an_unrelated_live_process(self):
        # A saved PID can later refer to a completely different process.
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.profile.mkdir()
        owner = self.profile / "parallel-owner.json"
        owner.write_text(json.dumps({"pid": process.pid}))
        try:
            try:
                with helper.ProfileLease(self.profile):
                    pass
            except RuntimeError as error:
                self.fail(f"PID của tiến trình khác đã chặn hồ sơ: {error}")
            self.assertIsNone(process.poll(), "Không được đóng tiến trình có PID tái sử dụng.")
            self.assertFalse(owner.exists(), "Thông tin PID cũ phải được dọn.")
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_close_workers_refuses_a_profile_used_by_another_script(self):
        with helper.ProfileLease(self.profile):
            result = subprocess.run(
                [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                 "--profiles-dir", self.temp.name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("đang", result.stdout)

    def test_close_workers_does_not_create_missing_profiles(self):
        root = Path(self.temp.name) / "missing"
        result = subprocess.run(
            [sys.executable, helper.__file__, "--close-workers", "--workers", "2",
             "--profiles-dir", str(root)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(root.exists())

    def test_close_workers_dry_run_does_not_modify_profiles(self):
        self.profile.mkdir()
        owner = self.profile / "parallel-owner.json"
        owner.write_text('{"pid": 1}')
        result = subprocess.run(
            [sys.executable, helper.__file__, "--close-workers", "--dry-run", "--workers", "1",
             "--profiles-dir", self.temp.name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(owner.read_text(), '{"pid": 1}')

    def test_invalid_owner_metadata_releases_profile_lock(self):
        self.profile.mkdir()
        (self.profile / "parallel-owner.json").write_text('{"pid": true}')
        try:
            with self.assertRaisesRegex(RuntimeError, "sở hữu"):
                with helper.ProfileLease(self.profile):
                    pass
        except (TypeError, OSError) as error:
            self.fail(f"PID không hợp lệ phải bị từ chối trước khi kiểm tra tiến trình: {error}")
        (self.profile / "parallel-owner.json").unlink()
        with helper.ProfileLease(self.profile):
            pass

    def test_two_workers_run_at_the_same_time_and_errors_are_aggregated(self):
        barrier = threading.Barrier(2)
        seen = []
        def work(worker_id, args, stop, register_session=None):
            seen.append(worker_id)
            barrier.wait(timeout=3)  # A sequential executor would fail here.
            return 0 if worker_id == 1 else 1
        with patch.object(helper, "run_worker", side_effect=work):
            self.assertEqual(helper.run_parallel(self.args()), 1)
        self.assertCountEqual(seen, [1, 2])

    def test_ctrl_c_also_closes_a_manual_worker_that_already_finished(self):
        finished = threading.Event()
        closed = []
        class Browser:
            def __init__(self, profile, chrome, stop):
                self.name, self.stop = profile.name, stop
                self.pid = 101
            def start(self):
                pass
            def ensure_permission(self, timeout, log):
                if self.name == "worker-2":
                    self.stop.wait(3)
                    raise helper.Cancelled("cancelled")
            def open_tab(self, mode, url):
                return {"window_id": 11, "tab_id": 12}
            def evaluate(self, target, source):
                finished.set()
                return json.dumps({"state": "ready", "ratings": [5] * 8})
            def close(self, keep_open=False):
                closed.append((self.name, keep_open))
        def interrupt_when_first_finishes(futures):
            self.assertTrue(finished.wait(3))
            next(future for future in futures if futures[future] == 1).result(timeout=3)
            raise KeyboardInterrupt()
        with patch.object(helper, "ChromeSession", Browser), \
                patch.object(helper, "as_completed", side_effect=interrupt_when_first_finishes), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(helper.run_parallel(self.args("--select-only")), 130)
        self.assertIn(("worker-1", False), closed)
        self.assertIn(("worker-2", False), closed)

    def test_alarm_during_final_cleanup_still_closes_every_session(self):
        for phase in ("executor", "browser"):
            with self.subTest(phase=phase):
                closed = []
                first_registered = threading.Event()
                real_executor = ThreadPoolExecutor
                class Executor(real_executor):
                    def shutdown(self, *args, **kwargs):
                        if phase == "executor" and not getattr(self, "interrupted", False):
                            self.interrupted = True
                            signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
                        return super().shutdown(*args, **kwargs)
                class Browser:
                    def __init__(self, worker_id):
                        self.worker_id = worker_id
                    def close(self, keep_open=False):
                        closed.append((self.worker_id, keep_open))
                        if phase == "browser" and self.worker_id == 2 and keep_open:
                            signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
                def work(worker_id, args, stop, register_session):
                    if worker_id == 2:
                        first_registered.wait(3)
                    register_session(worker_id, Browser(worker_id))
                    first_registered.set()
                    return 0
                with patch.object(helper, "ThreadPoolExecutor", Executor), \
                        patch.object(helper, "run_worker", side_effect=work), redirect_stdout(io.StringIO()):
                    try:
                        result = helper.main(["--workers", "2", "--profiles-dir", self.temp.name])
                    except KeyboardInterrupt:
                        self.fail(f"SIGALRM ở bước {phase} đã ngắt dọn phiên.")
                self.assertEqual(result, 130)
                self.assertIn((1, False), closed)
                self.assertIn((2, False), closed)

    def test_rejected_worker_lease_does_not_clean_another_scripts_helpers(self):
        with helper.ProfileLease(self.profile), \
                patch.object(helper, "close_profile_helpers") as cleanup, redirect_stdout(io.StringIO()):
            result = helper.run_worker(1, self.args(), threading.Event())
        self.assertEqual(result, 1)
        self.assertEqual(cleanup.call_count, 0, "Chưa giữ khóa thì không được dọn helper.")

    def test_helper_failure_does_not_prevent_owned_main_shutdown(self):
        class Process:
            dead = False
            pid = os.getpid()
            def poll(self):
                return 0 if self.dead else None
            def terminate(self):
                pass
            def kill(self):
                self.dead = True
            def wait(self, timeout):
                if not self.dead:
                    raise subprocess.TimeoutExpired("frozen fixture", timeout)
                return 0
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        session.lease = helper.ProfileLease(self.profile)
        session.lease.__enter__()
        session.process = Process()
        with patch.object(helper, "close_profile_helpers", side_effect=RuntimeError("helper scan failed")):
            with self.assertRaisesRegex(RuntimeError, "helper scan failed"):
                session.close()
        self.assertTrue(session.process.dead, "Lỗi helper không được bỏ qua bước kill Chrome cha.")

    def test_helper_failure_does_not_prevent_old_main_shutdown(self):
        identity = {"started_at": "Sat Oct 10 00:00:00 2026", "command": "Chrome fixture"}
        alive = True
        def send(pid, sig):
            nonlocal alive
            if sig == signal.SIGKILL:
                alive = False
        clock = iter(range(100))
        lease = helper.ProfileLease(self.profile)
        with patch.object(helper, "process_identity", side_effect=lambda pid: identity if alive else None), \
                patch.object(helper.os, "kill", side_effect=send), \
                patch.object(helper.time, "monotonic", side_effect=lambda: next(clock)), \
                patch.object(helper.time, "sleep"), \
                patch.object(helper, "close_profile_helpers", side_effect=RuntimeError("helper scan failed")):
            with self.assertRaisesRegex(RuntimeError, "helper scan failed"):
                lease.close_verified_process(123, identity, str(helper.DEFAULT_CHROME))
        self.assertFalse(alive, "Lỗi helper không được bỏ qua SIGKILL cho Chrome cũ đã xác minh.")

    def test_interrupted_cleanup_reacquires_lease_after_main_has_exited(self):
        class Process:
            pid = os.getpid()
            dead = False
            def poll(self):
                return 0 if self.dead else None
            def terminate(self):
                self.dead = True
            def wait(self, timeout):
                return 0
        browser = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        browser.process = Process()
        browser.lease = helper.ProfileLease(self.profile)
        browser.lease.__enter__()
        browser.lease.record_pid(browser.pid)
        interrupted = False
        completed = False
        def sweep(*args, **kwargs):
            nonlocal interrupted, completed
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            completed = True
        with patch.object(helper, "close_profile_helpers", side_effect=sweep):
            with self.assertRaises(KeyboardInterrupt):
                browser.close()
            browser.close()
        self.assertTrue(completed, "Dọn lại phải xử lý helper dù Chrome cha đã thoát.")
        self.assertFalse((self.profile / "parallel-owner.json").exists())

    def test_dry_run_does_not_launch_chrome_or_create_profiles(self):
        root = Path(self.temp.name) / "dry"
        output = io.StringIO()
        with redirect_stdout(output):
            result = helper.main(["--dry-run", "--workers", "3", "--profiles-dir", str(root)])
        self.assertEqual(result, 0)
        self.assertFalse(root.exists())
        self.assertIn("worker-3", output.getvalue())

    def test_rejects_invalid_worker_counts_and_timeouts(self):
        for arguments in (["--workers", "0"], ["--workers", "-1"],
                          ["--timeout", "nan"], ["--captcha-timeout", "inf"],
                          ["--permission-timeout", "0"], ["--response-timeout", "-1"]):
            with self.subTest(arguments=arguments), redirect_stdout(io.StringIO()), \
                    patch.object(sys, "stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    helper.parse_args(arguments)
                self.assertEqual(error.exception.code, 2)

    def workflow(self, args, reports, stop=None, sources=None):
        events = []
        class Browser:
            def __init__(self, profile, chrome, stop):
                self.pid = 101
            def start(self):
                events.append("start")
            def ensure_permission(self, timeout, log):
                events.append("permission")
            def open_tab(self, mode, url):
                events.append(("open", mode))
                return {"window_id": 11, "tab_id": 12}
            def evaluate(self, target, source, *, timeout=None):
                events.append("evaluate")
                if sources is not None:
                    sources.append(source)
                report = reports.pop(0)
                if isinstance(report, Exception):
                    raise report
                return json.dumps(report)
            def close(self, keep_open=False):
                events.append(("close", keep_open))
        with patch.object(helper, "ChromeSession", Browser), redirect_stdout(io.StringIO()):
            result = helper.run_worker(1, args, stop or threading.Event())
        return result, events

    def test_default_workflow_submits_once_and_cleans_up(self):
        result, events = self.workflow(self.args(), [
            {"state": "ready", "ratings": [5] * 8},
            {"state": "clicked", "message": "sent once"},
            {"state": "success", "message": "success"},
        ])
        self.assertEqual(result, 0)
        self.assertEqual(events.count("evaluate"), 3)
        self.assertEqual(events[-1], ("close", False))

    def test_result_read_recovers_from_apple_event_timeout_without_resubmitting(self):
        sources = []
        result, events = self.workflow(self.args(), [
            {"state": "ready", "ratings": [5] * 8},
            {"state": "clicked", "message": "sent once"},
            helper.ChromeError("Apple Event timed out", -1712),
            {"state": "success", "message": "accepted"},
        ], sources=sources)
        self.assertEqual(result, 0)
        self.assertEqual(sources.count(helper.SUBMIT_SOURCE.read_text()), 1)
        self.assertEqual(sources.count(helper.RESULT_SOURCE.read_text()), 2)
        self.assertEqual(events[-1], ("close", False))

    def test_result_read_retries_are_bounded_without_resubmitting(self):
        sources = []
        reports = [
            {"state": "ready", "ratings": [5] * 8},
            {"state": "clicked", "message": "sent once"},
            *[helper.ChromeError("Apple Event timed out", -1712) for _ in range(3)],
            {"state": "success", "message": "must not keep retrying"},
        ]
        result, events = self.workflow(self.args(), reports, sources=sources)
        self.assertEqual(result, 1)
        self.assertEqual(sources.count(helper.SUBMIT_SOURCE.read_text()), 1)
        self.assertEqual(sources.count(helper.RESULT_SOURCE.read_text()), 3)
        self.assertEqual(len(reports), 1)
        self.assertEqual(events[-1], ("close", False))

    def test_submit_timeout_is_not_retried(self):
        sources = []
        reports = [{"state": "ready", "ratings": [5] * 8},
                   helper.ChromeError("Apple Event timed out", -1712),
                   {"state": "clicked", "message": "must not retry submit"}]
        result, events = self.workflow(self.args(), reports, sources=sources)
        self.assertEqual(result, 1)
        self.assertEqual(sources.count(helper.SUBMIT_SOURCE.read_text()), 1)
        self.assertEqual(len(reports), 1)
        self.assertEqual(events[-1], ("close", False))

    def test_result_read_does_not_retry_permission_or_missing_tab_errors(self):
        for code in (-1743, -1728):
            with self.subTest(code=code):
                sources = []
                reports = [{"state": "ready", "ratings": [5] * 8},
                           {"state": "clicked", "message": "sent once"},
                           helper.ChromeError("Permanent Apple Event error", code),
                           {"state": "success", "message": "must not retry"}]
                result, events = self.workflow(self.args(), reports, sources=sources)
                self.assertEqual(result, 1)
                self.assertEqual(sources.count(helper.RESULT_SOURCE.read_text()), 1)
                self.assertEqual(len(reports), 1)
                self.assertEqual(events[-1], ("close", False))

    def test_result_read_transport_failure_keeps_original_deadline(self):
        class Browser:
            reads = 0
            def evaluate(self, target, source, *, timeout=None):
                self.reads += 1
                raise helper.ChromeError("Apple Event timed out", -1712)
        browser = Browser()
        with patch.object(helper.time, "monotonic", side_effect=[0, 0.1, 1.1, 1.2]):
            with self.assertRaisesRegex(RuntimeError, "Hết thời gian chờ"):
                helper.wait_state(browser, {}, helper.RESULT_SOURCE, "success", 1,
                                  threading.Event(), lambda message: None)
        self.assertEqual(browser.reads, 1, "Không đọc thêm sau deadline ban đầu.")

    def test_result_read_retry_obeys_remaining_budget_and_rejects_late_reply(self):
        clock = [0.0]
        budgets = []
        class Browser:
            def evaluate(self, target, source, *, timeout=None):
                budgets.append(timeout)
                if len(budgets) == 1:
                    clock[0] = 0.8
                    raise helper.ChromeError("Apple Event timed out", -1712)
                clock[0] = 15.0  # A stalled/late transport must not turn this into success.
                return json.dumps({"state": "success", "message": "late reply"})
        stop = threading.Event()
        def advance(seconds):
            clock[0] += seconds
        with patch.object(helper.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(stop, "wait", side_effect=advance):
            with self.assertRaisesRegex(RuntimeError, "Hết thời gian chờ"):
                helper.wait_state(Browser(), {}, helper.RESULT_SOURCE, "success", 2,
                                  stop, lambda message: None)
        self.assertEqual(budgets[0], 2)
        self.assertAlmostEqual(budgets[1], 0.7)

    def test_cancellation_during_result_retry_prevents_another_read(self):
        class Browser:
            reads = 0
            def evaluate(self, target, source, *, timeout=None):
                self.reads += 1
                raise helper.ChromeError("Apple Event timed out", -1712)
        browser = Browser()
        stop = threading.Event()
        with patch.object(stop, "wait", side_effect=lambda seconds: stop.set()):
            with self.assertRaises(helper.Cancelled):
                helper.wait_state(browser, {}, helper.RESULT_SOURCE, "success", 45,
                                  stop, lambda message: None)
        self.assertEqual(browser.reads, 1)

    def test_browser_error_closes_only_its_session(self):
        result, events = self.workflow(self.args(), [RuntimeError("tab closed")])
        self.assertEqual(result, 1)
        self.assertEqual(events[-1], ("close", False))

    def test_manual_modes_retain_browser_after_success(self):
        for flag, reports in (("--open-only", []),
                              ("--select-only", [{"state": "ready", "ratings": [5] * 8}])):
            with self.subTest(flag=flag):
                result, events = self.workflow(self.args(flag), reports)
                self.assertEqual(result, 0)
                self.assertEqual(events[-1], ("close", True))

    def test_cancellation_prevents_form_submission(self):
        stop = threading.Event()
        stop.set()
        result, events = self.workflow(self.args(), [], stop)
        self.assertEqual(result, 130)
        self.assertNotIn("evaluate", events)

    def test_cancellation_after_preparation_prevents_pending_submit(self):
        stop = threading.Event()
        class CancelAfterPreparation(list):
            def pop(self, index):
                result = super().pop(index)
                stop.set()
                return result
        reports = CancelAfterPreparation([{"state": "ready", "ratings": [5] * 8}])
        result, events = self.workflow(self.args(), reports, stop)
        self.assertEqual(result, 130)
        self.assertEqual(events.count("evaluate"), 1)
        self.assertEqual(events[-1], ("close", False))

    def test_malformed_form_reply_fails_and_closes_browser(self):
        result, events = self.workflow(self.args(), [{"unexpected": True}])
        self.assertEqual(result, 1)
        self.assertEqual(events[-1], ("close", False))

    def test_transport_rejects_malformed_browser_reply(self):
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        class Process:
            pid = 123
            def poll(self):
                return None
        session.process = Process()
        reply = subprocess.CompletedProcess([], 0, stdout='{"ok":true}', stderr="")
        with patch.object(helper.subprocess, "run", return_value=reply):
            with self.assertRaisesRegex(helper.ChromeError, "không hợp lệ"):
                session.call("ready")

    def test_transport_crash_reports_signal_and_chrome_pid(self):
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        class Process:
            pid = 123
            def poll(self):
                return None
        session.process = Process()
        reply = subprocess.CompletedProcess([], -11, stdout="", stderr="")
        with patch.object(helper.subprocess, "run", return_value=reply):
            with self.assertRaisesRegex(helper.ChromeError, "SIGSEGV.*123"):
                session.call("evaluate", window_id="11", tab_id="12", source="document.title")

    def test_result_read_recovers_from_transport_crash_without_resubmitting(self):
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        class Process:
            pid = 123
            def poll(self):
                return None
        session.process = Process()
        reply = subprocess.CompletedProcess([], -11, stdout="", stderr="")
        with patch.object(helper.subprocess, "run", return_value=reply):
            with self.assertRaises(helper.ChromeError) as error:
                session.call("evaluate", window_id="11", tab_id="12", source="document.title")
        sources = []
        result, events = self.workflow(self.args(), [
            {"state": "ready", "ratings": [5] * 8},
            {"state": "clicked", "message": "sent once"},
            error.exception,
            {"state": "success", "message": "accepted"},
        ], sources=sources)
        self.assertEqual(result, 0)
        self.assertEqual(sources.count(helper.SUBMIT_SOURCE.read_text()), 1)
        self.assertEqual(sources.count(helper.RESULT_SOURCE.read_text()), 2)
        self.assertEqual(events[-1], ("close", False))

    def test_result_read_recovers_from_osascript_timeout_without_resubmitting(self):
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        class Process:
            pid = 123
            def poll(self):
                return None
        session.process = Process()
        with patch.object(helper.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 15)):
            with self.assertRaisesRegex(helper.ChromeError, "15 giây.*123") as error:
                session.call("evaluate", window_id="11", tab_id="12", source="document.title")
        sources = []
        result, events = self.workflow(self.args(), [
            {"state": "ready", "ratings": [5] * 8},
            {"state": "clicked", "message": "sent once"},
            error.exception,
            {"state": "success", "message": "accepted"},
        ], sources=sources)
        self.assertEqual(result, 0)
        self.assertEqual(sources.count(helper.SUBMIT_SOURCE.read_text()), 1)
        self.assertEqual(sources.count(helper.RESULT_SOURCE.read_text()), 2)
        self.assertEqual(events[-1], ("close", False))

    def test_transport_uses_remaining_budget_for_subprocess_and_apple_event(self):
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        class Process:
            pid = 123
            def poll(self):
                return None
        session.process = Process()
        budgets = []
        def run(command, **kwargs):
            request = json.loads(command[-1])
            budgets.append((kwargs["timeout"], request.get("event_timeout")))
            return subprocess.CompletedProcess(command, 0, stdout='{"ok":true,"value":"ok"}', stderr="")
        with patch.object(helper.subprocess, "run", side_effect=run):
            value = session.call("evaluate", timeout=0.25, window_id="11", tab_id="12", source="document.title")
        self.assertEqual(value, "ok")
        self.assertEqual(budgets, [(0.25, 0.25)])

    def test_automation_denial_is_reported_without_waiting_for_permission(self):
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        with patch.object(session, "open_tab", return_value={"window_id": "11", "tab_id": "12"}), \
                patch.object(session, "evaluate", side_effect=helper.ChromeError("Automation denied", -1743)):
            with self.assertRaisesRegex(helper.ChromeError, "Automation denied"):
                session.ensure_permission(10, lambda message: None)

    def test_shutdown_surfaces_termination_failure(self):
        class Process:
            pid = os.getpid()
            def poll(self):
                return None
            def terminate(self):
                raise PermissionError("cannot terminate")
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        session.process = Process()
        with self.assertRaisesRegex(PermissionError, "cannot terminate"):
            session.close()

    def test_startup_failure_is_preserved_when_shutdown_also_times_out(self):
        class Process:
            pid = os.getpid()
            def poll(self):
                return None
            def terminate(self):
                pass
            def kill(self):
                pass
            def wait(self, timeout):
                raise subprocess.TimeoutExpired("Chrome fixture", timeout)
        session = helper.ChromeSession(self.profile, helper.DEFAULT_CHROME, threading.Event())
        real_popen = subprocess.Popen
        def spawn(command, *args, **kwargs):
            if command[0] == str(helper.DEFAULT_CHROME):
                return Process()
            return real_popen(command, *args, **kwargs)
        with patch.object(helper.subprocess, "Popen", side_effect=spawn), \
                patch.object(session, "call", side_effect=helper.ChromeError("Startup denied", -1743)), \
                patch.object(helper.ProfileLease, "record_pid"):
            try:
                with self.assertRaisesRegex(helper.ChromeError, "Startup denied") as error:
                    session.start()
            except subprocess.TimeoutExpired as error:
                self.fail(f"Lỗi dọn Chrome đã che mất lỗi khởi động: {error}")
        self.assertTrue(any("đóng Chrome" in note for note in error.exception.__notes__))

    def test_timeout_closes_browser_without_submission(self):
        reports = [{"state": "ready", "ratings": [5] * 8}] + [
            {"state": "waiting", "message": "CAPTCHA"} for _ in range(10)]
        result, events = self.workflow(self.args("--captcha-timeout", "0.02"), reports)
        self.assertEqual(result, 1)
        self.assertEqual(events[-1], ("close", False))


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("RUN_NATIVE_CHROME_TESTS") == "1",
                     "Set RUN_NATIVE_CHROME_TESTS=1 for two visible localhost Chrome sessions.")
class NativeParallelTests(unittest.TestCase):
    def test_unreachable_apple_event_target_returns_error_without_crashing_osascript(self):
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-", json.dumps({"pid": 2147483647, "action": "ready"})],
            input=helper.JXA_SOURCE, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr or f"osascript returncode={result.returncode}")
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertEqual(report["code"], -600)

    def test_close_workers_removes_orphan_helpers_when_main_pid_is_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            browser = helper.ChromeSession(root / "worker-1", helper.DEFAULT_CHROME, threading.Event())
            sibling = helper.ChromeSession(root / "worker-2", helper.DEFAULT_CHROME, threading.Event())
            children = set()
            def helpers_for_profile():
                result = subprocess.run(["ps", "-ww", "-ax", "-o", "pid=,args="],
                                        capture_output=True, text=True, check=True)
                return {int(line.strip().split(None, 1)[0]) for line in result.stdout.splitlines()
                        if "Google Chrome Helper" in line
                        and f" --user-data-dir={browser.profile} " in line}
            try:
                browser.start()
                sibling.start()
                browser.open_tab("incognito", "data:text/html,<title>Orphan fixture</title>")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not children:
                    children = helpers_for_profile()
                    time.sleep(0.1)
                self.assertTrue(children, "Fixture phải có tiến trình con Chrome.")
                # Đóng băng child để nó không tự thoát khi IPC với Chrome cha bị mất.
                # Nhờ đó fixture luôn tái hiện helper mồ côi, cả khi máy đang nhẹ tải.
                frozen = set()
                for pid in children:
                    try:
                        os.kill(pid, signal.SIGSTOP)
                        frozen.add(pid)
                    except ProcessLookupError:
                        pass
                self.assertTrue(frozen, "Fixture phải giữ được helper trước khi đóng Chrome cha.")
                browser.process.kill()
                browser.process.wait(timeout=5)
                browser.close(keep_open=True)
                self.assertTrue(helpers_for_profile(), "Fixture phải tái hiện renderer còn sót.")
                result = subprocess.run(
                    [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                     "--profiles-dir", folder], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(helpers_for_profile(), "Dọn phiên phải đóng cả helper mồ côi.")
                self.assertIsNone(sibling.process.poll())
            finally:
                browser.close()
                sibling.close()
                for pid in children & helpers_for_profile():
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_close_workers_can_stop_a_verified_frozen_chrome(self):
        with tempfile.TemporaryDirectory() as folder:
            browser = helper.ChromeSession(Path(folder) / "worker-1", helper.DEFAULT_CHROME, threading.Event())
            try:
                browser.start()
                browser.close(keep_open=True)
                browser.process.send_signal(signal.SIGSTOP)
                result = subprocess.run(
                    [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                     "--profiles-dir", folder], capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                browser.process.wait(timeout=5)
                self.assertFalse((browser.profile / "parallel-owner.json").exists())
            finally:
                if browser.process is not None and browser.process.poll() is None:
                    browser.process.send_signal(signal.SIGCONT)
                browser.close()

    def test_perl_alarm_stops_python_gracefully_and_closes_its_chromes(self):
        with tempfile.TemporaryDirectory() as folder:
            command = subprocess.Popen(
                ["perl", "-e", "alarm 5; exec @ARGV", sys.executable, helper.__file__,
                 "--workers", "2", "--profiles-dir", folder],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                output, _ = command.communicate(timeout=25)
                self.assertEqual(command.returncode, 130, output)
                self.assertIn("SIGALRM", output)
                self.assertFalse(list(Path(folder).glob("worker-*/parallel-owner.json")), output)
            finally:
                if command.poll() is None:
                    command.kill()
                    command.communicate(timeout=5)
                subprocess.run([sys.executable, helper.__file__, "--close-workers", "--workers", "2",
                                "--profiles-dir", folder], capture_output=True, timeout=25)

    def test_close_workers_closes_legacy_owner_and_preserves_other_browser(self):
        with tempfile.TemporaryDirectory(prefix="parallel profiles ") as folder:
            profiles = Path(folder)
            first = helper.ChromeSession(profiles / "worker-1", helper.DEFAULT_CHROME, threading.Event())
            second = helper.ChromeSession(profiles / "worker-2", helper.DEFAULT_CHROME, threading.Event())
            try:
                first.start()
                second.start()
                first.close(keep_open=True)
                with self.assertRaisesRegex(RuntimeError, "Chrome.*mở"):
                    with helper.ProfileLease(first.profile):
                        pass
                # Old script versions only saved the PID; they must also be recoverable.
                owner = first.profile / "parallel-owner.json"
                owner.write_text(json.dumps({"pid": first.pid}))
                result = subprocess.run(
                    [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                     "--profiles-dir", folder], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                first.process.wait(timeout=5)
                self.assertIsNone(second.process.poll(), "Chrome ngoài nhóm cần đóng phải còn chạy.")
                self.assertFalse(owner.exists())
                with helper.ProfileLease(first.profile):
                    pass
            finally:
                first.close()
                second.close()

    def test_restart_workers_replaces_retained_chrome_and_keeps_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "worker-1"
            (profile / "Default").mkdir(parents=True)
            (profile / "Default" / "Preferences").write_text(json.dumps({
                "browser": {"allow_javascript_apple_events": True},
            }))
            old = helper.ChromeSession(profile, helper.DEFAULT_CHROME, threading.Event())
            replacements = []
            session_class = helper.ChromeSession
            def create_session(*args, **kwargs):
                browser = session_class(*args, **kwargs)
                replacements.append(browser)
                return browser
            try:
                old.start()
                old.close(keep_open=True)
                with patch.object(helper, "URL", "data:text/html,<title>Restart fixture</title>"), \
                        patch.object(helper, "ChromeSession", side_effect=create_session), \
                        redirect_stdout(io.StringIO()):
                    try:
                        result = helper.main(["--workers", "1", "--restart-workers", "--open-only",
                                              "--profiles-dir", folder])
                    except SystemExit as error:
                        self.fail(f"Chưa hỗ trợ khởi động lại worker: {error}")
                self.assertEqual(result, 0)
                old.process.wait(timeout=5)
                owner = json.loads((profile / "parallel-owner.json").read_text())
                self.assertNotEqual(owner["pid"], old.pid)
                with self.assertRaisesRegex(RuntimeError, "Chrome.*mở"):
                    with helper.ProfileLease(profile):
                        pass
                result = subprocess.run(
                    [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                     "--profiles-dir", folder], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                replacements[0].process.wait(timeout=5)
                preferences = json.loads((profile / "Default" / "Preferences").read_text())
                self.assertTrue(preferences["browser"]["allow_javascript_apple_events"])
            finally:
                # The cleanup command also covers a retained replacement if an assertion fails.
                subprocess.run([sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                                "--profiles-dir", folder], capture_output=True, timeout=15)
                for browser in replacements:
                    browser.close()
                old.close()

    def test_cleanup_does_not_signal_a_pid_with_different_start_time_or_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            browser = helper.ChromeSession(root / "worker-1", helper.DEFAULT_CHROME, threading.Event())
            try:
                browser.start()
                browser.close(keep_open=True)
                owner_path = browser.profile / "parallel-owner.json"
                owner = json.loads(owner_path.read_text())
                owner["started_at"] = "Fri Jan 1 00:00:00 1999"
                owner_path.write_text(json.dumps(owner))
                result = subprocess.run(
                    [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                     "--profiles-dir", folder], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIsNone(browser.process.poll(), "Không được đóng PID đã đổi thời điểm khởi động.")
                other = root / "other" / "worker-1"
                other.mkdir(parents=True)
                (other / "parallel-owner.json").write_text(json.dumps({"pid": browser.pid}))
                result = subprocess.run(
                    [sys.executable, helper.__file__, "--close-workers", "--workers", "1",
                     "--profiles-dir", str(other.parent)], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIsNone(browser.process.poll(), "Không được đóng Chrome của hồ sơ khác.")
            finally:
                browser.close()

    def test_prepare_waits_for_navigation_from_chrome_new_tab(self):
        self.assertIsNotNone(helper)
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "worker-1"
            (profile / "Default").mkdir(parents=True)
            (profile / "Default" / "Preferences").write_text(json.dumps({
                "browser": {"allow_javascript_apple_events": True},
            }))
            browser = helper.ChromeSession(profile, helper.DEFAULT_CHROME, threading.Event())
            try:
                browser.start()
                target = browser.open_tab("incognito", "chrome://newtab/")
                source = helper.PREPARE_SOURCE.read_text(encoding="utf-8")
                report = json.loads(browser.evaluate(target, source))
                self.assertEqual(report["state"], "waiting", report)
                # Một trang thật khác vẫn phải bị từ chối; chỉ newtab là chuyển tiếp.
                other = browser.open_tab("incognito", "data:text/html,<title>Other page</title>")
                for _ in range(30):
                    if browser.evaluate(other, "location.protocol") == "data:":
                        break
                    time.sleep(0.1)
                report = json.loads(browser.evaluate(other, source))
                self.assertEqual(report["state"], "error", report)
            finally:
                browser.close()

    def test_missing_permission_guides_user_and_times_out(self):
        self.assertIsNotNone(helper)
        with tempfile.TemporaryDirectory() as folder:
            browser = helper.ChromeSession(Path(folder) / "worker-1", helper.DEFAULT_CHROME, threading.Event())
            messages = []
            try:
                browser.start()
                with self.assertRaisesRegex(RuntimeError, "Hết thời gian chờ bật"):
                    browser.ensure_permission(0.2, messages.append)
                self.assertEqual(len(messages), 1)
                self.assertIn("Allow JavaScript from Apple Events", messages[0])
            finally:
                browser.close()

    def test_ctrl_c_closes_both_owned_chrome_processes(self):
        self.assertIsNotNone(helper)
        with tempfile.TemporaryDirectory() as folder:
            command = subprocess.Popen(
                [sys.executable, str(Path(helper.__file__)), "--workers", "2", "--profiles-dir", folder],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            pids = []
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    owners = list(Path(folder).glob("worker-*/parallel-owner.json"))
                    if len(owners) == 2:
                        pids = [json.loads(owner.read_text())["pid"] for owner in owners]
                        break
                    time.sleep(0.1)
                self.assertEqual(len(pids), 2, "Cả hai Chrome phải khởi động trước khi Ctrl+C.")
                command.send_signal(signal.SIGINT)
                output, _ = command.communicate(timeout=25)
                self.assertEqual(command.returncode, 130, output)
                for pid in pids:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
            finally:
                if command.poll() is None:
                    command.kill()
                    command.communicate(timeout=5)
                for owner in Path(folder).glob("worker-*/parallel-owner.json"):
                    try:
                        os.kill(json.loads(owner.read_text())["pid"], signal.SIGTERM)
                    except ProcessLookupError:
                        pass

    def test_pid_cookie_storage_and_cleanup_are_independent(self):
        self.assertIsNotNone(helper)
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'<!doctype html><title>Parallel fixture</title><p>Local isolation test</p>'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        browsers = []
        for number in (1, 2):
            profile = Path(temp.name) / f"worker-{number}"
            (profile / "Default").mkdir(parents=True)
            # Test profiles only: no personal profile or production preference is edited.
            (profile / "Default" / "Preferences").write_text(json.dumps({
                "browser": {"allow_javascript_apple_events": True},
            }))
            browser = helper.ChromeSession(profile, helper.DEFAULT_CHROME, threading.Event())
            browsers.append(browser)
            self.addCleanup(browser.close)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda browser: browser.start(), browsers))
        first, second = browsers
        self.assertNotEqual(first.pid, second.pid)
        for browser in browsers:
            browser.ensure_permission(10, lambda message: None)
        url = f"http://127.0.0.1:{server.server_port}/"
        a = first.open_tab("incognito", url)
        b = second.open_tab("incognito", url)
        for browser, target in ((first, a), (second, b)):
            for _ in range(30):
                if browser.evaluate(target, "document.readyState") == "complete":
                    break
                threading.Event().wait(0.1)
        first.evaluate(a, "document.cookie='worker=one;path=/';localStorage.setItem('worker','one');'ok'")
        self.assertEqual(second.evaluate(b, "document.cookie"), "")
        self.assertIsNone(second.evaluate(b, "localStorage.getItem('worker')"))
        second.evaluate(b, "document.cookie='worker=two;path=/';'ok'")
        self.assertEqual(first.evaluate(a, "document.cookie"), "worker=one")
        self.assertEqual(second.evaluate(b, "document.cookie"), "worker=two")
        first.close_tab(a)
        self.assertEqual(second.evaluate(b, "document.title"), "Parallel fixture")
        first.close(keep_open=True)
        self.assertTrue((first.profile / "parallel-owner.json").exists())
        first.close()
        self.assertFalse((first.profile / "parallel-owner.json").exists(),
                         "Đóng bình thường phải dọn PID cũ khỏi hồ sơ.")
        self.assertEqual(second.evaluate(b, "document.cookie"), "worker=two")
        self.assertFalse(second.process.poll() is not None)


if __name__ == "__main__":
    unittest.main()
