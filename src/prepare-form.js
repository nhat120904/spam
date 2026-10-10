// Chạy trong tab Chrome hiện tại để mở biểu mẫu và chọn sao.
// Kết quả là JSON để Python đọc qua Apple Events.
(() => {
  const result = (state, message, ratings = []) => JSON.stringify({ state, message, ratings });
  // Chrome mới mở có thể còn ở newtab trước khi điều hướng đến URL được yêu cầu.
  if (location.href === 'about:blank' || location.href === 'chrome://newtab/') {
    return result('waiting', 'Đang tải trang.');
  }
  if (location.protocol !== 'https:' || location.hostname !== 'treemvietnam.net.vn'
    || location.pathname !== '/truong-hoc-hanh-phuc/truong-tieu-hoc-thinh-liet-1098.html') {
    return result('error', 'Tab không còn ở trang Trường Tiểu học Thịnh Liệt.');
  }
  if (document.readyState === 'loading') {
    return result('waiting', 'Đang tải nội dung trang.');
  }
  if (typeof window.jQuery === 'function' && !window.jQuery.isReady) {
    return result('waiting', 'Đang chờ trang khởi tạo các nút bình chọn.');
  }

  const popup = document.querySelector('#vote-popup');
  const visible = popup && popup.getClientRects().length > 0
    && getComputedStyle(popup).visibility !== 'hidden';
  if (!visible) {
    const button = document.querySelector('.btn-vote[data-thhp_id="1098"]');
    if (!button) return result('waiting', 'Đang chờ nút Bình chọn ngay xuất hiện.');
    // Lần bấm đầu có thể xảy ra trước khi trang gắn handler. Thử lại cách
    // nhau một giây khi popup vẫn đóng; dừng bấm ngay khi popup xuất hiện.
    const now = Date.now();
    if (!window.__thinhLietFormOpeningAt || now - window.__thinhLietFormOpeningAt >= 1000) {
      window.__thinhLietFormOpeningAt = now;
      button.click();
    }
    return result('waiting', 'Đang chờ biểu mẫu bình chọn mở.');
  }

  const school = popup.querySelector('#btn-confirm-vote')?.getAttribute('data-thhp_id');
  const rows = [...popup.querySelectorAll('.rating-wrapper')];
  const ratings = [...popup.querySelectorAll('select.rating')];
  if (school !== '1098' || rows.length !== 8 || ratings.length !== 8) {
    return result('error', 'Biểu mẫu không khớp trường Thịnh Liệt và tám tiêu chí.');
  }
  const stars = rows.map(row => [...row.querySelectorAll('a[data-rating-value="5"]')]);
  if (stars.some(matches => matches.length !== 1)) {
    return result('error', 'Không tìm thấy đủ tám nút 5 sao. Hãy kiểm tra biểu mẫu.');
  }
  for (const [star] of stars) star.click();
  const values = ratings.map(select => select.value);
  if (values.some(value => value !== '5')) {
    return result('error', 'Chưa chọn được đủ 5 sao. Hãy kiểm tra các mục trên trang.');
  }
  return result('ready', 'Đã chọn 5 sao cho tám tiêu chí.', values);
})()
