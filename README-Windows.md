# Chạy trên Windows

Cần Windows 10/11, Python 3.10 trở lên và Google Chrome. Giải nén toàn bộ gói vào một thư mục, giữ nguyên thư mục `src` bên cạnh `open_incognito_windows.py`.

## Cài và chạy

Mở PowerShell hoặc Command Prompt trong thư mục đã giải nén. Cài thư viện một lần:

```powershell
py -m pip install -r requirements-windows.txt
```

Sau đó chạy:

```powershell
py open_incognito_windows.py
```

Hoặc bấm đúp `run_windows.bat` sau khi cài thư viện. Nếu máy không có lệnh `py`, thay `py` bằng `python` trong các lệnh trên; file `.bat` cũng thử `python` khi không tìm thấy `py`.

Script mở Chrome ẩn danh, mở biểu mẫu **Bình chọn ngay**, chọn 5 sao cho đủ tám mục, chờ bạn xác minh CAPTCHA tối đa **10 giây**, rồi bấm nút gửi một lần. Script đóng đúng tab bình chọn khi thành công, khi có lỗi, khi báo chưa hoàn tất hoặc khi hết thời gian chờ. Nếu CAPTCHA chưa xong sau 10 giây thì đóng tab và chưa bấm gửi. Sau khi gửi, thời gian chờ kết quả vẫn mặc định 45 giây. Không tự thử gửi lại.

Bạn chỉ cần xử lý CAPTCHA; đợi script bấm nút gửi để tránh gửi hai lần.

## Tùy chọn

```powershell
# Chỉ chọn sao; bạn tự xác minh CAPTCHA và tự bấm gửi
py open_incognito_windows.py --select-only

# Chỉ mở Chrome ẩn danh, bạn thao tác toàn bộ trên trang
py open_incognito_windows.py --open-only

# Chờ biểu mẫu 90 giây, CAPTCHA 10 giây và kết quả 90 giây
py open_incognito_windows.py --timeout 90 --captcha-timeout 10 --response-timeout 90

# Xem các bước, chưa mở trình duyệt
py open_incognito_windows.py --dry-run

# Chrome cài ở vị trí khác
py open_incognito_windows.py --chrome "D:\Apps\Chrome\Application\chrome.exe"
```

Các tùy chọn cũng dùng được với `run_windows.bat`, ví dụ `run_windows.bat --select-only` trong Command Prompt.

## Chrome và CAPTCHA

Bản Windows điều khiển Chrome qua DevTools tại `127.0.0.1`. Chrome dùng hồ sơ riêng cố định ở `%LOCALAPPDATA%\ThinhLietHelper\ChromeProfile`; đây là yêu cầu của [Chrome với remote debugging từ phiên bản 136](https://developer.chrome.com/blog/remote-debugging-port). Không cần bật quyền Apple Events của macOS. Script không dùng Selenium, Playwright hoặc ChromeDriver khi chạy.

Nếu bản trước còn đang chạy, script sẽ báo và dừng. Hai chế độ `--open-only` và `--select-only` vẫn giữ tab mở khi hoàn tất bình thường để bạn thao tác tay. Nếu `--select-only` gặp lỗi thì cũng đóng tab. Đóng cửa sổ còn mở của công cụ trước khi chạy lại. Chrome cá nhân và các tab khác được giữ nguyên. Nếu Chrome mất kết nối khiến lệnh đóng tab thất bại, terminal sẽ báo rõ.

CAPTCHA thật trên Windows chưa được kiểm chứng. Cách điều khiển này khác bản macOS; việc Chrome mở được và chọn sao thành công không đảm bảo Cloudflare chấp nhận phiên. Nếu widget hiện **Verification failed**, không tiếp tục bấm gửi; dùng `--open-only` để thao tác trực tiếp. Script không tự giải CAPTCHA hoặc thay đổi cơ chế xác minh của trang.

## Phạm vi đã kiểm thử

Đã kiểm thử kết nối DevTools thật trong Chrome trên macOS với biểu mẫu mô phỏng: chọn đủ tám mục, chờ CAPTCHA, gửi đúng một lần, đóng đúng tab sau thành công, khi CAPTCHA hết giờ, khi có lỗi hoặc chưa rõ kết quả; giữ các tab khác. Kiểm thử không gửi phiếu tới website thật. Chưa chạy trực tiếp trên Windows hoặc xác nhận CAPTCHA thật trên Windows.

Mã thoát: `0` hoàn tất, `1` lỗi hoặc hết thời gian chờ, `2` tham số không hợp lệ, `130` người dùng dừng bằng Ctrl+C. Ctrl+C cũng đóng tab bình chọn do script quản lý trước khi thoát.
