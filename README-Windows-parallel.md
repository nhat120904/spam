# Chạy nhiều phiên Chrome độc lập trên Windows

Yêu cầu Windows 10/11, Python 3.10 trở lên và Google Chrome đã cài.
Giải nén **toàn bộ** `thinh-liet-windows-parallel.zip`, mở PowerShell hoặc CMD
trong thư mục đã giải nén rồi chạy:

```powershell
py -3 -m pip install -r requirements-windows.txt
py -3 open_incognito_windows_parallel.py --workers 2
```

Nếu máy chỉ có lệnh `python`, thay `py -3` bằng `python` trong các lệnh trên.
Sau khi cài thư viện, có thể bấm đúp `run_windows_parallel.bat` để chạy hai worker.
Từ terminal có thể truyền tham số:

```powershell
.\run_windows_parallel.bat --workers 4 --captcha-timeout 300
```

Mỗi worker mở một tiến trình Chrome ẩn danh với hồ sơ và cổng DevTools riêng.
Cookies và dữ liệu phiên được tách giữa các worker; thao tác nhắm đúng ID tab,
không phụ thuộc cửa sổ đang active. Bản Windows **không cần bật Allow JavaScript
from Apple Events**. Chỉ cần Python và `websocket-client`; không cần cài
ChromeDriver, Selenium hay Playwright để chạy.

Mỗi worker chạy **một lượt**: mở trang, chọn đủ tám mục 5 sao, chờ bạn tự xác minh
CAPTCHA trong cửa sổ tương ứng (mặc định 180 giây), bấm gửi một lần và chờ kết quả
tối đa 45 giây. Chrome của worker tự đóng khi thành công, lỗi hoặc hết giờ.
Khi dùng chế độ mặc định, bạn chỉ xác minh CAPTCHA và để script bấm gửi.
Nhấn `Ctrl+C` trong terminal để dừng các worker và đóng các Chrome của lần chạy
hiện tại. Chrome cá nhân và các phiên do lần chạy khác mở không bị đóng.

Chọn sao rồi giữ các cửa sổ mở để bạn tự xác minh CAPTCHA và bấm gửi:

```powershell
py -3 open_incognito_windows_parallel.py --workers 2 --select-only
```

Chỉ mở trang trong các phiên riêng, không chọn sao hoặc gửi:

```powershell
py -3 open_incognito_windows_parallel.py --workers 2 --open-only
```

Hai chế độ thủ công giữ Chrome mở khi worker hoàn tất bình thường. Đóng các
cửa sổ đó trước khi chạy lại cùng nhóm worker. Script có khóa hồ sơ và kiểm tra
Chrome đang mở để tránh hai lần chạy cùng điều khiển một phiên.

Các tùy chọn:

| Tham số | Ý nghĩa |
|---|---|
| `--workers 4` | Số worker, mặc định 2; tăng số worker sẽ dùng thêm RAM/CPU. |
| `--timeout 90` | Chờ điều hướng và chờ biểu mẫu tối đa 90 giây mỗi bước. |
| `--captcha-timeout 300` | Chờ bạn xác minh CAPTCHA tối đa 300 giây ở mỗi worker. |
| `--response-timeout 90` | Chờ kết quả sau gửi tối đa 90 giây. |
| `--dry-run` | In cấu hình; không mở Chrome hoặc tạo hồ sơ. |
| `--chrome "C:\Program Files\Google\Chrome\Application\chrome.exe"` | Chỉ định Chrome khi không tự tìm thấy. |
| `--profiles-dir "D:\Chrome workers"` | Chọn thư mục hồ sơ khác. |

Hồ sơ mặc định: `%LOCALAPPDATA%\ThinhLietHelper\ChromeParallel\worker-1`,
`worker-2`, ... Hồ sơ Chrome thường cá nhân không được đọc hoặc sao chép.
Tách phiên Chrome không thay đổi IP mạng; mọi worker vẫn chịu giới hạn và kiểm
tra của website. Công cụ chờ CAPTCHA do bạn xác minh và không tự gửi lại khi kết
quả chưa rõ.

Khi gặp lỗi:

- **Thiếu thư viện**: chạy lại lệnh cài `requirements-windows.txt` bằng đúng Python
  dùng để chạy script.
- **Hồ sơ đang được worker khác sử dụng / Chrome vẫn mở**: dừng lần chạy đang dùng
  hồ sơ đó hoặc đóng cửa sổ được giữ mở từ chế độ thủ công, rồi chạy lại.
- **Không tìm thấy Chrome**: dùng `--chrome` với đường dẫn đầy đủ tới `chrome.exe`.
- **Tab không còn ở trang của trường**: kiểm tra URL hoặc trang lỗi trong Chrome;
  script dừng worker đó để tránh thao tác sai trang.
- **Chưa hoàn tất sau khi gửi**: kết quả chưa được xác nhận; script không tự bấm lại.

Bộ ZIP cần giữ cùng nhau: hai file Python `open_incognito_windows_parallel.py`,
`open_incognito_windows.py`, thư mục `src` với ba file JavaScript,
`requirements-windows.txt`, launcher `.bat` và hướng dẫn này.

Kiểm chứng được thực hiện trên macOS bằng Chrome/CDP thật với biểu mẫu mô phỏng,
không gửi bình chọn thật. Chưa chạy trực tiếp trên Windows, chưa xác nhận launcher
`.bat`, khóa `msvcrt` hoặc CAPTCHA thật trên Windows.
