#!/usr/bin/env python3
"""Mở Chrome ẩn danh trên Windows, chọn 8 mục 5 sao và chờ bạn xác minh CAPTCHA."""

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener


URL = ("https://treemvietnam.net.vn/truong-hoc-hanh-phuc/"
       "truong-tieu-hoc-thinh-liet-1098.html")
SOURCE_DIR = Path(__file__).resolve().parent / "src"
LOCAL_HTTP = build_opener(ProxyHandler({}))
# URL cục bộ có dấu nhận diện; tránh nhầm với tab trống Chrome tạo khi khởi động.
START_PAGE = "data:text/plain,ThinhLietHelper"


def find_chrome(override=None):
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Không tìm thấy Chrome: {path}")
        return path
    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(name)
        if root:
            path = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if path.is_file():
                return path
    on_path = shutil.which("chrome.exe")
    if on_path:
        return Path(on_path)
    raise RuntimeError("Không tìm thấy Google Chrome. Cài Chrome hoặc dùng --chrome \"C:\\...\\chrome.exe\".")


def websocket_module():
    try:
        import websocket
    except ImportError as error:
        raise RuntimeError("Thiếu thư viện. Chạy: py -m pip install -r requirements-windows.txt") from error
    return websocket


class CdpConnection:
    """Chỉ kết nối DevTools của Chrome riêng tại loopback, không đọc hồ sơ cá nhân."""

    def __init__(self, url):
        websocket = websocket_module()
        self.socket_error = websocket.WebSocketException
        try:
            self.socket = websocket.create_connection(
                url, timeout=5, suppress_origin=True,
                http_no_proxy=["127.0.0.1", "localhost"],
            )
        except (OSError, self.socket_error) as error:
            raise RuntimeError("Không kết nối được Chrome qua DevTools cục bộ.") from error
        self.next_id = 0

    def call(self, method, params=None, session_id=None):
        self.next_id += 1
        request = {"id": self.next_id, "method": method, "params": params or {}}
        if session_id:
            request["sessionId"] = session_id
        deadline = time.monotonic() + 5
        try:
            self.socket.send(json.dumps(request, ensure_ascii=False))
            while time.monotonic() < deadline:
                self.socket.settimeout(max(0.01, deadline - time.monotonic()))
                raw = self.socket.recv()
                if not raw:
                    raise RuntimeError("Kết nối Chrome đã đóng.")
                reply = json.loads(raw)
                if reply.get("id") != self.next_id:
                    continue
                if "error" in reply:
                    raise RuntimeError(f"Chrome không thực hiện được {method}: "
                                       f"{reply['error'].get('message', 'lỗi DevTools')}")
                return reply.get("result", {})
        except (OSError, self.socket_error) as error:
            raise RuntimeError("Chrome ngắt kết nối hoặc không phản hồi; không tự gửi lại.") from error
        raise RuntimeError("Chrome không phản hồi trong thời gian chờ; không tự gửi lại.")

    def close(self):
        self.socket.close()


def read_endpoint(profile):
    lines = (profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
    port = int(lines[0])
    if not 1 <= port <= 65535 or not lines[1].startswith("/devtools/browser/"):
        raise ValueError("Cổng DevTools không hợp lệ.")
    return f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}{lines[1]}"


def endpoint_is_alive(profile):
    try:
        http, ws = read_endpoint(profile)
        with LOCAL_HTTP.open(http + "/json/version", timeout=1) as response:
            version = json.load(response)
        return version.get("webSocketDebuggerUrl") == ws
    except (OSError, ValueError, IndexError):
        return False


class ChromeTab:
    @classmethod
    def launch(cls, chrome, profile, timeout=30):
        websocket_module()  # Báo thiếu thư viện trước khi mở cửa sổ.
        profile = Path(profile)
        profile.mkdir(parents=True, exist_ok=True)
        if endpoint_is_alive(profile):
            raise RuntimeError("Cửa sổ Chrome của công cụ vẫn mở. Đóng cửa sổ đó rồi chạy lại; "
                               "không cần đóng Chrome cá nhân.")
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        process = subprocess.Popen(
            [str(chrome), f"--user-data-dir={profile}", "--remote-debugging-port=0",
             "--remote-debugging-address=127.0.0.1", "--no-first-run",
             "--no-default-browser-check", "--incognito", "--new-window", START_PAGE],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Chrome không khởi động được. Nếu cửa sổ của công cụ còn mở, "
                                   "hãy đóng cửa sổ đó rồi chạy lại.")
            try:
                http, ws = read_endpoint(profile)
                connection = CdpConnection(ws)
            except (OSError, ValueError, IndexError, RuntimeError):
                time.sleep(0.1)
                continue
            try:
                while time.monotonic() < deadline:
                    pages = [target for target in connection.call("Target.getTargets")["targetInfos"]
                             if target["type"] == "page" and target["url"] == START_PAGE]
                    if len(pages) > 1:
                        raise RuntimeError("Có nhiều tab trống nên không xác định được tab của công cụ.")
                    if pages:
                        target_id = pages[0]["targetId"]
                        session_id = connection.call("Target.attachToTarget", {
                            "targetId": target_id, "flatten": True,
                        })["sessionId"]
                        return cls(connection, target_id, session_id, http, process)
                    time.sleep(0.1)
            except BaseException:
                connection.close()
                raise
            connection.close()
            break
        raise RuntimeError("Hết thời gian chờ Chrome khởi động.")

    def __init__(self, connection, target_id, session_id, http_endpoint, process):
        self.connection = connection
        self.target_id = target_id
        self.session_id = session_id
        self.http_endpoint = http_endpoint
        self.process = process

    def evaluate(self, source):
        result = self.connection.call("Runtime.evaluate", {
            "expression": source, "returnByValue": True,
        }, self.session_id)
        if "exceptionDetails" in result:
            raise RuntimeError("JavaScript của biểu mẫu gặp lỗi.")
        return result.get("result", {}).get("value")

    def navigate(self):
        result = self.connection.call("Page.navigate", {"url": URL}, self.session_id)
        if result.get("errorText"):
            raise RuntimeError(f"Chrome không tải được trang: {result['errorText']}")

    def close_vote_tab(self):
        targets = self.connection.call("Target.getTargets")["targetInfos"]
        if not any(target["targetId"] == self.target_id for target in targets):
            return False
        result = self.connection.call("Target.closeTarget", {"targetId": self.target_id})
        if not result.get("success"):
            raise RuntimeError("Chrome chưa đóng được tab của công cụ.")
        return True

    def disconnect(self):
        # Ngắt điều khiển sau khi đã xử lý đúng tab của công cụ.
        self.connection.close()


def wait_for_state(tab, source_name, desired, timeout, timeout_message, interval=0.5):
    source = (SOURCE_DIR / source_name).read_text(encoding="utf-8")
    started = time.monotonic()
    deadline = started + timeout
    last_message = "Trang chưa sẵn sàng."
    last_report = None
    last_report_at = 0
    while time.monotonic() < deadline:
        result = json.loads(tab.evaluate(source))
        if result["state"] == desired:
            return result
        if result["state"] == "error":
            raise RuntimeError(result["message"])
        last_message = result["message"]
        now = time.monotonic()
        if last_message != last_report or now - last_report_at >= 5:
            print(f"{last_message} ({int(now - started)} giây)", flush=True)
            last_report, last_report_at = last_message, now
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"{timeout_message} {last_message}")


def run_workflow(tab, timeout=45, captcha_timeout=10, response_timeout=45,
                 select_only=False, navigate=False):
    keep_open = False
    try:
        if navigate:
            tab.navigate()
            print("Đã mở trang bằng Chrome ẩn danh.", flush=True)
        wait_for_state(tab, "prepare-form.js", "ready", timeout,
                       "Hết thời gian chờ biểu mẫu:", interval=0.25)
        print("Đã chọn 5 sao cho đủ tám mục.", flush=True)
        if select_only:
            print("Bạn tự xác minh CAPTCHA và bấm nút gửi. Tab vẫn mở.", flush=True)
            keep_open = True
            return
        print("Bạn chỉ cần xác minh CAPTCHA; script sẽ tự bấm Bình chọn ngay một lần.", flush=True)
        submitted = wait_for_state(tab, "submit-form.js", "clicked", captcha_timeout,
                                   "Hết thời gian chờ CAPTCHA, chưa bấm gửi:")
        print(submitted["message"], flush=True)
        print("Đang chờ kết quả bình chọn...", flush=True)
        result = wait_for_state(tab, "read-vote-result.js", "success", response_timeout,
                                "Đã bấm gửi nhưng chưa thấy thành công; không tự gửi lại.")
        print(result["message"], flush=True)
    finally:
        if not keep_open:
            failed = sys.exc_info()[0] is not None
            try:
                if tab.close_vote_tab():
                    print("Đã đóng tab bình chọn ẩn danh.", flush=True)
            except (RuntimeError, OSError, ValueError) as error:
                if not failed:
                    raise
                print(f"Không đóng được tab ẩn danh: {error}", file=sys.stderr)


@contextmanager
def single_run(directory):
    # Khóa được Windows giải phóng khi tiến trình thoát, kể cả bị dừng đột ngột.
    import msvcrt
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "helper.lock").open("a+b") as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("Một bản script đang chạy. Chờ bản đó kết thúc.") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Thời gian chờ phải là số hữu hạn lớn hơn 0.")
    return number


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", help="Đường dẫn chrome.exe nếu Chrome cài ở vị trí khác.")
    parser.add_argument("--dry-run", action="store_true", help="Xem các bước, chưa mở Chrome.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--open-only", action="store_true", help="Chỉ mở trang, bạn tự chọn sao và gửi.")
    mode.add_argument("--select-only", action="store_true", help="Tự chọn sao rồi dừng, bạn tự gửi.")
    parser.add_argument("--timeout", type=positive_seconds, default=45, help="Chờ biểu mẫu (giây).")
    parser.add_argument("--captcha-timeout", type=positive_seconds, default=10,
                        help="Chờ CAPTCHA (giây, mặc định: 10).")
    parser.add_argument("--response-timeout", type=positive_seconds, default=45, help="Chờ kết quả (giây).")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(f"Mở Chrome ẩn danh trên Windows: {URL}")
        if not args.open_only:
            print("Mở biểu mẫu và chọn 5 sao cho cả tám mục.")
            if not args.select_only:
                print(f"Chờ bạn xác minh CAPTCHA tối đa {args.captcha_timeout:g} giây, bấm gửi một lần.")
                print("Đóng đúng tab ẩn danh khi thành công, có lỗi hoặc hết thời gian chờ.")
        return 0
    if sys.platform != "win32":
        parser.error("Bản này dành cho Windows. Trên macOS dùng open_incognito.py.")
    tab = None
    try:
        chrome = find_chrome(args.chrome)
        if args.open_only:
            subprocess.Popen([str(chrome), "--incognito", "--new-window", URL])
            print("Đã yêu cầu Chrome mở trang ẩn danh.", flush=True)
            return 0
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data:
            raise RuntimeError("Windows chưa cung cấp thư mục LOCALAPPDATA.")
        directory = Path(local_data) / "ThinhLietHelper"
        for name in ("prepare-form.js", "submit-form.js", "read-vote-result.js"):
            if not (SOURCE_DIR / name).is_file():
                raise RuntimeError(f"Thiếu src/{name}. Giải nén đầy đủ gói Windows rồi chạy lại.")
        with single_run(directory):
            tab = ChromeTab.launch(chrome, directory / "ChromeProfile")
            try:
                run_workflow(tab, args.timeout, args.captcha_timeout, args.response_timeout,
                             args.select_only, navigate=True)
            finally:
                tab.disconnect()
                tab = None
        return 0
    except KeyboardInterrupt:
        print("\nĐã dừng script; không tự gửi lại.", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    finally:
        if tab is not None:
            tab.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
