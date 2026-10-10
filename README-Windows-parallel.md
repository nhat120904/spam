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

Với nhiều worker, script chỉ khởi động và tải biểu mẫu cho tối đa **2 Chrome
cùng lúc** để tránh dồn tải CPU/RAM. Khi biểu mẫu đã sẵn sàng, worker nhường
lượt khởi động và tiếp tục chờ CAPTCHA/kết quả song song với các worker khác.
`--workers 8` vẫn có đủ tám phiên riêng. Mỗi lệnh DevTools chờ tối đa 20 giây
(bản cũ chỉ chờ 5 giây); có thể điều chỉnh bằng `--cdp-timeout`.

Chrome được cấp cổng debug cụ thể riêng cho từng worker. Bản cũ dùng
`--remote-debugging-port=0`, khiến Chrome tự bật `navigator.webdriver`, khác
cách mở bằng Apple Events trên macOS. Đã thay cách cấp cổng và xác nhận người
dùng tự xác minh CAPTCHA thành công ở cả hai worker trên trang thật. Chi tiết
hành vi cổng `0` nằm trong
[mã nguồn Chromium](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/content/child/runtime_features.cc).

Mỗi worker chạy **một lượt**: mở trang, chọn đủ tám mục 5 sao, chờ bạn tự xác minh
CAPTCHA trong cửa sổ tương ứng (mặc định 180 giây), bấm gửi một lần và chờ kết quả
tối đa 45 giây. Chrome của worker tự đóng khi thành công, lỗi hoặc hết giờ.
Khi dùng chế độ mặc định, bạn chỉ xác minh CAPTCHA và để script bấm gửi.
Worker gặp lỗi CAPTCHA hoặc bị máy chủ từ chối sau khi gửi cũng tự đóng Chrome;
script không tự gửi thêm lần nữa. Trước khi in kết quả tổng, script dọn lại toàn
bộ phiên Chrome của lần chạy để không bỏ sót worker lỗi.
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
| `--cdp-timeout 30` | Chờ mỗi lệnh DevTools tối đa 30 giây, mặc định 20; hữu ích khi máy đang tải nặng. |
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
- **Chrome phản hồi ... quá ... giây**: lệnh DevTools bị timeout, khác với ngắt
  kết nối. Tăng `--cdp-timeout 30` hoặc `60` nếu máy đang tải nặng. Script không
  tự phát lại lệnh gửi chưa rõ kết quả.
- **Trang từ chối CAPTCHA sau khi gửi**: đây là phản hồi từ máy chủ website,
  khác với timeout Chrome. Website không cho biết lý do chi tiết trong phản hồi
  này. Token Turnstile chỉ dùng một lần và có hạn; trạng thái đã tích thành công
  ở widget chưa bảo đảm máy chủ chấp nhận. Script báo lỗi và đóng Chrome của
  worker đó; không tự gửi lại token cũ. Xem
  [xác minh phía máy chủ của Cloudflare](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/).
- **CAPTCHA / Verification failed**: script hiện mã lỗi Cloudflare từ console của
  đúng worker (không ghi token). Nhóm `300*`/`600*`, ví dụ `600010`, là challenge
  bị từ chối, có thể do phát hiện hành vi tự động; không có nghĩa là Python lỗi
  hay hết lượt bình chọn. Thử mở trang bằng Chrome thủ công để đối chiếu. Nếu
  trình duyệt thủ công cũng lỗi, kiểm tra Chrome đã cập nhật, ngày giờ Windows,
  tiện ích chặn nội dung và VPN/proxy đang dùng. Lỗi `200500` liên quan tải iframe;
  `110600`/`200100` liên quan hết giờ hoặc đồng hồ/cache; lỗi sitekey/domain cần
  quản trị website xử lý. Tra cứu tại
  [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/troubleshooting/client-side-errors/error-codes/).
  Script không tự giải CAPTCHA hoặc bảo đảm Cloudflare chấp nhận phiên tự động.

Bộ ZIP cần giữ cùng nhau: hai file Python `open_incognito_windows_parallel.py`,
`open_incognito_windows.py`, thư mục `src` với ba file JavaScript,
`requirements-windows.txt`, launcher `.bat` và hướng dẫn này.

Đã kiểm thử trực tiếp trên Windows bằng Chrome/CDP thật với biểu mẫu mô phỏng,
bao gồm hai worker riêng, khóa `msvcrt`, CAPTCHA lỗi, cổng bị chiếm và dọn dẹp
khi ngắt. 41 kiểm thử của hai bản Windows đã đạt, gồm tám worker hoạt động đồng
thời, CAPTCHA bị máy chủ từ chối và dọn hết phiên khi chỉ 6/8 worker thành công.
Đã mở trang thật/chọn sao thành công ở cả
tám worker với hồ sơ mới; chưa kiểm thử gửi bình chọn thật với tám worker.
Người dùng đã tự xác minh
CAPTCHA thật thành công ở cả hai worker sau bản sửa cấp cổng. Chưa xác nhận
launcher `.bat`; kiểm thử không gửi bình chọn thật.
