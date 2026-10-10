// Chờ thông báo kết quả do chính trang bình chọn hiển thị.
(() => {
  const result = (state, message) => JSON.stringify({ state, message });
  if (location.protocol !== 'https:' || location.hostname !== 'treemvietnam.net.vn'
    || location.pathname !== '/truong-hoc-hanh-phuc/truong-tieu-hoc-thinh-liet-1098.html') {
    return result('error', 'Tab đã chuyển sang trang khác.');
  }
  if (!window.__thinhLietVoteClicked) {
    return result('error', 'Không còn trạng thái gửi bình chọn.');
  }
  const siteError = document.getElementById('__thinh-liet-vote-status')?.dataset.error;
  if (siteError) return result('error', siteError);
  const visible = selector => {
    const element = document.querySelector(selector);
    return element && element.getClientRects().length > 0
      && getComputedStyle(element).visibility !== 'hidden';
  };
  if (visible('#vote-popup-success')) {
    return result('success', 'Trang đã báo bình chọn thành công.');
  }
  if (visible('#vote-popup-fail')) {
    return result('error', 'Trang báo hết lượt bình chọn.');
  }
  return result('waiting', 'Đang chờ trang báo kết quả bình chọn.');
})()
