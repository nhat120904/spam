#!/usr/bin/env python3
"""Mở Chrome ẩn danh, chọn 5 sao và bấm bình chọn sau khi bạn xác minh CAPTCHA."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


URL = (
    "https://treemvietnam.net.vn/truong-hoc-hanh-phuc/"
    "truong-tieu-hoc-thinh-liet-1098.html"
)
PREPARE_SOURCE = Path(__file__).resolve().parent / "src" / "prepare-form.js"
SUBMIT_SOURCE = PREPARE_SOURCE.with_name("submit-form.js")
RESULT_SOURCE = PREPARE_SOURCE.with_name("read-vote-result.js")


def apple_string(value):
    return json.dumps(value, ensure_ascii=False)


def run_applescript(script):
    result = subprocess.run(
        ["osascript", "-"], input=script, text=True, capture_output=True, timeout=15
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Chrome không nhận được lệnh.")
    return result.stdout.strip()


def open_window(mode="incognito", url=URL):
    # Chrome tự quản lý cửa sổ này; không khởi chạy qua browser driver.
    script = f'''tell application "Google Chrome"
    activate
    set voteWindow to make new window with properties {{mode:{apple_string(mode)}}}
    set URL of active tab of voteWindow to {apple_string(url)}
    return id of voteWindow
end tell'''
    return int(run_applescript(script))


def ensure_javascript_permission(timeout):
    # Bật trong profile thường để quyền được giữ sau khi đóng phiên ẩn danh.
    window_id = open_window(mode="normal", url="about:blank")
    probe = f'''tell application "Google Chrome"
    return execute active tab of window id {window_id} javascript "1"
end tell'''
    deadline = time.monotonic() + timeout
    last_error = RuntimeError("Không kiểm tra được quyền JavaScript của Chrome.")
    guidance_shown = False
    while time.monotonic() < deadline:
        try:
            ready = run_applescript(probe) == "1"
        except RuntimeError as error:
            if "(12)" not in str(error) or "JavaScript" not in str(error):
                raise
            last_error = error
            ready = False
            if not guidance_shown:
                print(
                    "Chrome chưa bật quyền tự chọn sao trong hồ sơ thường.\n"
                    "Trong cửa sổ Chrome THƯỜNG vừa mở, bật:\n"
                    "  View > Developer > Allow JavaScript from Apple Events\n"
                    f"Script đang chờ tối đa {timeout:g} giây và sẽ tự chạy tiếp khi bạn bật.",
                    flush=True,
                )
                guidance_shown = True
        if ready:
            # Chỉ đóng cửa sổ kiểm tra do script tạo nếu người dùng chưa điều hướng.
            run_applescript(f'''tell application "Google Chrome"
    set setupWindow to window id {window_id}
    if (count of tabs of setupWindow) is 1 then
        set currentURL to URL of active tab of setupWindow
        if currentURL is "about:blank" then
            close setupWindow
        end if
    end if
end tell''')
            return
        time.sleep(0.5)
    raise last_error


def tab_reference(window_id, tab_id=None):
    tab = "active tab" if tab_id is None else f"tab id {int(tab_id)}"
    return f"{tab} of window id {int(window_id)}"


def prepare_vote_form(window_id, timeout, tab_id=None):
    source = PREPARE_SOURCE.read_text(encoding="utf-8")
    script = f'''tell application "Google Chrome"
    return execute {tab_reference(window_id, tab_id)} javascript {apple_string(source)}
end tell'''
    deadline = time.monotonic() + timeout
    last_message = "Trang chưa sẵn sàng."
    last_report = None
    last_report_at = 0
    while time.monotonic() < deadline:
        result = json.loads(run_applescript(script))
        if result["state"] == "ready":
            return result["ratings"]
        if result["state"] == "error":
            raise RuntimeError(result["message"])
        last_message = result["message"]
        now = time.monotonic()
        if last_message != last_report or now - last_report_at >= 5:
            elapsed = int(timeout - max(0, deadline - now))
            print(f"{last_message} ({elapsed} giây)", flush=True)
            last_report = last_message
            last_report_at = now
        time.sleep(0.25)
    raise RuntimeError(f"Hết thời gian chờ: {last_message}")


def submit_vote_form(window_id, timeout, tab_id=None):
    source = SUBMIT_SOURCE.read_text(encoding="utf-8")
    script = f'''tell application "Google Chrome"
    return execute {tab_reference(window_id, tab_id)} javascript {apple_string(source)}
end tell'''
    deadline = time.monotonic() + timeout
    last_message = "Đang chờ bạn xác minh CAPTCHA."
    while time.monotonic() < deadline:
        result = json.loads(run_applescript(script))
        if result["state"] == "clicked":
            return result["message"]
        if result["state"] == "error":
            raise RuntimeError(result["message"])
        last_message = result["message"]
        time.sleep(0.5)
    raise RuntimeError(f"Hết thời gian chờ, chưa bấm gửi: {last_message}")


def wait_vote_result(window_id, tab_id, timeout):
    source = RESULT_SOURCE.read_text(encoding="utf-8")
    script = f'''tell application "Google Chrome"
    return execute {tab_reference(window_id, tab_id)} javascript {apple_string(source)}
end tell'''
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = json.loads(run_applescript(script))
        if result["state"] == "success":
            return result["message"]
        if result["state"] == "error":
            raise RuntimeError(result["message"])
        time.sleep(0.5)
    raise RuntimeError("Đã bấm gửi nhưng chưa thấy trang báo thành công; giữ tab đang mở, không tự gửi lại.")


def close_vote_tab(window_id, tab_id):
    target = tab_reference(window_id, tab_id)
    result = run_applescript(f'''tell application "Google Chrome"
    if exists window id {int(window_id)} then
        if mode of window id {int(window_id)} is "incognito" then
            if exists {target} then
                if URL of {target} is {apple_string(URL)} then
                    close {target}
                    return "closed"
                end if
            end if
        end if
    end if
end tell
return "not-closed"''')
    if result != "closed":
        raise RuntimeError("Bình chọn thành công nhưng tab đã đổi trạng thái nên chưa đóng được.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Xem các bước, chưa mở Chrome.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--open-only", action="store_true", help="Chỉ mở trang, tự chọn sao và gửi.")
    mode.add_argument("--select-only", action="store_true", help="Tự chọn sao rồi dừng, bạn tự bấm gửi.")
    parser.add_argument("--timeout", type=float, default=45,
                        help="Thời gian chờ biểu mẫu, tính bằng giây (mặc định: 45).")
    parser.add_argument("--permission-timeout", type=float, default=180,
                        help="Thời gian chờ bật quyền Chrome, tính bằng giây (mặc định: 180).")
    parser.add_argument("--captcha-timeout", type=float, default=180,
                        help="Thời gian chờ bạn xác minh CAPTCHA, tính bằng giây (mặc định: 180).")
    parser.add_argument("--response-timeout", type=float, default=45,
                        help="Thời gian chờ trang báo thành công trước khi đóng tab (mặc định: 45 giây).")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout phải lớn hơn 0.")
    if args.permission_timeout <= 0:
        parser.error("--permission-timeout phải lớn hơn 0.")
    if args.captcha_timeout <= 0:
        parser.error("--captcha-timeout phải lớn hơn 0.")
    if args.response_timeout <= 0:
        parser.error("--response-timeout phải lớn hơn 0.")
    if args.dry_run:
        print(f"Mở Google Chrome trực tiếp, tạo cửa sổ ẩn danh và truy cập {URL}")
        if not args.open_only:
            print('Dùng Apple Events mở biểu mẫu "Bình chọn ngay" và chọn 5 sao cho tám mục.')
            print("Kiểm tra quyền trong Chrome thường trước; nếu thiếu, chờ bạn bật rồi tự tiếp tục.")
            if not args.select_only:
                print(f'Chờ bạn xác minh CAPTCHA tối đa {args.captcha_timeout:g} giây, rồi bấm nút gửi "Bình chọn ngay" một lần.')
                print("Chờ trang báo thành công rồi đóng đúng tab ẩn danh do script mở.")
        return 0
    if sys.platform != "darwin" or shutil.which("osascript") is None:
        parser.error("Script này dùng Chrome và Apple Events trên macOS.")

    try:
        if not args.open_only:
            ensure_javascript_permission(args.permission_timeout)
        window_id = open_window()
        print("Đã mở trang bằng Chrome ẩn danh trực tiếp.", flush=True)
        if args.open_only:
            return 0
        tab_id = int(run_applescript(f'''tell application "Google Chrome"
    return id of active tab of window id {window_id}
end tell'''))
        prepare_vote_form(window_id, args.timeout, tab_id)
        print("Đã chọn 5 sao cho đủ tám mục.", flush=True)
        if args.select_only:
            print("Bạn tự xác minh CAPTCHA và bấm nút gửi.")
            print("Cửa sổ Chrome vẫn mở sau khi script kết thúc.")
        else:
            print("Bạn chỉ cần xác minh CAPTCHA; script sẽ tự bấm Bình chọn ngay một lần.", flush=True)
            print(submit_vote_form(window_id, args.captcha_timeout, tab_id), flush=True)
            print("Đang chờ kết quả bình chọn...", flush=True)
            print(wait_vote_result(window_id, tab_id, args.response_timeout), flush=True)
            close_vote_tab(window_id, tab_id)
            print("Đã đóng tab bình chọn ẩn danh.", flush=True)
        return 0
    except RuntimeError as error:
        if "(12)" in str(error) and "JavaScript" in str(error):
            print(
                "Chrome vẫn chưa cho phép JavaScript từ Apple Events. Bật trong cửa sổ đang cần quyền:\n"
                "  View > Developer > Allow JavaScript from Apple Events\n"
                "rồi chạy lại script. Bật trong Chrome thường để giữ quyền cho lần sau;\n"
                "đóng hết cửa sổ ẩn danh cũ rồi mới tạo phiên ẩn danh mới.\n"
                "Chrome yêu cầu bạn trực tiếp bật tùy chọn này bằng menu.",
                file=sys.stderr,
            )
            return 2
        print(f"Chưa hoàn tất: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Không thể hoàn tất thao tác Chrome: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nĐã dừng; cửa sổ Chrome vẫn mở.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
