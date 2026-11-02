"""Opt-in real Chromium + synthetic CLI acceptance; no external mail or website.

Run separately: python3 tests/browser_smoke.py
Requires playwright and its Chromium binary. All temporary files contain only
synthetic fixture data. No screenshots, recordings, traces or browser profiles persist.
"""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from browser_handoff import BrowserSession
from read_sms import run_workflow

CODE = '778812'
STATE = {'sends': 0, 'submits': 0, 'accepted': False}
PAGE = b'''<!doctype html><meta charset="utf-8">
<input id="phone" value="13000001218"><button id="send">send</button>
<input id="code"><button id="submit">login</button><div id="account" hidden>account</div>
<script>
document.querySelector('#send').onclick = async () => { await fetch('/send',{method:'POST'}); };
document.querySelector('#submit').onclick = async () => {
 const r = await fetch('/login',{method:'POST',body:document.querySelector('#code').value});
 if(r.ok) document.querySelector('#account').hidden=false;
};
</script>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode()
        status = 200
        if self.path == '/send':
            STATE['sends'] += 1
        elif self.path == '/login':
            STATE['submits'] += 1
            STATE['accepted'] = body == CODE
            status = 200 if STATE['accepted'] else 403
        self.send_response(status)
        self.end_headers()


FAKE_CLI = '''#!/usr/bin/env python3
from datetime import datetime, timezone, timedelta
import json,sys
args=sys.argv[1:]
if args==['+me']:
 data={'aliases':[{'email':'fixture@example.invalid'}],'scopes':['mail:read']}
elif args[:2]==['message','+search']:
 data={'data':[{'message_id':'msg_fixture'}], 'pagination':{'has_more':False}}
elif args[:2]==['message','+read']:
 stamp=datetime.now(timezone.utc).replace(microsecond=0)
 body='106809281150240 【百度】验证码：778812，您正在登录，有效期60秒。 SIM2_1218 '+stamp.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
 data={'message_id':'msg_fixture','dir':{'dir_id':1,'dir_name':'inbox'},
       'from':{'email':'forwarder@example.invalid'},'to':[{'email':'fixture@example.invalid'}],
       'subject':'SIM2_1218的短信验证码','body':body,'created_at':stamp.isoformat()}
else:
 sys.exit(2)
print(json.dumps({'ok':True,'data':data}))
'''


def free_port():
    with socket.socket() as channel:
        channel.bind(('127.0.0.1', 0))
        return channel.getsockname()[1]


class RealBrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.endpoint = 'http://127.0.0.1:' + str(free_port())
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port) + '/login'
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(headless=True, args=[
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=' + cls.endpoint.rsplit(':', 1)[1]])
        cls.context = cls.browser.new_context()
        cls.page = cls.context.new_page()
        cls.temp = tempfile.TemporaryDirectory()
        cls.cli = Path(cls.temp.name) / 'synthetic-cli'
        cls.cli.write_text(FAKE_CLI)
        cls.cli.chmod(0o700)

    @classmethod
    def tearDownClass(cls):
        cls.context.close()
        cls.browser.close()
        cls.runtime.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)
        cls.temp.cleanup()

    def setUp(self):
        STATE.update(sends=0, submits=0, accepted=False)
        self.page.goto(self.url)

    def flow(self, **updates):
        config = {'cdp_endpoint': self.endpoint, 'login_url': self.url,
                  'service': 'baidu', 'route': 'SIM2_1218', 'phone_selector': '#phone',
                  'send_selector': '#send', 'code_selector': '#code',
                  'submit_selector': '#submit', 'success_selector': '#account', 'timeout_ms': 1500}
        config.update(updates)
        settings = {'schema': 1, 'backend': 'cli', 'cli': str(self.cli), 'expected_email': 'fixture@example.invalid',
                    'services': {'baidu': '【百度】'}, 'phone_routes': {'SIM2_1218': '1218'},
                    'trusted_senders': ['forwarder@example.invalid'],
                    'subject_pattern': r'^(SIM[1-9]_([0-9]{4}))的短信验证码$'}
        root = Path(self.temp.name) / 'data'
        (root / 'profiles').mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = root / 'profiles/fixture.json'
        profile.write_text(json.dumps(settings))
        profile.chmod(0o600)
        browser_file = Path(self.temp.name) / 'browser.json'
        browser_file.write_text(json.dumps(config))
        browser_file.chmod(0o600)
        result = subprocess.run([sys.executable,
            str(Path(__file__).resolve().parents[1] / 'scripts/read_sms.py'),
            'login', '--profile', 'fixture', '--data-dir', str(root), '--service', 'baidu',
            '--route', 'SIM2_1218', '--browser-config', str(browser_file), '--wait-seconds', '5',
            '--interval', '0.1'], capture_output=True, text=True, timeout=20, check=False)
        self.assertNotIn(CODE, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if report['ok'] else 1)
        self.assertNotIn(CODE, json.dumps(report))
        self.assertFalse(self.page.is_closed())
        return report

    def test_login_from_cli_through_cdp_and_verify_visible_account(self):
        report = self.flow()
        self.assertTrue(report['login_passed'], report)
        self.assertEqual(STATE, {'sends': 1, 'submits': 1, 'accepted': True})
        self.assertEqual(self.page.locator('#code').input_value(), '')

    def test_wrong_phone_never_sends_or_fills(self):
        self.page.locator('#phone').fill('13000009999')
        report = self.flow()
        self.assertEqual(report['blocker'], 'browser_phone_suffix_mismatch')
        self.assertEqual((STATE['sends'], STATE['submits']), (0, 0))

    def test_login_failure_does_not_resubmit(self):
        report = self.flow(success_selector='#never-visible')
        self.assertFalse(report['login_passed'])
        self.assertEqual(report['blocker'], 'browser_login_not_verified_do_not_resubmit')
        self.assertEqual((STATE['sends'], STATE['submits']), (1, 1))
        self.assertEqual(self.page.locator('#code').input_value(), '')

    def test_existing_login_is_preserved(self):
        self.page.locator('#account').evaluate('(el) => el.hidden=false')
        report = self.flow()
        self.assertEqual(report['blocker'], 'browser_already_logged_in')
        self.assertEqual((STATE['sends'], STATE['submits']), (0, 0))

    def test_ambiguous_tab_never_sends(self):
        other = self.context.new_page()
        try:
            other.goto(self.url)
            report = self.flow()
            self.assertEqual(report['blocker'], 'browser_target_tab_missing_or_ambiguous')
            self.assertEqual((STATE['sends'], STATE['submits']), (0, 0))
        finally:
            other.close()


if __name__ == '__main__':
    unittest.main()
