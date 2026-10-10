#!/usr/bin/env python3
"""Chạy nhiều worker trên macOS, mỗi worker có một phiên Chrome ẩn danh độc lập."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import quote

try:
    import fcntl
except ImportError:  # Cho phép xem --help/--dry-run trên hệ điều hành khác.
    fcntl = None

from open_incognito import URL, PREPARE_SOURCE, SUBMIT_SOURCE, RESULT_SOURCE


ROOT = Path(__file__).resolve().parent
DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PRINT_LOCK = threading.Lock()

# Gửi Apple Events bằng descriptor PID tường minh. Application(pid) của JXA
# có thể bị macOS phân giải lại theo bundle ID khi nhiều Chrome cùng chạy.
JXA_SOURCE = r'''
ObjC.import('Foundation');
function run(argv) {
    try {
        const r = JSON.parse(argv[0]);
        const D = $.NSAppleEventDescriptor;
        const four = s => ((s.charCodeAt(0) << 24) | (s.charCodeAt(1) << 16)
            | (s.charCodeAt(2) << 8) | s.charCodeAt(3)) >>> 0;
        const text = s => D.descriptorWithString(String(s));
        const type = s => D.descriptorWithTypeCode(four(s));
        const address = D.descriptorWithProcessIdentifier(r.pid);
        function object(kind, form, selector, container) {
            const record = D.recordDescriptor;
            record.setDescriptorForKeyword(type(kind), four('want'));
            record.setDescriptorForKeyword(D.descriptorWithEnumCode(four(form)), four('form'));
            record.setDescriptorForKeyword(selector, four('seld'));
            record.setDescriptorForKeyword(container || D.nullDescriptor, four('from'));
            return record.coerceToDescriptorType(four('obj '));
        }
        const property = (name, container) => object('prop', 'prop', type(name), container);
        function send(eventClass, eventId, params) {
            const event = D.appleEventWithEventClassEventIDTargetDescriptorReturnIDTransactionID(
                four(eventClass), four(eventId), address, -1, 0);
            Object.keys(params).forEach(key => event.setParamDescriptorForKeyword(params[key], four(key)));
            // NSError ** phải dùng tham chiếu ObjC; Ref() dành cho kiểu vô hướng.
            const error = $();
            const reply = event.sendEventWithOptionsTimeoutError(3, 10, error);
            if (!reply || reply.isNil()) {
                const failure = new Error(!error.isNil() ? ObjC.unwrap(error.localizedDescription)
                    : 'Không nhận được Apple Events từ Chrome.');
                failure.errorNumber = !error.isNil() ? Number(error.code) : 0;
                throw failure;
            }
            const errorCode = reply.paramDescriptorForKeyword(four('errn'));
            if (errorCode && !errorCode.isNil() && errorCode.int32Value !== 0) {
                const detail = reply.paramDescriptorForKeyword(four('errs'));
                const failure = new Error(detail && !detail.isNil() ? ObjC.unwrap(detail.stringValue)
                    : 'Chrome từ chối Apple Event (' + errorCode.int32Value + ').');
                failure.errorNumber = errorCode.int32Value;
                throw failure;
            }
            return reply.paramDescriptorForKeyword(four('----'));
        }
        const get = target => send('core', 'getd', {'----': target});
        const string = descriptor => ObjC.unwrap(descriptor.stringValue);
        const window = id => object('cwin', 'ID  ', text(id));
        const tab = (windowId, tabId) => object('CrTb', 'ID  ', text(tabId), window(windowId));
        let value;
        if (r.action === 'ready') {
            const first = object('cwin', 'indx', D.descriptorWithInt32(1));
            value = Boolean(string(get(property('ID  ', first))));
        } else if (r.action === 'open') {
            const props = D.recordDescriptor;
            props.setDescriptorForKeyword(text(r.mode), four('mode'));
            const win = send('core', 'crel', {'kocl': type('cwin'), 'prdt': props});
            const windowId = string(get(property('ID  ', win)));
            const activeTab = get(property('acTa', window(windowId)));
            const tabId = string(get(property('ID  ', activeTab)));
            send('core', 'setd', {'----': property('URL ', tab(windowId, tabId)), 'data': text(r.url)});
            value = {window_id: windowId, tab_id: tabId};
        } else if (r.action === 'evaluate') {
            const result = send('CrSu', 'ExJa', {'----': tab(r.window_id, r.tab_id), 'JvSc': text(r.source)});
            value = !result || result.isNil() ? null : string(result);
        } else if (r.action === 'close') {
            send('core', 'clos', {'----': tab(r.window_id, r.tab_id)});
            value = true;
        } else {
            throw new Error('Lệnh điều khiển Chrome không hợp lệ.');
        }
        if (value === undefined) value = null;
        return JSON.stringify({ok: true, value: value});
    } catch (error) {
        return JSON.stringify({ok: false, message: String(error), code: error.errorNumber || 0});
    }
}
'''


class Cancelled(RuntimeError):
    pass


class ChromeError(RuntimeError):
    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


class ChromeTransportError(ChromeError):
    """osascript đã chết/hết giờ; Apple Event có thể đã được thực thi."""


def process_identity(pid):
    """Đọc cả thời điểm khởi động và lệnh đầy đủ để nhận diện PID tái sử dụng."""
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "args="],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 1 and not result.stdout.strip():
        return None
    parts = result.stdout.strip().split(None, 5)
    if result.returncode or len(parts) != 6:
        raise RuntimeError(f"Không xác minh được tiến trình PID {pid}; giữ nguyên Chrome.")
    return {"started_at": " ".join(parts[:5]), "command": parts[5]}


def chrome_helpers(profile, chrome):
    """Chỉ nhận diện helper trong cùng bộ Chrome và có đúng --user-data-dir."""
    result = subprocess.run(
        ["ps", "-ww", "-ax", "-o", "pid=,ppid=,lstart=,args="],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode:
        raise RuntimeError("Không đọc được danh sách tiến trình con Chrome.")
    prefix = str(Path(chrome).resolve().parent.parent / "Frameworks") + "/"
    flag = f" --user-data-dir={Path(profile).resolve()}"
    helpers = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 7)
        if len(parts) != 8:
            continue
        command = parts[7]
        if command.startswith(prefix) and (flag + " " in command or command.endswith(flag)):
            helpers[int(parts[0])] = (int(parts[1]),
                                     {"started_at": " ".join(parts[2:7]), "command": command})
    return helpers


def close_profile_helpers(profile, chrome, *, orphan_only=True, log=None):
    log = log or (lambda message: None)
    original = {pid: identity for pid, (parent, identity) in chrome_helpers(profile, chrome).items()
                if not orphan_only or parent == 1}
    if not original:
        return
    def remaining():
        return {pid: identity for pid, (_, identity) in chrome_helpers(profile, chrome).items()
                if original.get(pid) == identity}
    # Kiểm tra lại PID/thời điểm/lệnh trước mỗi tín hiệu; không dùng killall.
    for sig, grace in ((signal.SIGTERM, 2), (signal.SIGKILL, 5)):
        for pid, identity in remaining().items():
            if process_identity(pid) == identity:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + grace
        while remaining():
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        else:
            log(f"Đã dọn {len(original)} tiến trình con Chrome của {Path(profile).name}.")
            return
    raise RuntimeError(f"Tiến trình con Chrome của {Path(profile).name} chưa thoát; giữ thông tin hồ sơ.")


class ProfileLease:
    """Khóa qua tiến trình; Chrome giữ mở ở chế độ thủ công vẫn sở hữu hồ sơ."""

    def __init__(self, profile, chrome=DEFAULT_CHROME, close_existing=False, log=None, own_pid=None):
        self.profile = Path(profile).resolve()
        self.chrome = Path(chrome).resolve()
        self.close_existing = close_existing
        self.log = log or (lambda message: None)
        self.own_pid = own_pid
        self.lock = None

    def __enter__(self):
        if fcntl is None:
            raise RuntimeError("Khóa hồ sơ này yêu cầu macOS.")
        self.profile.mkdir(parents=True, exist_ok=True)
        self.lock = (self.profile / "parallel.lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            owner = self.profile / "parallel-owner.json"
            if owner.exists():
                try:
                    metadata = json.loads(owner.read_text(encoding="utf-8"))
                    pid = metadata["pid"]
                    chrome = metadata.get("chrome", str(self.chrome))
                    started_at = metadata.get("started_at")
                    if (type(pid) is not int or pid <= 0 or not isinstance(chrome, str)
                            or not Path(chrome).is_absolute()
                            or (started_at is not None and not isinstance(started_at, str))):
                        raise ValueError("PID không hợp lệ")
                except (ValueError, KeyError, TypeError) as error:
                    raise RuntimeError(f"Thông tin sở hữu hồ sơ bị lỗi: {owner}") from error
                identity = process_identity(pid)
                prefix = f"{chrome} --user-data-dir={self.profile} "
                verified = (identity is not None and identity["command"].startswith(prefix)
                            and (started_at is None or started_at == identity["started_at"]))
                if verified:
                    if pid == self.own_pid:
                        # Lấy lại khóa để đóng chính Popen đã được giữ mở trước đó.
                        return self
                    if not self.close_existing:
                        raise RuntimeError(f"Chrome của {self.profile.name} vẫn mở (PID {pid}). "
                                           "Dùng --restart-workers để đóng phiên cũ rồi chạy lại, "
                                           "hoặc --close-workers để chỉ đóng.")
                    self.close_verified_process(pid, identity, chrome)
                elif identity is not None:
                    self.log(f"PID cũ {pid} không còn khớp Chrome của hồ sơ; không đóng tiến trình đó.")
                close_profile_helpers(self.profile, chrome, log=self.log)
                self.clear_owner()
            else:
                # Renderer có thể còn sống dù Chrome cha/bản ghi PID đã mất.
                close_profile_helpers(self.profile, self.chrome, log=self.log)
            return self
        except BlockingIOError as error:
            self.__exit__(None, None, None)
            raise RuntimeError(f"Hồ sơ {self.profile.name} đang được worker khác sử dụng.") from error
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def record_pid(self, pid):
        identity = process_identity(pid)
        if identity is None:
            raise RuntimeError("Chrome đã đóng trước khi ghi thông tin hồ sơ.")
        owner = self.profile / "parallel-owner.json"
        temporary = owner.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": pid, "chrome": str(self.chrome),
                                         "started_at": identity["started_at"]}), encoding="utf-8")
        temporary.replace(owner)

    def close_verified_process(self, pid, identity, chrome):
        # Xác minh lại ngay trước SIGTERM; tuyệt đối không đóng theo tên ứng dụng.
        if process_identity(pid) != identity:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        cleanup_error = None
        try:
            close_profile_helpers(self.profile, chrome, orphan_only=False, log=self.log)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            cleanup_error = error
        deadline = time.monotonic() + 5
        while process_identity(pid) == identity:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        else:
            if cleanup_error is not None:
                raise cleanup_error
            self.log(f"Đã đóng Chrome cũ của {self.profile.name} (PID {pid}).")
            return
        # Phiên đã được xác minh và người dùng yêu cầu đóng/khởi động lại.
        if process_identity(pid) == identity:
            self.log(f"Chrome PID {pid} không thoát sau SIGTERM; đang đóng cưỡng bức phiên worker.")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        deadline = time.monotonic() + 10
        while process_identity(pid) == identity:
            if time.monotonic() >= deadline:
                error = RuntimeError(f"Chrome PID {pid} chưa chịu đóng; giữ hồ sơ và chưa mở phiên mới.")
                if cleanup_error is not None:
                    error.add_note(f"Đồng thời không dọn được helper: {cleanup_error}")
                raise error
            time.sleep(0.1)
        if cleanup_error is not None:
            raise cleanup_error
        self.log(f"Đã đóng Chrome cũ của {self.profile.name} (PID {pid}).")

    def clear_owner(self):
        (self.profile / "parallel-owner.json").unlink(missing_ok=True)

    def __exit__(self, *args):
        if self.lock is not None:
            self.lock.close()
            self.lock = None


class ChromeSession:
    def __init__(self, profile, chrome, stop):
        self.profile = Path(profile).resolve()
        self.chrome = Path(chrome)
        self.stop = stop
        self.process = None
        self.lease = None

    @property
    def pid(self):
        return self.process.pid if self.process is not None else None

    def check_cancelled(self):
        if self.stop.is_set():
            raise Cancelled("Đã dừng worker.")

    def start(self, *, restart_existing=False, log=None):
        self.check_cancelled()
        lease = ProfileLease(self.profile, self.chrome, close_existing=restart_existing, log=log)
        lease.__enter__()
        self.lease = lease
        try:
            self.process = subprocess.Popen(
                [str(self.chrome), f"--user-data-dir={self.profile}", "--no-first-run",
                 "--no-default-browser-check", "--disable-background-mode", "about:blank"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.lease.record_pid(self.pid)
            deadline = time.monotonic() + 30
            last_error = "Chrome chưa sẵn sàng."
            while time.monotonic() < deadline:
                self.check_cancelled()
                if self.process.poll() is not None:
                    raise RuntimeError("Chrome không khởi động được. Hồ sơ có thể đang được mở "
                                       "bên ngoài script; không dùng chung hồ sơ.")
                try:
                    if self.call("ready"):
                        return
                except ChromeError as error:
                    last_error = str(error)
                    if error.code == -1743:
                        raise  # Quyền Automation của macOS, không phải lỗi chờ khởi động.
                self.stop.wait(0.2)
            raise RuntimeError(f"Hết thời gian khởi động Chrome: {last_error}")
        except BaseException as error:
            try:
                self.close()
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as cleanup_error:
                error.add_note(f"Đồng thời không đóng Chrome được: {cleanup_error}")
            raise

    def call(self, action, **payload):
        if self.process is None or self.process.poll() is not None:
            raise ChromeError("Tiến trình Chrome của worker đã đóng.")
        request = {"pid": self.pid, "action": action, **payload}
        try:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", "-", json.dumps(request, ensure_ascii=False)],
                input=JXA_SOURCE, text=True, capture_output=True, timeout=15,
            )
        except subprocess.TimeoutExpired as error:
            raise ChromeTransportError(
                f"osascript không trả lời sau 15 giây; Chrome PID {self.pid}, lệnh {action}.") from error
        if result.returncode:
            status = f"mã thoát {result.returncode}"
            if result.returncode < 0:
                try:
                    status += f", {signal.Signals(-result.returncode).name}"
                except ValueError:
                    pass
            detail = result.stderr.strip() or result.stdout.strip()
            message = f"osascript lỗi ({status}); Chrome PID {self.pid}, lệnh {action}."
            if detail:
                message += " " + detail[:600]
            error_type = ChromeTransportError if result.returncode < 0 else ChromeError
            raise error_type(message)
        try:
            reply = json.loads(result.stdout)
            if not reply["ok"]:
                raise ChromeError(reply["message"], reply.get("code", 0))
            return reply["value"]
        except (ValueError, KeyError, TypeError) as error:
            raise ChromeError("Phản hồi điều khiển Chrome không hợp lệ.") from error

    def open_tab(self, mode, url):
        self.check_cancelled()
        return self.call("open", mode=mode, url=url)

    def evaluate(self, target, source):
        self.check_cancelled()
        return self.call("evaluate", **target, source=source)

    def close_tab(self, target):
        return self.call("close", **target)

    def ensure_permission(self, timeout, log):
        label = html.escape(self.profile.name)
        setup_html = (f'<!doctype html><meta charset="utf-8"><title>Thiết lập {label}</title>'
                      f'<h1>Thiết lập {label}</h1><p>PID Chrome: {self.pid}</p>'
                      '<p>Bật View &gt; Developer &gt; Allow JavaScript from Apple Events.</p>'
                      '<p>Script sẽ tự tiếp tục khi bạn bật quyền.</p>')
        target = self.open_tab("normal", "data:text/html;charset=utf-8," + quote(setup_html))
        deadline = time.monotonic() + timeout
        guidance_shown = False
        while time.monotonic() < deadline:
            self.check_cancelled()
            try:
                ready = str(self.evaluate(target, "1")) == "1"
            except ChromeError as error:
                if error.code != 12 and "JavaScript" not in str(error):
                    raise
                ready = False
                if not guidance_shown:
                    log(f"Trong Chrome THƯỜNG của worker này (PID {self.pid}), bật "
                        "View > Developer > Allow JavaScript from Apple Events. "
                        f"Hồ sơ: {self.profile}. Chờ tối đa {timeout:g} giây.")
                    guidance_shown = True
            if ready:
                # Đóng tab kiểm tra đúng ID; Chrome vẫn có tab khởi động riêng.
                self.close_tab(target)
                return
            self.stop.wait(0.5)
        raise RuntimeError("Hết thời gian chờ bật JavaScript từ Apple Events trong hồ sơ worker.")

    def close(self, keep_open=False):
        cleanup_errors = []
        def clean_helpers(orphan_only):
            if self.lease is not None and self.lease.lock is not None:
                try:
                    close_profile_helpers(self.profile, self.chrome, orphan_only=orphan_only)
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                    cleanup_errors.append(error)
        try:
            if not keep_open and self.process is not None and self.lease is None:
                lease = ProfileLease(self.profile, self.chrome, own_pid=self.pid)
                try:
                    lease.__enter__()
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                    cleanup_errors.append(error)
                else:
                    self.lease = lease
            if not keep_open and self.process is not None and self.process.poll() is None:
                # Chỉ PID do worker này tạo; không dùng killall hoặc tên ứng dụng.
                self.process.terminate()
                clean_helpers(orphan_only=False)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            if not keep_open:
                clean_helpers(orphan_only=True)
            if (self.lease is not None and self.process is not None
                    and self.process.poll() is not None and not cleanup_errors):
                self.lease.clear_owner()
            if cleanup_errors:
                raise cleanup_errors[0]
        except BaseException as error:
            for cleanup_error in cleanup_errors:
                if cleanup_error is not error:
                    error.add_note(f"Đồng thời không dọn được helper: {cleanup_error}")
            raise
        finally:
            if self.lease is not None:
                self.lease.__exit__(None, None, None)
                self.lease = None


def log_worker(worker_id, message):
    with PRINT_LOCK:
        print(f"[Worker {worker_id}] {message}", flush=True)


def wait_state(browser, target, source_path, desired, timeout, stop, log):
    source = source_path.read_text(encoding="utf-8")
    deadline = time.monotonic() + timeout
    message = "Trang chưa sẵn sàng."
    last_report = None
    last_report_at = 0
    read_retries = 0
    while time.monotonic() < deadline:
        if stop.is_set():
            raise Cancelled("Đã dừng worker.")
        try:
            report = json.loads(browser.evaluate(target, source))
        except ChromeError as error:
            # Chỉ đọc lại kết quả sau khi đã gửi; không lặp thao tác chuẩn bị/bấm gửi.
            read_only = source_path == RESULT_SOURCE and desired == "success"
            transient = isinstance(error, ChromeTransportError) or error.code == -1712
            if not read_only or not transient:
                raise
            if read_retries >= 2:
                error.add_note("Đã bấm gửi nhưng chưa xác định được kết quả; không tự gửi lại.")
                raise
            read_retries += 1
            message = f"Lỗi đọc kết quả: {error}"
            log(f"{message} Thử đọc lại {read_retries}/2; không bấm gửi lại.")
            stop.wait(min(0.5 * read_retries, max(0, deadline - time.monotonic())))
            continue
        if not isinstance(report, dict) or "state" not in report:
            raise RuntimeError("Phản hồi biểu mẫu không hợp lệ.")
        if report["state"] == desired:
            return report
        message = report.get("message", message)
        if report["state"] == "error":
            raise RuntimeError(message)
        now = time.monotonic()
        if message != last_report or now - last_report_at >= 5:
            log(message)
            last_report, last_report_at = message, now
        stop.wait(min(0.5, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"Hết thời gian chờ: {message}. Không tự gửi lại.")


def run_worker(worker_id, args, stop, register_session=None):
    log = lambda message: log_worker(worker_id, message)
    browser = ChromeSession(args.profiles_dir / f"worker-{worker_id}", args.chrome, stop)
    if register_session is not None:
        register_session(worker_id, browser)
    keep_open = False
    status = 1
    try:
        if stop.is_set():
            raise Cancelled("Đã dừng worker.")
        if args.restart_workers:
            browser.start(restart_existing=True, log=log)
        else:
            browser.start()
        log(f"Chrome riêng đã mở (PID {browser.pid}).")
        if not args.open_only:
            browser.ensure_permission(args.permission_timeout, log)
        target = browser.open_tab("incognito", URL)
        log("Đã mở trang trong phiên ẩn danh riêng.")
        if args.open_only:
            keep_open = True
        else:
            wait_state(browser, target, PREPARE_SOURCE, "ready", args.timeout, stop, log)
            log("Đã chọn đủ tám mục 5 sao.")
            if args.select_only:
                keep_open = True
                log("Bạn tự xác minh CAPTCHA và bấm gửi trong cửa sổ này.")
            else:
                log("Chờ bạn xác minh CAPTCHA trong cửa sổ này; sẽ bấm gửi một lần.")
                report = wait_state(browser, target, SUBMIT_SOURCE, "clicked",
                                    args.captcha_timeout, stop, log)
                log(report["message"])
                report = wait_state(browser, target, RESULT_SOURCE, "success",
                                    args.response_timeout, stop, log)
                log(report["message"])
        status = 0
    except Cancelled as error:
        log(str(error))
        status = 130
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        detail = " ".join([str(error), *getattr(error, "__notes__", [])])
        log(f"Chưa hoàn tất: {detail}")
    finally:
        try:
            # Phiên thủ công vẫn thuộc lệnh chính đến khi tất cả worker kết thúc.
            # Nhờ đó Ctrl+C còn đóng được worker đã xong trước các worker khác.
            retain_for_coordinator = keep_open and not stop.is_set() and register_session is not None
            if not retain_for_coordinator:
                browser.close(keep_open=keep_open and not stop.is_set())
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            log(f"Không đóng được Chrome của worker: {error}")
            status = 1
    if status == 0:
        log("Giữ Chrome mở để thao tác tay." if keep_open else "Hoàn tất; đã đóng Chrome của worker.")
    return status


def run_parallel(args):
    stop = threading.Event()
    sessions = []
    session_lock = threading.Lock()
    def register_session(worker_id, browser):
        with session_lock:
            sessions.append((worker_id, browser))
    executor = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="chrome-worker")
    futures = {}
    statuses = []
    interrupted = False
    def close_sessions(keep_open):
        for worker_id, browser in sessions:
            try:
                browser.close(keep_open=keep_open)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                log_worker(worker_id, f"Không đóng được Chrome của worker: {error}")
                statuses.append(1)
    try:
        futures = {executor.submit(run_worker, worker_id, args, stop, register_session): worker_id
                   for worker_id in range(1, args.workers + 1)}
        for future in as_completed(futures):
            try:
                statuses.append(future.result())
            except Exception as error:
                log_worker(futures[future], f"Worker gặp lỗi: {error}")
                statuses.append(1)
    except KeyboardInterrupt:
        interrupted = True
        stop.set()
        print("\nĐang dừng tất cả worker và đóng Chrome của từng worker...", flush=True)
    finally:
        try:
            executor.shutdown(wait=True)
            close_sessions(keep_open=not interrupted)
        except KeyboardInterrupt:
            # Tín hiệu có thể đến trong chính shutdown/close, sau khi vòng chờ đã xong.
            interrupted = True
            stop.set()
            print("\nDừng trong lúc dọn phiên; tiếp tục đóng tất cả Chrome worker...", flush=True)
            executor.shutdown(wait=True)
            close_sessions(keep_open=False)
    if interrupted:
        return 130
    with PRINT_LOCK:
        print(f"Kết quả: {statuses.count(0)}/{args.workers} worker hoàn tất.", flush=True)
    return 0 if all(status == 0 for status in statuses) else 1


def close_workers(args):
    statuses = []
    for worker_id in range(1, args.workers + 1):
        profile = args.profiles_dir / f"worker-{worker_id}"
        log = lambda message: log_worker(worker_id, message)
        try:
            if profile.exists():
                with ProfileLease(profile, args.chrome, close_existing=True, log=log):
                    pass
            log("Đã dọn phiên cũ; giữ hồ sơ và quyền Allow.")
            statuses.append(0)
        except KeyboardInterrupt:
            print("\nĐã dừng đóng phiên worker.", flush=True)
            return 130
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            log(f"Chưa đóng được: {error}")
            statuses.append(1)
    print(f"Kết quả: {statuses.count(0)}/{args.workers} hồ sơ đã dọn.", flush=True)
    return 0 if all(status == 0 for status in statuses) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2, help="Số phiên Chrome độc lập (mặc định: 2).")
    parser.add_argument("--profiles-dir", type=Path, default=ROOT / "runtime" / "chrome-parallel",
                        help="Thư mục chứa hồ sơ riêng cho từng worker.")
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME, help="Đường dẫn file thực thi Chrome.")
    parser.add_argument("--dry-run", action="store_true", help="Xem cấu hình; không mở Chrome.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--open-only", action="store_true", help="Chỉ mở trang và giữ Chrome mở.")
    mode.add_argument("--select-only", action="store_true", help="Chọn sao và giữ Chrome mở để bạn tự gửi.")
    mode.add_argument("--close-workers", action="store_true", help="Chỉ đóng Chrome cũ của các worker, giữ hồ sơ.")
    parser.add_argument("--restart-workers", action="store_true",
                        help="Đóng Chrome cũ của từng worker rồi chạy lượt mới bằng cùng hồ sơ.")
    for flag, default, description in (
        ("timeout", 45, "chờ biểu mẫu"), ("permission-timeout", 180, "chờ bật quyền Apple Events"),
        ("captcha-timeout", 20, "chờ bạn xác minh CAPTCHA"),
        ("response-timeout", 45, "chờ kết quả sau khi gửi"),
    ):
        parser.add_argument(f"--{flag}", type=float, default=default,
                            help=f"Số giây {description} (mặc định: {default}).")
    args = parser.parse_args(argv)
    if args.close_workers and args.restart_workers:
        parser.error("Không dùng --close-workers cùng --restart-workers.")
    if args.workers <= 0:
        parser.error("--workers phải lớn hơn 0.")
    for name in ("timeout", "permission_timeout", "captcha_timeout", "response_timeout"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} phải là số hữu hạn lớn hơn 0.")
    args.profiles_dir = args.profiles_dir.expanduser().resolve()
    args.chrome = args.chrome.expanduser().resolve()
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.dry_run:
        for worker_id in range(1, args.workers + 1):
            if args.close_workers:
                print(f"[Worker {worker_id}] Chỉ đóng Chrome cũ; hồ sơ: "
                      f"{args.profiles_dir / f'worker-{worker_id}'}")
                continue
            if args.restart_workers:
                print(f"[Worker {worker_id}] Đóng Chrome cũ trước khi mở phiên mới.")
            print(f"[Worker {worker_id}] Chrome riêng; --user-data-dir="
                  f"{args.profiles_dir / f'worker-{worker_id}'}; ẩn danh: {URL}")
        print("Điều khiển theo PID + window ID + tab ID; mỗi worker chạy một lượt.")
        return 0
    if sys.platform != "darwin":
        print("Lệnh này dành cho Chrome và Apple Events trên macOS.", file=sys.stderr)
        return 2
    previous_handlers = {}
    signal_received = False
    def request_shutdown(signum, frame):
        nonlocal signal_received
        if not signal_received:
            signal_received = True
            print(f"\nNhận {signal.Signals(signum).name}; đang dừng và dọn Chrome worker...", flush=True)
            raise KeyboardInterrupt
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGALRM):
            previous_handlers[sig] = signal.signal(sig, request_shutdown)
    try:
        if args.close_workers:
            return close_workers(args)
        if shutil.which("osascript") is None:
            print("Không tìm thấy osascript để điều khiển Chrome.", file=sys.stderr)
            return 2
        if not args.chrome.is_file():
            print(f"Không tìm thấy Chrome: {args.chrome}", file=sys.stderr)
            return 2
        return run_parallel(args)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
