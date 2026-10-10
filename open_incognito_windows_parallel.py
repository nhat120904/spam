#!/usr/bin/env python3
"""Chạy nhiều phiên Chrome ẩn danh độc lập trên Windows; mỗi worker chạy một lượt."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from open_incognito_windows import (
    URL, SOURCE_DIR, ChromeTab, CdpConnection, endpoint_is_alive,
    find_chrome, positive_seconds, read_endpoint, websocket_module,
)


PRINT_LOCK = threading.Lock()


class Cancelled(RuntimeError):
    pass


class ProfileLease:
    """Khóa hệ điều hành, được giải phóng cả khi Python thoát đột ngột."""

    def __init__(self, profile):
        self.profile = Path(profile)
        self.lock = None

    def __enter__(self):
        self.profile.mkdir(parents=True, exist_ok=True)
        self.lock = (self.profile / "parallel.lock").open("a+b")
        if self.lock.seek(0, os.SEEK_END) == 0:
            self.lock.write(b"0")
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                # Để kiểm thử khóa/CDP trên macOS; CLI thật vẫn yêu cầu Windows.
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.__exit__(None, None, None)
            raise RuntimeError(f"Hồ sơ {self.profile.name} đang được worker khác sử dụng.") from error
        return self

    def __exit__(self, *args):
        if self.lock is not None:
            self.lock.close()
            self.lock = None


class ChromeSession:
    def __init__(self, profile, chrome, stop):
        self.profile = Path(profile).resolve()
        self.chrome = chrome
        self.stop = stop
        self.process = None
        self.connection = None
        self.tab = None
        self.lease = None
        # Dấu nhận diện khác nhau cho từng lần mở; không chọn active tab.
        self.start_page = f"data:text/plain,ThinhLiet-{self.profile.name}-{uuid4().hex}"

    @property
    def pid(self):
        return self.process.pid if self.process is not None else None

    def check_cancelled(self):
        if self.stop.is_set():
            raise Cancelled("Đã dừng worker.")

    def start(self, timeout=30):
        self.check_cancelled()
        websocket_module()
        self.lease = ProfileLease(self.profile)
        self.lease.__enter__()
        try:
            if endpoint_is_alive(self.profile):
                raise RuntimeError(f"Chrome của {self.profile.name} vẫn mở. "
                                   "Đóng cửa sổ đó trước khi chạy lại.")
            (self.profile / "DevToolsActivePort").unlink(missing_ok=True)
            self.check_cancelled()
            self.process = subprocess.Popen(
                [str(self.chrome), f"--user-data-dir={self.profile}",
                 "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                 "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
                 "--incognito", "--new-window", self.start_page],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                self.check_cancelled()
                if self.process.poll() is not None:
                    raise RuntimeError("Chrome không khởi động được; hồ sơ có thể đang được mở "
                                       "bên ngoài script. Hãy đóng Chrome dùng hồ sơ này.")
                if self.connection is None:
                    try:
                        http, ws = read_endpoint(self.profile)
                        self.connection = CdpConnection(ws)
                    except (OSError, ValueError, IndexError, RuntimeError):
                        self.stop.wait(0.1)
                        continue
                targets = self.connection.call("Target.getTargets")["targetInfos"]
                pages = [target for target in targets
                         if target["type"] == "page" and target["url"] == self.start_page]
                if len(pages) > 1:
                    raise RuntimeError("Không xác định được duy nhất tab của worker.")
                if pages:
                    target_id = pages[0]["targetId"]
                    session_id = self.connection.call("Target.attachToTarget", {
                        "targetId": target_id, "flatten": True,
                    })["sessionId"]
                    self.tab = ChromeTab(self.connection, target_id, session_id, http, self.process)
                    return
                self.stop.wait(0.1)
            raise RuntimeError("Hết thời gian chờ Chrome khởi động.")
        except BaseException:
            self.close()
            raise

    def navigate(self, timeout):
        self.check_cancelled()
        self.tab.navigate()
        deadline = time.monotonic() + timeout
        expected = urlsplit(URL)
        while time.monotonic() < deadline:
            self.check_cancelled()
            try:
                current = self.tab.evaluate("location.href")
            except RuntimeError:
                # Context JavaScript cũ có thể mất trong lúc trang chuyển hướng.
                if self.process.poll() is not None:
                    raise
                self.stop.wait(0.1)
                continue
            if current not in (self.start_page, "about:blank", "chrome://newtab/"):
                actual = urlsplit(current)
                if (actual.scheme, actual.netloc, actual.path) == (
                        expected.scheme, expected.netloc, expected.path):
                    return
                raise RuntimeError("Tab không còn ở trang Trường Tiểu học Thịnh Liệt.")
            self.stop.wait(0.1)
        raise RuntimeError("Hết thời gian chờ điều hướng tới trang bình chọn.")

    def close(self, keep_open=False):
        try:
            if not keep_open and self.process is not None and self.process.poll() is None:
                if self.connection is not None:
                    try:
                        self.connection.call("Browser.close")
                    except (RuntimeError, OSError, ValueError):
                        pass
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        # Windows terminate() chỉ dừng tiến trình cha. /T dọn cả
                        # tiến trình con của đúng PID worker, không chọn theo tên.
                        result = subprocess.run(
                            ["taskkill", "/PID", str(self.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        if result.returncode and self.process.poll() is None:
                            raise RuntimeError(f"Không dừng được cây tiến trình Chrome PID {self.pid}.")
                    else:
                        self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
        finally:
            try:
                if self.connection is not None:
                    self.connection.close()
                    self.connection = None
            finally:
                if self.lease is not None:
                    self.lease.__exit__(None, None, None)
                    self.lease = None


def log_worker(worker_id, message):
    with PRINT_LOCK:
        print(f"[Worker {worker_id}] {message}", flush=True)


def wait_state(session, source_name, desired, timeout, stop, log):
    source = (SOURCE_DIR / source_name).read_text(encoding="utf-8")
    deadline = time.monotonic() + timeout
    message = "Trang chưa sẵn sàng."
    last_report, last_report_at = None, 0
    while time.monotonic() < deadline:
        if stop.is_set():
            raise Cancelled("Đã dừng worker.")
        report = json.loads(session.tab.evaluate(source))
        if not isinstance(report, dict) or report.get("state") not in (
                "waiting", "ready", "clicked", "success", "error"):
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
        stop.wait(min(0.25, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"Hết thời gian chờ: {message}. Không tự gửi lại.")


def run_worker(worker_id, args, stop, register_session=None):
    log = lambda message: log_worker(worker_id, message)
    session = ChromeSession(args.profiles_dir / f"worker-{worker_id}", args.chrome, stop)
    if register_session is not None:
        register_session(worker_id, session)
    keep_open, status = False, 1
    try:
        session.start()
        log(f"Chrome riêng đã mở (PID {session.pid}).")
        session.navigate(args.timeout)
        log("Đã mở trang trong phiên ẩn danh riêng.")
        if args.open_only:
            keep_open = True
        else:
            wait_state(session, "prepare-form.js", "ready", args.timeout, stop, log)
            log("Đã chọn đủ tám mục 5 sao.")
            if args.select_only:
                keep_open = True
                log("Bạn tự xác minh CAPTCHA và bấm gửi trong cửa sổ này.")
            else:
                log("Chờ bạn xác minh CAPTCHA trong cửa sổ này; sẽ bấm gửi một lần.")
                report = wait_state(session, "submit-form.js", "clicked", args.captcha_timeout, stop, log)
                log(report["message"])
                report = wait_state(session, "read-vote-result.js", "success", args.response_timeout, stop, log)
                log(report["message"])
        status = 0
    except Cancelled as error:
        log(str(error))
        status = 130
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        log(f"Chưa hoàn tất: {error}")
    finally:
        try:
            # Giữ quyền sở hữu phiên thủ công đến khi toàn bộ lệnh kết thúc,
            # để Ctrl+C vẫn đóng được worker đã hoàn tất sớm.
            retained = keep_open and not stop.is_set() and register_session is not None
            if not retained:
                session.close(keep_open=keep_open and not stop.is_set())
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            log(f"Không đóng được Chrome của worker: {error}")
            status = 1
    if status == 0:
        log("Giữ Chrome mở để thao tác tay." if keep_open else "Hoàn tất; đã đóng Chrome của worker.")
    return status


def run_parallel(args):
    stop = threading.Event()
    sessions, statuses = [], []
    session_lock = threading.Lock()
    def register_session(worker_id, session):
        with session_lock:
            sessions.append((worker_id, session))
    executor = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="chrome-worker")
    futures = {}
    interrupted = False
    try:
        futures = {executor.submit(run_worker, number, args, stop, register_session): number
                   for number in range(1, args.workers + 1)}
        for future in as_completed(futures):
            try:
                statuses.append(future.result())
            except Exception as error:
                log_worker(futures[future], f"Worker gặp lỗi: {error}")
                statuses.append(1)
    except KeyboardInterrupt:
        interrupted = True
        stop.set()
        print("\nĐang dừng các worker và đóng Chrome của từng worker...", flush=True)
    finally:
        while True:
            try:
                executor.shutdown(wait=True)
                break
            except KeyboardInterrupt:
                interrupted = True
                stop.set()
        index = 0
        while index < len(sessions):
            worker_id, session = sessions[index]
            try:
                session.close(keep_open=not interrupted)
            except KeyboardInterrupt:
                interrupted = True
                stop.set()
                # Một phiên trước đó có thể đã được giữ mở và ngắt CDP.
                # Duyệt lại từ đầu để đóng cả các phiên đã giải phóng đó.
                index = 0
                continue
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                log_worker(worker_id, f"Không đóng được Chrome của worker: {error}")
                statuses.append(1)
            index += 1
    if interrupted:
        return 130
    print(f"Kết quả: {statuses.count(0)}/{args.workers} worker hoàn tất.", flush=True)
    return 0 if len(statuses) == args.workers and all(status == 0 for status in statuses) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2, help="Số phiên Chrome độc lập (mặc định: 2).")
    parser.add_argument("--chrome", help="Đường dẫn chrome.exe; mặc định tự tìm Chrome đã cài.")
    parser.add_argument("--profiles-dir", type=Path,
                        help="Thư mục hồ sơ; mặc định %%LOCALAPPDATA%%\\ThinhLietHelper\\ChromeParallel.")
    parser.add_argument("--dry-run", action="store_true", help="Xem cấu hình, không mở Chrome.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--open-only", action="store_true", help="Chỉ mở trang, giữ Chrome mở.")
    mode.add_argument("--select-only", action="store_true", help="Chọn sao, giữ Chrome mở để tự gửi.")
    for name, default, description in (
        ("timeout", 45, "chờ trang và biểu mẫu"),
        ("captcha-timeout", 180, "chờ bạn xác minh CAPTCHA"),
        ("response-timeout", 45, "chờ kết quả gửi"),
    ):
        parser.add_argument(f"--{name}", type=positive_seconds, default=default,
                            help=f"Số giây {description} (mặc định: {default}).")
    args = parser.parse_args(argv)
    if args.workers <= 0:
        parser.error("--workers phải lớn hơn 0.")
    if args.profiles_dir is None:
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data and sys.platform == "win32":
            parser.error("Không tìm thấy biến môi trường LOCALAPPDATA; hãy dùng --profiles-dir.")
        args.profiles_dir = (Path(local_data) / "ThinhLietHelper" / "ChromeParallel" if local_data
                             else Path(__file__).resolve().parent / "runtime" / "chrome-windows-parallel")
    args.profiles_dir = args.profiles_dir.expanduser().resolve()
    return args


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    if args.dry_run:
        for number in range(1, args.workers + 1):
            print(f"[Worker {number}] Chrome riêng; hồ sơ: {args.profiles_dir / f'worker-{number}'}")
        print(f"Trang: {URL}\nMỗi worker có CDP và phiên ẩn danh riêng; chạy một lượt.")
        return 0
    if sys.platform != "win32":
        print("Bản này dành cho Windows. macOS dùng open_incognito_parallel.py.", file=sys.stderr)
        return 2
    try:
        args.chrome = find_chrome(args.chrome)
        websocket_module()
        for name in ("prepare-form.js", "submit-form.js", "read-vote-result.js"):
            if not (SOURCE_DIR / name).is_file():
                raise RuntimeError(f"Thiếu src/{name}. Hãy giải nén toàn bộ bộ công cụ.")
        return run_parallel(args)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
