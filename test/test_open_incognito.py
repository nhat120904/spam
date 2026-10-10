"""Kiểm tra thao tác biểu mẫu trong Chrome với trang được mô phỏng cục bộ."""

import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

import open_incognito


class ChromePermissionTests(unittest.TestCase):
    def test_continues_after_user_enables_permission_without_rerunning(self):
        # Chrome là ứng dụng ngoài; chỉ giả lập biên Apple Events, giữ vòng chờ thật.
        denied = RuntimeError("JavaScript from Apple Events is disabled. (12)")
        with patch.object(open_incognito, "open_window", return_value=91), \
                patch.object(open_incognito, "run_applescript", side_effect=[denied, "1", ""]), \
                patch.object(open_incognito.time, "sleep"):
            open_incognito.ensure_javascript_permission(timeout=2)

    def test_does_not_wait_on_unrelated_chrome_errors(self):
        with patch.object(open_incognito, "open_window", return_value=91), \
                patch.object(open_incognito, "run_applescript", side_effect=RuntimeError("Chrome window closed")):
            with self.assertRaisesRegex(RuntimeError, "Chrome window closed"):
                open_incognito.ensure_javascript_permission(timeout=2)


class PrepareVoteFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "src" / "prepare-form.js"
        self.assertTrue(
            source.is_file(),
            "Chưa có mã chọn sao dùng trong Chrome mở trực tiếp.",
        )
        self.source = source.read_text(encoding="utf-8")
        self.submit_source_path = source.with_name("submit-form.js")
        self.result_source_path = source.with_name("read-vote-result.js")
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(2000)
        self.requests = []

    def prepare(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = json.loads(self.page.evaluate(self.source))
            if result["state"] == "ready":
                return result["ratings"]
            if result["state"] == "error":
                raise ValueError(result["message"])
            self.page.wait_for_timeout(50)
        self.fail("Biểu mẫu không mở hoặc chưa chọn được sao.")

    def load_form(self, criteria=8, school="1098", missing_star=False, captcha="human-only", quota=1,
                  response="1", status=200, defer_open_handler=False):
        rows = "".join(
            '<div class="rating-wrapper">'
            '<select class="rating" style="display:none">'
            '<option value="1">1</option><option value="5">5</option></select>'
            + ('' if missing_star and index == criteria - 1
               else '<a href="#" data-rating-value="5">5 sao</a>')
            + '</div>'
            for index in range(criteria)
        )
        html = f"""<!doctype html><meta charset="utf-8">
            <style>.mfp-hide {{ display:none !important; }}</style>
            <button class="btn-vote" data-thhp_id="1098">Bình chọn ngay</button>
            <div id="vote-popup" style="display:none">{rows}
              <strong id="err-max-vote">{quota}</strong>
              <input name="cf-turnstile-response" value="{captcha}">
              <button id="btn-confirm-vote" data-thhp_id="{school}">Bình chọn ngay</button>
            </div>
            <div id="vote-popup-success" class="mfp-hide">Bình chọn thành công</div>
            <div id="vote-popup-fail" class="mfp-hide">Hết lượt bình chọn</div>
            <script>
              window.submitClicks = 0;
              window.captcha1Response = {json.dumps(captcha)};
              window.turnstileWidget1 = 'vote-widget';
              window.fixtureTurnstileToken = {json.dumps(captcha)};
              window.fixtureTurnstileExpired = false;
              window.turnstile = {{
                getResponse: id => id === 'vote-widget' ? window.fixtureTurnstileToken : '',
                isExpired: id => id !== 'vote-widget' || window.fixtureTurnstileExpired,
              }};
              window.fixtureVerifyCaptcha = token => {{
                window.captcha1Response = window.fixtureTurnstileToken = token;
                document.querySelector('[name="cf-turnstile-response"]').value = token;
              }};
              window.bindVoteHandler = () => {{
                document.querySelector('.btn-vote').onclick = () => setTimeout(() => {{
                  document.querySelector('#vote-popup').style.display = 'block';
                }}, 100);
              }};
              if (!{json.dumps(defer_open_handler)}) window.bindVoteHandler();
              document.querySelectorAll('[data-rating-value]').forEach(star => {{
                star.onclick = event => {{
                  event.preventDefault();
                  star.closest('.rating-wrapper').querySelector('select').value = '5';
                }};
              }});
              document.querySelector('#btn-confirm-vote').onclick = () => {{
                window.submitClicks++;
                fetch('/truong-hoc-hanh-phuc/vote', {{method: 'POST'}}).then(async response => {{
                  const body = await response.text();
                  if (response.ok && body === '1') {{
                    document.querySelector('#vote-popup-success').classList.remove('mfp-hide');
                  }} else if (response.ok && body === '0') {{
                    document.querySelector('#vote-popup-fail').classList.remove('mfp-hide');
                  }} else if (response.ok && body === '3') {{
                    alert('Vui lòng xác minh mã Captcha!');
                  }} else if (response.ok && body === '2') {{
                    alert('Vui lòng cập nhật số điện thoại của bạn để tiếp tục bình chọn!');
                  }}
                  window.voteResponseHandled = true;
                }});
              }};
            </script>"""

        def serve(route):
            self.requests.append((route.request.method, route.request.url))
            if route.request.url == open_incognito.URL and route.request.method == "GET":
                route.fulfill(content_type="text/html; charset=utf-8", body=html)
            elif route.request.url == "https://treemvietnam.net.vn/truong-hoc-hanh-phuc/vote" and route.request.method == "POST":
                route.fulfill(status=status, content_type="text/plain", body=response)
            else:
                route.abort()

        self.page.route("**/*", serve)
        self.page.goto(open_incognito.URL)

    def assert_no_submission(self):
        self.assertEqual(self.page.evaluate("window.submitClicks"), 0)
        self.assertEqual(
            self.page.locator('[name="cf-turnstile-response"]').input_value(),
            "human-only",
        )
        self.assertEqual(self.requests, [("GET", open_incognito.URL)])

    def test_opens_delayed_popup_and_selects_eight_five_star_ratings(self):
        self.load_form()
        ratings = self.prepare()
        self.assertTrue(self.page.locator("#vote-popup").is_visible())
        self.assertEqual(ratings, ["5", "5", "5", "5", "5", "5", "5", "5"])
        self.assert_no_submission()

    def test_recovers_when_first_click_happens_before_site_binds_button_handler(self):
        self.load_form(defer_open_handler=True)
        first = json.loads(self.page.evaluate(self.source))
        self.assertEqual(first["state"], "waiting")
        self.assertFalse(self.page.locator("#vote-popup").is_visible())
        self.page.evaluate("window.bindVoteHandler()")
        self.assertEqual(self.prepare(), ["5"] * 8)
        self.assert_no_submission()

    def test_changed_form_is_rejected_before_any_star_is_selected(self):
        for options in ({"school": "999"}, {"criteria": 7}, {"missing_star": True}):
            with self.subTest(options=options):
                self.load_form(**options)
                with self.assertRaises(ValueError):
                    self.prepare()
                ratings = self.page.locator("select.rating").evaluate_all(
                    "elements => elements.map(element => element.value)"
                )
                self.assertEqual(ratings, ["1"] * options.get("criteria", 8))
                self.assert_no_submission()
                self.requests.clear()
                self.page.unroute("**/*")

    def test_does_not_touch_another_website_if_user_changes_tabs(self):
        self.load_form()
        self.page.route("https://example.test/**", lambda route: route.fulfill(body="other site"))
        self.page.goto("https://example.test/")
        result = json.loads(self.page.evaluate(self.source))
        self.assertEqual(result["state"], "error")
        self.assertEqual(self.page.content().count("rating-wrapper"), 0)

    def submit(self):
        self.assertTrue(self.submit_source_path.is_file(), "Chưa có bước tự bấm gửi.")
        return json.loads(self.page.evaluate(self.submit_source_path.read_text(encoding="utf-8")))

    def test_waits_for_captcha_then_clicks_once_even_when_polled_again(self):
        self.load_form(captcha="")
        self.prepare()
        self.assertEqual(self.submit()["state"], "waiting")
        self.assertEqual(self.page.evaluate("window.submitClicks"), 0)
        self.assertEqual(self.requests, [("GET", open_incognito.URL)])
        self.page.evaluate("window.fixtureVerifyCaptcha('fixture-human-confirmed')")
        with self.page.expect_response("**/truong-hoc-hanh-phuc/vote"):
            result = self.submit()
        self.assertEqual(result["state"], "clicked")
        self.assertNotIn("fixture-human-confirmed", json.dumps(result))
        self.assertEqual(self.submit()["state"], "clicked")
        self.assertEqual(self.page.evaluate("window.submitClicks"), 1)
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_waits_when_dom_token_exists_before_site_captcha_callback(self):
        self.load_form()
        self.prepare()
        self.page.evaluate("window.captcha1Response = ''")
        self.assertEqual(self.submit()["state"], "waiting")
        self.assert_no_submission()
        self.page.evaluate("window.fixtureVerifyCaptcha('verified-after-callback')")
        with self.page.expect_response("**/truong-hoc-hanh-phuc/vote"):
            self.assertEqual(self.submit()["state"], "clicked")
        self.assertEqual(self.page.evaluate("window.submitClicks"), 1)

    def test_does_not_submit_stale_expired_or_other_widget_captcha(self):
        for change in ("window.fixtureTurnstileToken = 'new-widget-token'",
                       "window.fixtureTurnstileExpired = true",
                       "window.turnstileWidget1 = 'login-widget'",
                       "window.captcha1Response = 'old-callback-token'",
                       "window.turnstile = undefined",
                       "window.turnstile.getResponse = () => { throw new Error('Widget removed'); }"):
            with self.subTest(change=change):
                self.load_form()
                self.prepare()
                self.page.evaluate(f"() => {{ {change}; }}")
                self.assertEqual(self.submit()["state"], "waiting")
                self.assert_no_submission()
                self.requests.clear()
                self.page.unroute("**/*")

    def test_reports_site_captcha_rejection_without_modal_or_second_submission(self):
        dialogs = []
        self.page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
        self.load_form(response="3")
        self.prepare()
        self.assertEqual(self.submit()["state"], "clicked")
        self.page.wait_for_function("window.voteResponseHandled === true")
        report = json.loads(self.page.evaluate(self.result_source_path.read_text()))
        self.assertEqual(report["state"], "error")
        self.assertIn("CAPTCHA", report["message"])
        self.assertEqual(dialogs, [], "Thông báo CAPTCHA không được khóa Apple Events bằng alert.")
        self.assertEqual(self.submit()["state"], "clicked")
        self.assertEqual(self.page.evaluate("window.submitClicks"), 1)
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_preserves_unrelated_site_alerts(self):
        dialogs = []
        self.page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
        self.load_form()
        self.prepare()
        self.submit()
        for message in ('Unrelated website warning', 'toString', 'constructor', '__proto__'):
            self.page.evaluate("message => alert(message)", message)
        self.assertEqual(dialogs, ['Unrelated website warning', 'toString', 'constructor', '__proto__'])

    def test_does_not_submit_if_csp_blocks_page_world_captcha_check(self):
        self.load_form()
        self.prepare()
        self.page.evaluate("""() => {
            const meta = document.createElement('meta');
            meta.httpEquiv = 'Content-Security-Policy';
            meta.content = "script-src 'none'";
            document.head.append(meta);
        }""")
        report = self.submit()
        self.assertEqual(report['state'], 'error')
        self.assertIn('callback CAPTCHA', report['message'])
        self.assert_no_submission()

    def test_does_not_submit_when_quota_is_zero_or_ratings_changed(self):
        for changed in ("quota", "rating", "school"):
            with self.subTest(changed=changed):
                self.load_form()
                self.prepare()
                if changed == "quota":
                    self.page.locator("#err-max-vote").evaluate("el => el.textContent = '0'")
                elif changed == "rating":
                    self.page.locator("select.rating").first.evaluate("el => el.value = '1'")
                else:
                    self.page.locator("#btn-confirm-vote").evaluate("el => el.dataset.thhp_id = '999'")
                self.assertEqual(self.submit()["state"], "error")
                self.assert_no_submission()
                self.requests.clear()
                self.page.unroute("**/*")

    def test_does_not_click_disabled_submit_button(self):
        self.load_form()
        self.prepare()
        self.page.locator("#btn-confirm-vote").evaluate("el => el.disabled = true")
        self.assertEqual(self.submit()["state"], "waiting")
        self.assert_no_submission()

    def test_does_not_submit_on_another_page(self):
        self.load_form()
        self.prepare()
        self.page.evaluate("history.replaceState(null, '', '/other-page')")
        self.assertEqual(self.submit()["state"], "error")
        self.assert_no_submission()

    def invoke_cli(self, *args):
        other_tab = self.context.new_page()
        other_tab.goto("about:blank")
        closed = []
        self.closed_vote_observations = []
        def execute_in_fixture(script):
            # Thay biên Apple Events bằng Chrome thử nghiệm; chạy nguyên JS sản phẩm.
            if "return id of active tab of window id 91" in script:
                return "92"
            if "close tab id 92 of window id 91" in script:
                self.closed_vote_observations.append({
                    "clicks": self.page.evaluate("window.submitClicks"),
                    "success": self.page.locator("#vote-popup-success").is_visible(),
                })
                closed.append(self.page.locator("select.rating").evaluate_all(
                    "elements => elements.map(element => element.value)"))
                self.page.close()
                return "closed"
            argument = script.split(" javascript ", 1)[1].rsplit("\nend tell", 1)[0]
            return self.page.evaluate(json.loads(argument))

        with patch.object(open_incognito, "open_window", return_value=91), \
                patch.object(open_incognito, "ensure_javascript_permission"), \
                patch.object(open_incognito, "run_applescript", side_effect=execute_in_fixture), \
                patch.object(open_incognito.sys, "argv", ["open_incognito.py", *args]), \
                redirect_stdout(io.StringIO()), patch.object(open_incognito.sys, "stderr", io.StringIO()):
            exit_code = open_incognito.main()
        self.assertFalse(other_tab.is_closed(), "Không được đóng tab khác.")
        return exit_code, closed

    def test_default_command_closes_only_voting_tab_after_success(self):
        self.load_form()
        with patch.object(open_incognito, "submit_vote_form", wraps=open_incognito.submit_vote_form) as submit:
            exit_code, closed = self.invoke_cli()
        self.assertEqual(submit.call_args.args[1], 10)
        self.assertEqual(exit_code, 0)
        self.assertTrue(self.page.is_closed())
        self.assertEqual(closed, [["5"] * 8])
        self.assertEqual(self.closed_vote_observations, [{"clicks": 1, "success": True}])
        self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])

    def test_failure_or_uncertain_response_closes_voting_tab_without_retry(self):
        for options in ({"response": "0"}, {"response": "", "status": 500}):
            with self.subTest(options=options):
                self.load_form(**options)
                exit_code, closed = self.invoke_cli("--response-timeout", "0.8")
                self.assertNotEqual(exit_code, 0)
                self.assertTrue(self.page.is_closed())
                self.assertEqual(closed, [["5"] * 8])
                self.assertEqual(self.closed_vote_observations, [{"clicks": 1, "success": False}])
                self.assertEqual([method for method, _ in self.requests], ["GET", "POST"])
                self.requests.clear()
                self.page = self.context.new_page()

    def test_cli_captcha_timeout_closes_own_tab_without_submission(self):
        self.load_form(captcha="")
        exit_code, closed = self.invoke_cli("--captcha-timeout", "0.05")
        self.assertEqual(exit_code, 1)
        self.assertTrue(self.page.is_closed())
        self.assertEqual(closed, [["5"] * 8])
        self.assertEqual(self.closed_vote_observations, [{"clicks": 0, "success": False}])
        self.assertEqual([method for method, _ in self.requests], ["GET"])

    def test_cli_form_error_closes_own_tab_before_submission(self):
        self.load_form(criteria=7)
        exit_code, closed = self.invoke_cli()
        self.assertEqual(exit_code, 1)
        self.assertTrue(self.page.is_closed())
        self.assertEqual(closed, [["1"] * 7])
        self.assertEqual(self.closed_vote_observations, [{"clicks": 0, "success": False}])

    def test_select_only_success_still_keeps_tab_open(self):
        self.load_form()
        exit_code, closed = self.invoke_cli("--select-only")
        self.assertEqual(exit_code, 0)
        self.assertFalse(self.page.is_closed())
        self.assertEqual(closed, [])
        self.assert_no_submission()

    def test_captcha_timeout_leaves_form_open_without_submission(self):
        self.load_form(captcha="")
        self.prepare()

        def execute_in_fixture(script):
            argument = script.split(" javascript ", 1)[1].rsplit("\nend tell", 1)[0]
            return self.page.evaluate(json.loads(argument))

        with patch.object(open_incognito, "run_applescript", side_effect=execute_in_fixture):
            with self.assertRaisesRegex(RuntimeError, "CAPTCHA"):
                open_incognito.submit_vote_form(window_id=91, timeout=0.05)
        self.assertTrue(self.page.locator("#vote-popup").is_visible())
        self.assertEqual(self.page.evaluate("window.submitClicks"), 0)
        self.assertEqual(self.requests, [("GET", open_incognito.URL)])


if __name__ == "__main__":
    unittest.main()
