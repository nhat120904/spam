# Bản Windows chạy nhiều phiên Chrome

Người dùng đã yêu cầu bản Windows có cùng cách dùng `--workers` với bản macOS.

Thiết kế: file mới `open_incognito_windows_parallel.py`, dùng giao thức CDP của
bản Windows hiện có. Mỗi worker sở hữu một tiến trình Chrome, user-data-dir,
cổng DevTools và target riêng; không phụ thuộc cửa sổ đang active. Khóa hồ sơ
ngăn hai lần chạy dùng chung worker. Mỗi worker chạy một lượt; CAPTCHA vẫn do
người dùng xác minh. Chế độ mặc định đóng Chrome của worker sau thành công/lỗi;
`--select-only` và `--open-only` giữ Chrome mở. Ctrl+C đóng các Chrome thuộc lần
chạy hiện tại, kể cả worker thủ công đã xong trước worker khác.

Các bước:
1. Viết và chạy kiểm thử thất bại cho CLI, khóa hồ sơ, phiên Chrome độc lập,
   vòng đời worker, gửi một lần và hủy.
2. Viết script Windows và chạy kiểm thử qua Chrome/CDP thật với biểu mẫu mô phỏng.
3. Thêm launcher `.bat`, hướng dẫn tiếng Việt và ZIP có đủ phụ thuộc nguồn.
4. Chạy kiểm thử dự án, rà soát độc lập và ghi rõ giới hạn: máy hiện tại là macOS,
   nên chưa xác nhận trực tiếp msvcrt/launcher trên Windows.

Không gửi bình chọn thật khi kiểm thử. Giữ nguyên các script hiện có.

Đã hoàn tất script, launcher, hướng dẫn và ZIP. Bộ kiểm thử mới gồm 16 ca đạt
với Chrome thật/CDP và trang mô phỏng. Rà soát độc lập đã phát hiện và xác nhận
sửa lỗi Ctrl+C trong vòng dọn dẹp cuối cùng. Kết quả kiểm chứng và các lỗi còn
trong bộ kiểm thử cũ được ghi ở
`runtime/reports/windows-parallel-verification.md`.
