# Bình chọn Thịnh Liệt bằng Chrome

Bản macOS chạy nhiều phiên Chrome độc lập: xem [hướng dẫn chạy song song](README-parallel.md) và dùng `python3 open_incognito_parallel.py --workers 2`.

## Bản Windows

Bản **chạy song song**: giải nén `thinh-liet-windows-parallel.zip`, cài thư viện rồi dùng `py -3 open_incognito_windows_parallel.py --workers 2` hoặc bấm đúp `run_windows_parallel.bat`. Mỗi worker có Chrome, hồ sơ và phiên ẩn danh riêng. Xem [hướng dẫn Windows song song](README-Windows-parallel.md).

Dùng `open_incognito_windows.py` với Python 3.10 trở lên và Google Chrome. Xem [hướng dẫn Windows](README-Windows.md). Giải nén đầy đủ `thinh-liet-windows.zip`, mở terminal trong thư mục đã giải nén rồi chạy:

```powershell
py -m pip install -r requirements-windows.txt
py open_incognito_windows.py
```

Sau khi cài thư viện, có thể bấm đúp `run_windows.bat`. Bản này mở Chrome ẩn danh bằng hồ sơ riêng cố định, chọn tám mục 5 sao, chờ bạn xác minh CAPTCHA tối đa **10 giây**, gửi một lần và đóng đúng tab khi thành công, có lỗi hoặc chưa hoàn tất/hết thời gian chờ. Có `--open-only` và `--select-only`; hai chế độ này vẫn giữ tab mở nếu hoàn tất bình thường để bạn thao tác tay. Đã kiểm thử qua DevTools thật với trang mô phỏng trên macOS; chưa kiểm chứng trực tiếp trên Windows hoặc với CAPTCHA thật của bản Windows.

## Mở Chrome ẩn danh, tự chọn 5 sao và bấm bình chọn (macOS)

Ngày 10/10/2026, người dùng báo CAPTCHA “Verification failed” sau khi bản Python chuyển sang Playwright để chọn sao. Trước đó bản chỉ mở Chrome trực tiếp hoạt động được. Phiên Playwright có khả năng gây lỗi; [Cloudflare không hỗ trợ Playwright để giải CAPTCHA thật](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/).

`open_incognito.py` hiện dùng Apple Events của macOS để mở cửa sổ Chrome ẩn danh trực tiếp, chọn sao và bấm gửi sau khi CAPTCHA được xác minh. Script đóng đúng tab bình chọn do nó mở khi thành công, khi có lỗi hoặc khi chưa hoàn tất/hết thời gian chờ. Script dùng thư viện chuẩn Python 3, không cần Playwright khi chạy.

Để tự chọn sao, bật **View > Developer > Allow JavaScript from Apple Events** trong **cửa sổ Chrome thường, cùng hồ sơ Chrome**. Bật trong cửa sổ ẩn danh chỉ giữ quyền trong phiên ẩn danh đó: [Chromium lưu thay đổi của hồ sơ ẩn danh trong bộ nhớ](https://github.com/chromium/chromium/blob/main/components/sync_preferences/pref_service_syncable.cc), và [quyền Apple Events không thuộc danh sách tùy chọn được lưu lâu dài từ ẩn danh](https://github.com/chromium/chromium/blob/main/chrome/browser/prefs/pref_service_incognito_allowlist.cc).

Nếu đã bật/tắt quyền trong ẩn danh trước đó, hãy đóng hết cửa sổ ẩn danh cũ, bật quyền ở Chrome thường, rồi mới tạo phiên ẩn danh mới. Quyền được lưu theo hồ sơ Chrome; hồ sơ khác có tùy chọn riêng.

Tùy chọn này cho phép ứng dụng trên máy chạy JavaScript trong tab Chrome; Chrome hiện báo lỗi `12` nếu chưa bật. [Chrome yêu cầu thao tác trực tiếp của người dùng để bật quyền](https://github.com/chromium/chromium/blob/main/chrome/browser/ui/browser_commands_mac.mm). Chạy:

```sh
python3 /Users/nhatcuong/code_project/chi-tuyet/open_incognito.py
```

Script kiểm tra quyền trong một cửa sổ Chrome thường trống trước. Nếu chưa bật, script in hướng dẫn trong terminal và chờ tối đa 180 giây. Bật quyền ngay trong cửa sổ đó, script sẽ tự tiếp tục, không cần chạy lại. Sau đó script mở Chrome ẩn danh, mở biểu mẫu bằng nút **Bình chọn ngay**, chọn 5 sao cho cả tám tiêu chí và chờ CAPTCHA tối đa **10 giây**. Bạn chỉ cần xác minh CAPTCHA nếu trang yêu cầu; script kiểm tra lại đúng trường, đủ tám mục 5 sao và còn lượt, rồi tự bấm nút **Bình chọn ngay** trong biểu mẫu một lần. Script không tự xác minh CAPTCHA hoặc bấm gửi lại. Nếu hết thời gian chờ CAPTCHA thì chưa bấm gửi và tab ẩn danh được đóng tự động.

Để tránh bị kẹt khi trang tải chậm, bước mở biểu mẫu chờ nội dung trang và jQuery khởi tạo xong. Nếu lần bấm mở biểu mẫu chưa có tác dụng, script thử lại sau một giây khi popup vẫn đóng, trong thời gian `--timeout`. Terminal hiện bước đang chờ và thời gian đã chờ mỗi 5 giây. Việc thử lại này chỉ áp dụng cho nút mở biểu mẫu; nút gửi vẫn chỉ được bấm một lần.

Sau khi bấm, script chờ tối đa 45 giây để thông báo thành công `#vote-popup-success` của trang hiện ra, rồi đóng đúng tab ẩn danh ban đầu bằng ID tab. Nếu đó là tab cuối thì cửa sổ ẩn danh cũng đóng. Các tab khác được giữ lại. Nếu trang báo hết lượt, có lỗi hoặc chưa thấy thành công sau thời gian chờ, script cũng đóng đúng tab và không tự gửi lại. Nhấn Ctrl+C trong luồng tự động cũng đóng tab trước khi thoát. Hai chế độ `--open-only` và `--select-only` giữ tab mở khi hoàn tất bình thường để thao tác tay; lỗi trong `--select-only` vẫn đóng tab. Nếu Chrome không nhận được lệnh đóng, terminal sẽ báo rõ. Cửa sổ kiểm tra quyền được đóng khi xong nếu bạn chưa mở thêm tab hoặc điều hướng sang trang khác. Nếu hết thời gian chờ quyền, script báo mã thoát `2`.

Để chỉ chọn đủ 5 sao rồi tự bấm gửi như bản trước:

```sh
python3 /Users/nhatcuong/code_project/chi-tuyet/open_incognito.py --select-only
```

Để chỉ mở trang bằng Chrome trực tiếp, không cần quyền JavaScript:

```sh
python3 /Users/nhatcuong/code_project/chi-tuyet/open_incognito.py --open-only
```

Thêm `--dry-run` để xem các bước; `--timeout 90` để chờ biểu mẫu tối đa 90 giây; `--permission-timeout 300` để chờ bật quyền tối đa 5 phút; `--captcha-timeout 10` để chờ bạn xác minh CAPTCHA tối đa 10 giây (mặc định); `--response-timeout 90` để chờ trang báo kết quả tối đa 90 giây trước khi đóng tab. Nếu không muốn bật quyền Apple Events, dùng dấu trang trong `chrome-helper.html` theo hướng dẫn bên dưới để chọn sao bằng một lần bấm.

Kiểm thử mã chọn sao với biểu mẫu mô phỏng (Playwright chỉ dùng cho kiểm thử):

```sh
cd /Users/nhatcuong/code_project/chi-tuyet
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s test -p 'test_*.py' -v
```

Báo cáo `runtime/reports/python-incognito-five-stars.*` ghi nhận bản Playwright cũ, không xác nhận CAPTCHA hoạt động. Sau khi người dùng bật quyền JavaScript ngày 10/10/2026, bản Apple Events chạy thành công trên trang thật: biểu mẫu đang mở, cả tám giá trị bằng `5`, Chrome báo `navigator.webdriver === false`. Người dùng xác nhận CAPTCHA đã xác minh thành công trong cửa sổ này. Báo cáo tại `runtime/reports/native-chrome-five-stars.json` ghi nhận bản chỉ chọn sao trước khi thêm bước tự bấm gửi; kết quả CAPTCHA dựa trên xác nhận của người dùng vì công cụ xem giao diện gặp lỗi `timeoutReached`.

Bước tự bấm gửi và đóng tab được kiểm thử bằng biểu mẫu mô phỏng trong Chrome: chờ CAPTCHA, bấm đúng một lần, đóng tab sau thông báo thành công, khi CAPTCHA hết giờ, khi có lỗi hoặc chưa rõ kết quả, và giữ các tab khác. Thao tác đóng đúng ID tab cũng đã được kiểm tra bằng Chrome thật với một tab khác trong cùng cửa sổ. Chưa gửi phiếu lên trang thật để kiểm tra bước mới.

## Dùng Chrome bình thường

Ngày 09/10/2026, người dùng xác nhận CAPTCHA thành công trong Chrome tự mở, nhưng báo “Xác minh thất bại” trong cửa sổ Chrome do tool mở. [Cloudflare không hỗ trợ trình duyệt do Playwright điều khiển để hoàn tất CAPTCHA trên trang thật](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/). Kiểm thử giả lập đạt không chứng minh chế độ tự gửi hoạt động trên trang thật.

Bản hỗ trợ `chrome-helper.html` chạy ngay trong Chrome bình thường và chỉ chọn 5 sao. Trên macOS, mở trang cài dấu trang bằng:

```sh
cd /Users/nhatcuong/code_project/chi-tuyet
npm run helper
```

1. Dừng lệnh `vote`/`vote:api` đang chạy bằng `Ctrl+C`.
2. Trong trang vừa mở bằng Chrome, nhấn `Cmd+Shift+B` để hiện thanh dấu trang. Kéo nút **★ Thịnh Liệt · chọn 5 sao** lên thanh dấu trang.
3. Tự mở trang bình chọn của trường trong Chrome bình thường, rồi bấm dấu trang đã lưu. Công cụ mở biểu mẫu và chọn 5 sao cho tám tiêu chí.
4. Bạn tự xác minh CAPTCHA và bấm **Bình chọn ngay** nếu còn lượt. Kiểm tra kết quả trên trang.

Dấu trang kiểm tra đúng địa chỉ trang, mã trường 1098, tám tiêu chí và số lượt còn lại. Nó không đọc/chuyển CAPTCHA, không tạo phiên mới, không POST hoặc tự bấm gửi. CAPTCHA và kết quả gửi thật của bản này chưa được kiểm chứng; người dùng cần thử trên Chrome của mình. Nếu trình duyệt chặn mã dấu trang hoặc cấu trúc trang thay đổi, dùng trực tiếp các nút của trang.

## Script tự động cũ (gặp lỗi CAPTCHA trên trang thật)

Script terminal có các chế độ kiểm tra, gửi **một lượt** qua API trực tiếp hoặc nút bình chọn trên trang. Mặc định chỉ kiểm tra. Node.js 22 trở lên và Google Chrome là bắt buộc. Việc tự bấm xác minh trong cửa sổ do script mở vẫn có thể bị Cloudflare từ chối; tăng thời gian chờ hay đổi sang API không khắc phục được việc thiếu CAPTCHA hợp lệ.

```sh
cd /Users/nhatcuong/code_project/chi-tuyet
npm install
npm run inspect
```

Gửi một lượt bằng **POST API trực tiếp**:

```sh
npm run vote:api
```

Chế độ này mở biểu mẫu để xác minh CAPTCHA, rồi Node gửi POST thẳng tới API bằng phiên của hồ sơ Chrome riêng. Không bấm các ngôi sao hoặc nút bình chọn: tám giá trị 5 được ghi vào payload. Không tự thử lại hoặc theo redirect. Kết quả xuất hiện trong terminal/JSON; popup của trang không được cập nhật thành công bởi chế độ API.

Gửi một lượt bằng nút của trang:

```sh
npm run vote
```

Nếu CAPTCHA yêu cầu tương tác, hãy tự xác minh trong cửa sổ Chrome vừa mở; **chỉ xác minh CAPTCHA, không tự bấm nút bình chọn**. Mặc định chờ tối đa 180 giây. Chrome sẽ đóng khi hoàn tất. Có thể đổi thời gian chờ:

```sh
npm run vote:api -- --captcha-timeout 240 --response-timeout 60
```

Chrome dùng hồ sơ riêng cố định tại `runtime/chrome-profile`, giữ phiên giữa các lần chạy. Đây là Chrome thật, nhưng phiên này khác tab Chrome cá nhân bạn đã bình chọn thành công. Script không đọc hoặc sao chép hồ sơ cá nhân. Không chạy hai bản script cùng lúc.

API quan sát được là `POST https://treemvietnam.net.vn/truong-hoc-hanh-phuc/vote`. Payload có mã trường `1098`, tám giá trị `rating[]=5` và CAPTCHA hiện tại, mã hóa `application/x-www-form-urlencoded`. Hai chế độ dùng cùng các trường này; báo cáo không lưu CAPTCHA, cookie, header hoặc phản hồi lạ nguyên văn.

Gọi API vẫn cần CAPTCHA: [Cloudflare quy định token dùng một lần và hết hạn sau 5 phút](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/). Gửi lại token cũ không tạo lượt mới hợp lệ. Script không tạo token giả, giải CAPTCHA hoặc gọi Siteverify thay máy chủ của trang.

| Kết quả | Ý nghĩa và hành động |
|---|---|
| HTTP 200, mã `1` | Máy chủ báo thành công. |
| Hết lượt trên giao diện hoặc mã `0` | Dừng; chờ lượt tiếp theo. |
| Mã `2` | Trang yêu cầu cập nhật số điện thoại; cần hoàn tất quy trình trên trang. |
| Mã `3` | Máy chủ từ chối CAPTCHA, kể cả khi widget đã hiện thành công. |
| CAPTCHA hết thời gian chờ | Script không bấm gửi. |
| HTTP 500, lỗi mạng, phản hồi lạ, timeout | Chưa rõ lượt có được ghi nhận hay không; không tự thử lại. |

Báo cáo JSON và ảnh nằm trong `runtime/reports/`. Mã thoát `0`: kiểm tra xong hoặc API báo thành công; `2`: dừng/không gửi/thông tin bị từ chối; `4`: đã bắt đầu gửi nhưng kết quả chưa rõ.

Trước khi bấm gửi, script lưu trạng thái tại `runtime/last-attempt.json`. Sau thành công, hết lượt, phản hồi chưa rõ hoặc lần chạy bị gián đoạn ở bước gửi, script chặn gửi lại trong 24 giờ. Trạng thái chỉ biết lượt do script này gửi; bạn vẫn cần tuân thủ giới hạn nếu đã bình chọn bằng điện thoại hoặc Chrome cá nhân. Chế độ kiểm tra vẫn chạy được.

Theo [thông báo mở bình chọn ngày 05/10/2026 của ban tổ chức](https://treemvietnam.net.vn/bat-dau-mo-cong-binh-chon-truong-hoc-hanh-phuc-2026-tu-7h-sang-nay-d10208.html), mỗi số điện thoại/email được một lượt cho mỗi trường trong 24 giờ. Giao diện hiện tại thông báo một bài dự thi mỗi ngày. Công cụ không tạo 10.000 phiếu, danh tính giả hoặc bỏ qua CAPTCHA/giới hạn.

Lỗi loading đã quan sát: trình duyệt nhúng có yêu cầu không hoàn tất và HTTP 500; Edge có phản hồi `3` và HTTP 500. Handler AJAX của trang không đặt timeout; nhánh lỗi bỏ lớp loading nhưng giữ nền che trang. Chưa xác định nguyên nhân phía máy chủ, và chưa đọc được tab Chrome cá nhân đang hoạt động. Chrome chạy bằng script cũng có thể bị CAPTCHA từ chối.

Kiểm tra thật ngày 08/10/2026: script mở Chrome 155.0.8059.39, xác nhận trường 1098 và tám tiêu chí. Không gửi yêu cầu bình chọn. Sau 30 giây CAPTCHA hiện ô “Verify you are human”; chưa có token vì cần người dùng xác minh. Báo cáo: `runtime/reports/chrome-captcha-check.json`. Chưa xác nhận API trực tiếp ghi nhận phiếu trên trang thật.

Kiểm thử trên trang thử localhost bằng Chrome:

```sh
npm test
```

Kiểm thử không gửi phiếu lên trang thật. [Playwright hỗ trợ Chrome qua channel `chrome`](https://playwright.dev/docs/browsers#google-chrome--microsoft-edge) và [yêu cầu hồ sơ riêng khi dùng persistent context với Chrome](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context).

Trang bình chọn thử tương tác trên localhost có 8 tiêu chí, bộ đếm và các tình huống thành công/thất bại:

```sh
npm run lab
# Mở http://127.0.0.1:3000
```

Trong terminal khác, gửi một phiếu bằng HTTP thuần, chạy một lượt qua giao diện hoặc thử tải 10.000 phiếu:

```sh
npm run lab:vote:http
npm run lab:vote
npm run lab:load
```

Script thử tải chỉ gọi loopback và dùng token mô phỏng cục bộ. Chế độ Turnstile riêng dùng khóa test chính thức; không tích hợp Turnstile-Solver hoặc kiểm thử vượt CAPTCHA thật. Xem [hướng dẫn đầy đủ](lab/README.md). Báo cáo thử tải được lưu tại `runtime/lab/load-report.json`.
