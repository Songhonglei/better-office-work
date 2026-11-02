"""Fill one authorized Chromium login page without exporting its SMS code."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from onboard import SKILL_ROOT
from workflow_errors import WorkflowError


def _url(value):
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError('invalid_url')
        parsed.port  # Validate malformed/out-of-range ports before using this URL.
        return parsed
    except (TypeError, ValueError):
        raise WorkflowError('browser_url_invalid') from None


def validate_config(value: dict) -> dict:
    if not isinstance(value, dict):
        raise WorkflowError('browser_config_invalid')
    required = ('cdp_endpoint', 'login_url', 'service', 'route', 'phone_selector',
                'send_selector', 'code_selector', 'submit_selector', 'success_selector')
    allowed = set(required) | {'captcha_selector', 'timeout_ms'}
    if set(value) - allowed or any(not isinstance(value.get(k), str) or not 0 < len(value[k]) <= 1024 for k in required):
        raise WorkflowError('browser_config_invalid')
    endpoint, target = _url(value['cdp_endpoint']), _url(value['login_url'])
    if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or not endpoint.port
            or endpoint.path not in ('', '/')):
        raise WorkflowError('browser_cdp_must_be_loopback_http')
    if target.scheme != 'https' and not (target.scheme == 'http' and target.hostname == '127.0.0.1'):
        raise WorkflowError('browser_target_must_be_https')
    timeout = value.get('timeout_ms', 10000)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 100 <= timeout <= 30000:
        raise WorkflowError('browser_timeout_invalid')
    captcha = value.get('captcha_selector')
    if captcha is not None and (not isinstance(captcha, str) or not 0 < len(captcha) <= 1024):
        raise WorkflowError('browser_captcha_selector_invalid')
    return {**value, 'timeout_ms': timeout}


def load_browser_config(name: str) -> dict:
    path = Path(name).expanduser().absolute()
    if path.is_symlink() or SKILL_ROOT in path.resolve().parents:
        raise WorkflowError('browser_config_must_be_external')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384 or (os.name == 'posix' and (
            info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077)):
        raise WorkflowError('browser_config_must_be_private')
    try:
        return validate_config(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError, RecursionError):
        raise WorkflowError('browser_config_invalid') from None


class BrowserSession:
    def __init__(self, config: dict):
        self.config = validate_config(config)
        self.runtime = self.browser = self.page = None
        self.attempted = self.submitted = False

    def _location(self, *, same_path=True):
        actual, expected = urlsplit(self.page.url), urlsplit(self.config['login_url'])
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc) or (
                same_path and actual.path != expected.path):
            raise WorkflowError('browser_page_changed')

    def _captcha(self):
        selector = self.config.get('captcha_selector')
        if selector and self.page.locator(selector).is_visible():
            raise WorkflowError('browser_captcha_requires_user')

    def prepare(self, service: str, route: str, suffix: str):
        if (service, route) != (self.config['service'], self.config['route']):
            raise WorkflowError('browser_target_mismatch')
        if any(os.environ.get(key) for key in ('DEBUG', 'PWDEBUG')):
            raise WorkflowError('browser_disable_debug_logging')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise WorkflowError('browser_playwright_not_installed') from None
        try:
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.connect_over_cdp(
                self.config['cdp_endpoint'], timeout=self.config['timeout_ms'])
            expected = urlsplit(self.config['login_url'])
            pages = [page for context in self.browser.contexts for page in context.pages
                     if (urlsplit(page.url).scheme, urlsplit(page.url).netloc, urlsplit(page.url).path)
                     == (expected.scheme, expected.netloc, expected.path)]
            if len(pages) != 1:
                raise WorkflowError('browser_target_tab_missing_or_ambiguous')
            self.page = pages[0]
            self.page.set_default_timeout(self.config['timeout_ms'])
            self._location()
            self._captcha()
            if self.page.locator(self.config['success_selector']).is_visible():
                raise WorkflowError('browser_already_logged_in')
            phone = self.page.locator(self.config['phone_selector'])
            if phone.count() != 1:
                raise WorkflowError('browser_phone_field_ambiguous')
            raw = phone.input_value() if phone.evaluate('(el) => ["INPUT","TEXTAREA"].includes(el.tagName)') else phone.inner_text()
            if not re.sub(r'[^0-9]', '', raw).endswith(suffix):
                raise WorkflowError('browser_phone_suffix_mismatch')
            if self.page.locator(self.config['code_selector']).count() != 1:
                raise WorkflowError('browser_code_field_ambiguous')
            for key in ('send_selector', 'submit_selector'):
                if self.page.locator(self.config[key]).count() != 1:
                    raise WorkflowError('browser_action_ambiguous')
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError('browser_prepare_failed') from None

    def request_code(self):
        if self.attempted:
            raise WorkflowError('browser_send_already_attempted')
        self.attempted = True
        try:
            self._location()
            self._captcha()
            self.page.locator(self.config['send_selector']).click(timeout=self.config['timeout_ms'])
            self._captcha()
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError('browser_send_result_uncertain_do_not_retry') from None

    def finish(self, code: str, *, valid_until: datetime):
        if self.submitted or not self.attempted:
            raise WorkflowError('browser_login_attempt_invalid')
        self.submitted = True
        if not isinstance(code, str) or re.fullmatch(r'[0-9]{4,8}', code) is None:
            raise WorkflowError('browser_code_invalid')
        try:
            self._location()
            self._captcha()
            def remaining_ms():
                remaining = (valid_until - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    raise WorkflowError('browser_code_expired_do_not_submit')
                return max(1, min(self.config['timeout_ms'], int(remaining * 1000)))
            self.page.locator(self.config['code_selector']).fill(code, timeout=remaining_ms())
            self._location()
            self.page.locator(self.config['submit_selector']).click(timeout=remaining_ms())
            self._captcha()
            self.page.locator(self.config['success_selector']).wait_for(state='visible', timeout=self.config['timeout_ms'])
            self._location(same_path=False)
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError('browser_login_not_verified_do_not_resubmit') from None
        finally:
            # Best-effort cleanup, never overwrite a different tab after navigation.
            try:
                self._location()
                field = self.page.locator(self.config['code_selector'])
                if field.count() == 1:
                    field.fill('', timeout=500)
            except Exception:
                pass

    def disconnect(self):
        # Stop our driver connection, leave the user's browser, tabs and session alive.
        if self.runtime is not None:
            try:
                self.runtime.stop()
            except Exception:
                pass
            self.runtime = self.browser = self.page = None
