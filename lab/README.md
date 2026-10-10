# Vote Lab trên localhost

Trang thử mô phỏng biểu mẫu 8 tiêu chí và API bình chọn, chạy trên máy của bạn. Dữ liệu chỉ nằm trong bộ nhớ; khởi động lại hoặc bấm “Đặt lại bộ đếm” sẽ xóa dữ liệu thử. Server chỉ bind `127.0.0.1`.

Trong thư mục `/Users/nhatcuong/code_project/chi-tuyet`, chạy:

```sh
npm run lab
```

Mở [http://127.0.0.1:3000](http://127.0.0.1:3000). Trang có 8 hàng chấm sao và các kịch bản:

| Kịch bản | Phản hồi |
|---|---|
| Cho phép nhiều lượt để thử tải | `1`, tăng bộ đếm và tổng điểm |
| Một lượt mỗi phiên trong 24 giờ | Lượt đầu `1`, lượt tiếp theo `0` |
| Yêu cầu điện thoại | `2` |
| Từ chối CAPTCHA | `3` |
| Lỗi máy chủ | HTTP 500, body rỗng |

API: `POST /truong-hoc-hanh-phuc/vote`, form URL encoded với `thhp_id=1098`, tám giá trị `rating[]`, và `captcha`.

## Gửi một lượt bằng script hiện có

Gửi một phiếu bằng Node `fetch`, hoàn toàn không mở trình duyệt:

```sh
npm run lab:vote:http
```

Lệnh chỉ nhận cổng localhost (`--port 3000`), yêu cầu chế độ `open + mock`, lấy token mô phỏng từ API cục bộ rồi POST một phiếu. Báo cáo riêng tại `runtime/lab/vote-http.json`, không ghi đè báo cáo thử tải 10.000 lượt. Không dùng lệnh này để kiểm thử CAPTCHA production.

Giữ server đang chạy, mở terminal thứ hai:

```sh
npm run lab:vote
npm run lab:vote -- --api
```

Hai lệnh dùng lại `runVote()` của `src/vote.mjs`. Lệnh đầu thao tác giao diện, lệnh sau POST API trực tiếp. Mặc định Chrome chạy headless; thêm `--headed` để xem cửa sổ. Báo cáo/ảnh ở `runtime/lab/vote-3000-page.*` và `vote-3000-api.*`.

## Thử tải 10.000 lượt, hoàn toàn cục bộ

Chọn kịch bản “Cho phép nhiều lượt để thử tải”. Có thể đặt lại bộ đếm trước khi chạy:

```sh
npm run lab:load
```

Mặc định 10.000 lượt, 20 tác vụ song song; mỗi lượt xin token mô phỏng mới rồi POST API. Runner dùng một phiên cố định, không xoay danh tính. Token mock dùng một lần, hết hạn sau 5 phút. Báo cáo so sánh số phản hồi `1` với bộ đếm máy chủ và tổng điểm: 10.000 lượt chấm 8 × 5 phải thêm 400.000 điểm.

Đổi tham số:

```sh
npm run lab:load -- --count 1000 --concurrency 10
```

Runner chỉ nhận cổng số, luôn gọi `127.0.0.1`, kiểm tra đúng Vote Lab trước khi POST, không theo redirect. Nó chỉ chạy khi server đang ở chế độ `open + mock`; tối đa 10.000 lượt mỗi lần. Báo cáo ở `runtime/lab/load-report.json`. Không gửi yêu cầu nào đến website bình chọn thật.

## Kiểm tra widget Turnstile bằng khóa test chính thức

Chạy server thứ hai:

```sh
npm run lab:turnstile
```

Mở [http://127.0.0.1:3001](http://127.0.0.1:3001), hoặc chạy một lượt tự động:

```sh
npm run lab:vote -- --port 3001 --api
```

Chế độ này dùng widget Turnstile và gọi Siteverify với cặp khóa test “always passes” công khai của Cloudflare. Không cần tài khoản hoặc khóa production. Kết nối ngoài localhost chỉ phục vụ widget/Siteverify của Cloudflare. Không chạy 10.000 lượt qua dịch vụ này.

Đây là kiểm thử luồng nhận token và gửi phiếu bằng [khóa test chính thức](https://developers.cloudflare.com/turnstile/troubleshooting/testing/). Khóa test không dùng được để vượt CAPTCHA production. Lab không tích hợp repo Turnstile-Solver và không đo khả năng giải CAPTCHA thật.

## Kiểm thử tự động

Demo riêng cho mô hình HTTP API giữ Chrome headless và trả Turnstile test token: xem [README-token-demo.md](./README-token-demo.md), chạy `npm run lab:token-api`.

```sh
npm test
```

Các kiểm thử mặc định dùng API/Chrome cục bộ, không gọi dịch vụ CAPTCHA thật. Chế độ Turnstile được kiểm tra riêng bằng lệnh nêu trên.
