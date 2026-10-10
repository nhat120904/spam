// Bấm gửi một lần sau khi người dùng xác minh CAPTCHA trong tab này.
// Chỉ trả trạng thái, không đưa giá trị CAPTCHA ra ngoài trang.
(() => {
  const result = (state, message) => JSON.stringify({ state, message });
  if (location.protocol !== 'https:' || location.hostname !== 'treemvietnam.net.vn'
    || location.pathname !== '/truong-hoc-hanh-phuc/truong-tieu-hoc-thinh-liet-1098.html') {
    return result('error', 'Tab không còn ở trang Trường Tiểu học Thịnh Liệt.');
  }
  if (window.__thinhLietVoteClicked) {
    return result('clicked', 'Nút bình chọn đã được bấm; không bấm lại.');
  }
  const popup = document.querySelector('#vote-popup');
  if (!popup || !popup.getClientRects().length || getComputedStyle(popup).visibility === 'hidden') {
    return result('error', 'Biểu mẫu bình chọn đã đóng.');
  }
  const button = popup.querySelector('#btn-confirm-vote');
  const ratings = [...popup.querySelectorAll('select.rating')];
  if (button?.getAttribute('data-thhp_id') !== '1098'
    || popup.querySelectorAll('.rating-wrapper').length !== 8
    || ratings.length !== 8 || ratings.some(select => select.value !== '5')) {
    return result('error', 'Biểu mẫu phải đúng trường Thịnh Liệt và đủ tám mục 5 sao.');
  }
  const remaining = popup.querySelector('#err-max-vote')?.textContent.trim();
  if (!/^\d+$/.test(remaining ?? '')) {
    return result('error', 'Không xác định được số lượt bình chọn còn lại.');
  }
  if (Number(remaining) === 0) {
    return result('error', 'Đã hết lượt bình chọn trên trang.');
  }
  if (!popup.querySelector('[name="cf-turnstile-response"]')?.value.trim()) {
    return result('waiting', 'Đang chờ bạn xác minh CAPTCHA.');
  }
  if (button.disabled || button.getAttribute('aria-disabled') === 'true'
    || !button.getClientRects().length || getComputedStyle(button).visibility === 'hidden') {
    return result('waiting', 'Đang chờ nút bình chọn sẵn sàng.');
  }

  // Apple Events chạy trong isolated world: đọc biến callback của website
  // bằng script trong page world, chỉ trả boolean qua DOM, không trả token.
  const markerId = '__thinh-liet-vote-status';
  let marker = document.getElementById(markerId);
  if (!marker) {
    marker = document.createElement('div');
    marker.id = markerId;
    marker.hidden = true;
    document.body.append(marker);
  }
  marker.dataset.captchaReady = 'false';
  marker.dataset.checked = 'false';
  const check = document.createElement('script');
  check.textContent = `(${(() => {
    const status = document.getElementById('__thinh-liet-vote-status');
    status.dataset.checked = 'true';
    const api = window.turnstile;
    const widget = window.turnstileWidget1;
    if (!api || typeof api.getResponse !== 'function' || typeof api.isExpired !== 'function'
      || widget == null) return;
    try {
      const token = api.getResponse(widget);
      const field = document.querySelector('#vote-popup [name="cf-turnstile-response"]');
      if (!token || api.isExpired(widget) || window.captcha1Response !== token
        || field?.value !== token) return;
    } catch {
      return;
    }

    // Các alert lỗi bình chọn khóa JavaScript, khiến Apple Events hết giờ.
    // Hiển thị nguyên thông báo trong trang và ghi lỗi để Python đọc được.
    // Không đổi phản hồi máy chủ, không xác minh hộ hay tự gửi lại CAPTCHA.
    if (!window.__thinhLietVoteAlertInstalled) {
      const originalAlert = window.alert;
      window.alert = function (message) {
        const errors = {
          'Vui lòng xác minh Captcha.': 'Trang chưa nhận xác minh CAPTCHA. Không tự gửi lại.',
          'Vui lòng xác minh mã Captcha!': 'Trang từ chối CAPTCHA; cần xác minh lại. Không tự gửi lại.',
          'Vui lòng cập nhật số điện thoại của bạn để tiếp tục bình chọn!':
            'Trang yêu cầu cập nhật số điện thoại. Không tự gửi lại.',
        };
        const current = document.getElementById('__thinh-liet-vote-status');
        const detail = Object.hasOwn(errors, String(message)) ? errors[String(message)] : null;
        if (!current || current.dataset.submitted !== 'true' || !detail) {
          return originalAlert.call(window, message);
        }
        current.dataset.error = detail;
        current.dataset.errorCode = String(message) === 'Vui lòng xác minh mã Captcha!'
          ? 'captcha-rejected' : 'site-error';
        current.textContent = String(message);
        current.hidden = false;
        current.setAttribute('role', 'alert');
        current.style.cssText = 'position:fixed;top:16px;left:16px;right:16px;z-index:2147483647;'
          + 'padding:20px;background:white;color:#b00020;border:2px solid #b00020;font:18px sans-serif;';
      };
      window.__thinhLietVoteAlertInstalled = true;
    }
    status.dataset.captchaReady = 'true';
  }).toString()})();`;
  try {
    document.documentElement.append(check);
  } finally {
    check.remove();
  }
  if (marker.dataset.checked !== 'true') {
    return result('error', 'Không kiểm tra được callback CAPTCHA của website; chưa bấm gửi.');
  }
  if (marker.dataset.captchaReady !== 'true') {
    return result('waiting', 'Đang chờ CAPTCHA của biểu mẫu được website xác nhận.');
  }
  // Đánh dấu trước khi bấm để các lần kiểm tra tiếp theo không gửi lại.
  window.__thinhLietVoteClicked = true;
  marker.dataset.submitted = 'true';
  button.click();
  return result('clicked', 'Đã bấm Bình chọn ngay một lần. Hãy kiểm tra kết quả trên trang.');
})()
