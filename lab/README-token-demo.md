# API lấy Turnstile test token bằng headless browser

Demo dùng một Chrome headless được giữ lại giữa các request. Mỗi request mở trang localhost với test key chính thức của Cloudflare, chờ callback trả dummy token, rồi gọi Siteverify bằng test secret để kiểm tra luồng. Không nhận URL, sitekey hoặc secret từ client.

## Chạy

Yêu cầu Node.js >= 22 và Google Chrome. Repo đã có dependency `playwright-core`.

```sh
cd /Users/nhatcuong/code_project/chi-tuyet
npm install
npm run lab:token-api
```

Server chỉ nghe tại `127.0.0.1:3002`. Đổi cổng bằng `npm run lab:token-api -- --port 3003`. Nếu cần chỉ định Chrome, đặt biến `CHROME_EXECUTABLE_PATH` trỏ đến executable trước khi chạy.

## Gọi bằng HTTP

```sh
curl -X POST http://127.0.0.1:3002/api/token
```

Hoặc Python `requests`:

Nếu môi trường Python chưa có thư viện này, cài bằng `python -m pip install requests`.

```python
import requests

response = requests.post("http://127.0.0.1:3002/api/token", timeout=90)
response.raise_for_status()
data = response.json()
print(data["token"])
print(data["verification"]["success"])
```

API không cần body; cũng chấp nhận JSON `{}`. Response gồm `token`, `verification`, `headless`, `browserInstance`, `browserLaunches` và `elapsedMs`. Gọi hai lần liên tiếp để thấy cùng `browserInstance` và `browserLaunches: 1`.

```sh
curl http://127.0.0.1:3002/health
```

Health cho biết browser đã khởi chạy chưa, worker đang bận không và số lượt hoàn tất. Worker xử lý từng request; request đến khi đang bận nhận HTTP 409. Lỗi widget/network trả HTTP 502, timeout trả 504, xác minh thất bại trả 422. Dừng bằng Ctrl+C để đóng cả server và Chrome.

## Bằng chứng của lượt gần nhất

- `runtime/token-demo/latest-response.json`: response đầy đủ.
- `runtime/token-demo/latest-widget.png`: ảnh trang test trong Chrome headless.

## Phạm vi của test key

Cloudflare test key trả dummy token; không bảo đảm token khác nhau giữa các lượt. `requestId` là ID của request, không phải CAPTCHA token. Test secret “always passes” có thể chấp nhận lại cùng dummy token; demo không kiểm chứng tính dùng một lần hoặc thời hạn của production token. Token test bị production secret từ chối. Demo không mô phỏng khả năng vượt CAPTCHA thật hoặc giới hạn trên website khác.

Widget dùng key công khai `1x00000000000000000000AA`; Siteverify dùng test secret công khai `1x0000000000000000000000000000000AA`. Kết nối ngoài localhost chỉ đến `https://challenges.cloudflare.com` để tải widget và gọi Siteverify.

[Tài liệu kiểm thử Cloudflare](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)

## Kiểm thử

```sh
npm test
```

Suite mặc định kiểm tra HTTP validation cục bộ, không gọi Cloudflare. Kiểm tra end-to-end thật bằng request `curl` ở trên.
