# Chrome ẩn danh chạy song song trên macOS

`open_incognito_parallel.py` là lệnh riêng. Mỗi worker chạy một lượt trong một tiến trình Chrome, một thư mục dữ liệu và một cửa sổ ẩn danh riêng. Lệnh dùng thư viện chuẩn Python 3 và Apple Events, không cần Playwright khi chạy.

Chạy hai worker:

```sh
cd /Users/nhatcuong/code_project/chi-tuyet
python3 open_incognito_parallel.py --workers 2
```

Đổi `2` thành số phiên cần chạy. Mỗi phiên Chrome tiêu thụ RAM và CPU riêng; nên bắt đầu với hai phiên.

## Thiết lập lần đầu

Mỗi worker dùng hồ sơ cố định trong `runtime/chrome-parallel/worker-1`, `worker-2`, ... Các hồ sơ này độc lập với Chrome cá nhân và độc lập với nhau. Cookie và dữ liệu của cửa sổ ẩn danh nằm trong phiên riêng của worker.

Lần đầu, script mở Chrome thường của từng worker để kiểm tra quyền. Trong từng cửa sổ đó, bật:

**View > Developer > Allow JavaScript from Apple Events**

Script chờ tối đa 180 giây và tự tiếp tục sau khi bạn bật. Quyền được giữ cho lần chạy tiếp theo trong hồ sơ worker tương ứng. Nếu macOS hỏi quyền điều khiển Chrome, cho phép ứng dụng/terminal đang chạy Python điều khiển Chrome.

Sau đó, từng worker mở trang bằng Chrome ẩn danh, chọn tám mục 5 sao và chờ bạn xác minh CAPTCHA trong chính cửa sổ đó. Mặc định thời gian chờ CAPTCHA là 60 giây tính riêng từ khi worker đã chọn đủ sao và bắt đầu bước chờ CAPTCHA. Nếu hết thời gian mà CAPTCHA chưa xong, worker đó báo lỗi và đóng Chrome của mình. CAPTCHA vẫn do bạn xác minh; mỗi worker chỉ bấm gửi một lần, không tự gửi lại khi lỗi hoặc chưa rõ kết quả. Có thể đổi mốc này bằng `--captcha-timeout`.

Script điều khiển theo **PID của Chrome + ID cửa sổ + ID tab**. Chuyển cửa sổ đang active không làm các worker điều khiển lẫn nhau.

Khi tab mới còn ở `chrome://newtab/` hoặc `about:blank`, script chờ trang tải trong thời gian `--timeout`. Đây là trạng thái chuyển tiếp của Chrome, không phải lỗi quyền Apple Events. Quyền Allow được lưu theo từng hồ sơ worker; không cần bật lại mỗi lần chạy nếu vẫn dùng cùng hồ sơ.

Sau khi đã bấm gửi, nếu Apple Events tạm thời hết giờ hoặc `osascript` bị ngắt, script thử **đọc lại kết quả tối đa hai lần** trong thời gian `--response-timeout` còn lại. Bước này không bấm gửi lại. Lỗi quyền hoặc tab không còn tồn tại vẫn dừng ngay. Nếu vẫn chưa đọc được kết quả, log báo chưa hoàn tất; không thể từ đó kết luận máy chủ chưa nhận bình chọn. Log điều khiển có mã thoát/tín hiệu, PID Chrome và thao tác để chẩn đoán khi có lỗi.

Trước khi gửi, script đối chiếu token trong ô của biểu mẫu với `getResponse` của đúng widget bình chọn và biến callback `captcha1Response` mà website thực sự dùng; widget phải còn hạn. Có dữ liệu trong ô CAPTCHA chưa đủ để bấm gửi. Nếu không đọc được trạng thái này, script không gửi. CAPTCHA vẫn do Turnstile và người dùng hoàn tất; kiểm tra ở trình duyệt không thay thế xác thực của máy chủ.

Website có thể từ chối CAPTCHA sau gửi bằng thông báo **“Vui lòng xác minh mã Captcha!”**. Script hiển thị nguyên thông báo này trong trang dưới dạng không chặn JavaScript và ghi nhận lỗi CAPTCHA rõ ràng, thay vì để hộp thoại `alert` khóa Apple Events đến lỗi `-1712`. Cách xử lý tương tự áp dụng cho hai thông báo bình chọn đã biết: chưa xác minh CAPTCHA và yêu cầu cập nhật số điện thoại. Các thông báo khác của website vẫn giữ nguyên hộp thoại. Worker dừng, đóng Chrome và không tự gửi lại khi website báo lỗi; tăng timeout không bảo đảm máy chủ sẽ chấp nhận CAPTCHA.

## Các chế độ

```sh
# Xem cấu hình, không mở Chrome và không tạo hồ sơ.
python3 open_incognito_parallel.py --workers 3 --dry-run

# Chỉ mở các trang để thao tác tay, giữ Chrome mở.
python3 open_incognito_parallel.py --workers 2 --open-only

# Tự chọn sao, giữ Chrome mở để bạn tự xác minh CAPTCHA và gửi.
python3 open_incognito_parallel.py --workers 2 --select-only

# Tăng thời gian chờ CAPTCHA khi cần chuyển giữa nhiều cửa sổ.
python3 open_incognito_parallel.py --workers 3 --captcha-timeout 300

# Dùng một nhóm hồ sơ worker khác.
python3 open_incognito_parallel.py --workers 2 --profiles-dir runtime/chrome-parallel-other
```

Các tùy chọn khác: `--timeout` (biểu mẫu, mặc định 45 giây), `--permission-timeout` (quyền, 180 giây), `--response-timeout` (kết quả, 60 giây tính từ sau khi bấm gửi), và `--chrome` (đường dẫn file thực thi Chrome nếu cài ở nơi khác). Xem `--help` để biết đầy đủ.

## Đóng phiên và chạy lại

Ở chế độ tự động, worker đóng **tiến trình Chrome riêng do nó tạo** khi hoàn tất, có lỗi hoặc hết giờ. Ctrl+C yêu cầu tất cả worker dừng và đóng Chrome của mình; không đóng Chrome cá nhân. Vì toàn bộ tiến trình worker sẽ được đóng, hãy dùng Chrome cá nhân cho các tab khác.

`--open-only` và `--select-only` giữ Chrome mở khi hoàn tất bình thường. Đóng Chrome của các worker đó trước khi dùng lại cùng nhóm hồ sơ; script sẽ từ chối nếu hồ sơ còn có worker hoặc Chrome đang sử dụng. Hồ sơ được giữ trên đĩa để lưu quyền Apple Events. Lần chạy tự động tiếp theo mở phiên ẩn danh mới.

Để tự xử lý Chrome còn mở từ lượt trước, thêm `--restart-workers` vào lệnh chạy:

```sh
# Đóng phiên Chrome cũ của worker 1–8 rồi chạy lượt mới.
python3 open_incognito_parallel.py --workers 8 --restart-workers

# Có thể kết hợp với chế độ thao tác tay.
python3 open_incognito_parallel.py --workers 8 --restart-workers --select-only

# Chỉ đóng phiên cũ của worker 1–8, không mở trang hoặc gửi bình chọn.
python3 open_incognito_parallel.py --workers 8 --close-workers

# Xem nhóm hồ sơ cần dọn, không đóng Chrome.
python3 open_incognito_parallel.py --workers 8 --close-workers --dry-run
```

Hai tùy chọn áp dụng cho worker `1` đến `--workers` trong `--profiles-dir` đang chọn. `--restart-workers` sẽ đóng các tab của phiên worker cũ, nên thao tác chưa gửi trong phiên đó sẽ mất. Chrome mới vẫn dùng hồ sơ đã lưu quyền Allow.

Trước khi đóng, script đối chiếu PID, đường dẫn Chrome, đường dẫn hồ sơ và thời điểm khởi động đã lưu. Hồ sơ từ phiên bản cũ chỉ lưu PID được kiểm tra bằng đường dẫn Chrome và hồ sơ. PID đã được cấp lại cho tiến trình khác được bỏ qua và dọn khỏi thông tin sở hữu. Khi Chrome do lượt chạy hiện tại kết thúc bình thường, script cũng xóa thông tin PID cũ.

Nếu một lệnh khác vẫn giữ khóa hồ sơ, cả hai tùy chọn đều từ chối can thiệp; hãy dừng lệnh đó bằng Ctrl+C tại terminal của nó. Chrome nhận SIGTERM và các tiến trình con đúng hồ sơ cũng được dọn. Nếu Chrome cũ không đóng sau 5 giây, script xác minh lại PID rồi gửi SIGKILL và chờ thêm tối đa 10 giây. Nếu vẫn chưa đóng, script giữ thông tin hồ sơ, báo lỗi và chưa mở phiên thay thế. Tùy chọn không xóa hồ sơ, và không đóng Chrome cá nhân hoặc Chrome của nhóm hồ sơ khác. Khi dùng lại nhóm hồ sơ riêng, truyền cùng `--profiles-dir` và `--chrome` nếu đã tùy chỉnh.

Renderer có thể còn chạy sau khi Chrome cha bị ngắt đột ngột, dù PID cha hoặc file sở hữu đã mất. Khi dọn hoặc mở lại hồ sơ, script tìm helper đã mất tiến trình cha, kiểm tra đúng đường dẫn Chrome và `--user-data-dir`, rồi dọn chúng. Khi đóng phiên đang sở hữu, script cũng dọn helper cùng hồ sơ. Tiến trình không xác minh được hồ sơ không bị đóng theo tên chung.

## Chạy nhiều lượt liên tiếp

Nên dùng thời gian chờ của script thay cho `perl -e 'alarm 30; exec @ARGV'`. Mốc CAPTCHA 60 giây áp dụng riêng cho từng worker sau khi chọn sao; bước tải biểu mẫu có thời gian chờ riêng, bước chờ kết quả có tối đa 60 giây tính từ sau khi bấm gửi. Script không tự đặt alarm cho toàn bộ lượt chạy. Tăng các mốc này không thay đổi hoặc hủy alarm do lệnh bên ngoài đặt; hãy chạy trực tiếp bằng Python như ví dụ bên dưới.

Nếu vẫn bọc bằng Perl `alarm 30`, SIGALRM đến sau 30 giây kể từ khi Perl đặt alarm, tính cả khởi động Chrome, tải trang, CAPTCHA và chờ kết quả, miễn là tiến trình còn chạy. Mỗi lượt trong vòng lặp đặt lại một alarm mới. Bản mới nhận SIGALRM/SIGTERM để dừng worker và dọn phiên rồi trả mã 130; việc dọn có thể kéo dài quá mốc alarm. SIGKILL không cho Python chạy bước dọn, nhưng lượt tiếp theo vẫn có thể dọn helper mồ côi bằng thông tin hồ sơ.

Ví dụ chạy tối đa 10 lượt với hai worker, dừng vòng lặp khi một lượt lỗi hoặc bị hủy:

```sh
for i in {1..10}; do
    echo "Running $i/10"
    python3 /Users/nhatcuong/code_project/chi-tuyet/open_incognito_parallel.py \
        --workers 2 --restart-workers || break
done
```

Mỗi lượt vẫn cần bạn tự xác minh CAPTCHA. Tăng số worker sau khi theo dõi RAM và CPU; vòng lặp không tự lặp lại một lượt lỗi hoặc chưa rõ kết quả.

Log có tiền tố `[Worker N]`. Mã thoát `0`: tất cả worker hoàn tất; `1`: ít nhất một worker lỗi/chưa hoàn tất; `2`: cấu hình hoặc môi trường không hợp lệ; `130`: dừng bằng Ctrl+C, SIGTERM hoặc SIGALRM. Một worker lỗi không dừng các worker còn lại.

Tách phiên chỉ tách dữ liệu trình duyệt. Các phiên vẫn dùng kết nối mạng của máy và chịu quy tắc, giới hạn bình chọn phía website.

## Kiểm thử

Kiểm thử thông thường:

```sh
.venv/bin/python -m unittest discover -s test -p 'test_parallel_incognito.py' -v
```

Kiểm thử bằng hai Chrome thật trên macOS (mở cửa sổ nhìn thấy được):

```sh
RUN_NATIVE_CHROME_TESTS=1 .venv/bin/python -m unittest discover -s test -p 'test_parallel_incognito.py' -v
```

Kiểm thử Chrome thật chỉ dùng hồ sơ tạm và trang localhost để kiểm tra PID riêng, cookie/localStorage độc lập và đóng một phiên không ảnh hưởng phiên còn lại. Không gửi bình chọn lên website thật. Kết quả kiểm thử cục bộ không xác nhận CAPTCHA thật hoặc website sẽ chấp nhận mọi phiên.
