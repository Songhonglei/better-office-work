"""Host network defaults and persistence failures, with synthetic data and no sockets."""
import io
import json
import os
import ssl
import subprocess
import traceback
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import getproxies_environment, proxy_bypass_environment
from urllib.response import addinfourl

import test_refresh as fixtures

creds = fixtures.creds


class NetworkAndDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RefreshTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def exchange_with_host_defaults(self, *, status=200, location=None, error=None):
        calls = []
        reply = self.fixture.reply

        def transport(handler, request):
            # Exercise the real opener, default ProxyHandler, request processing,
            # SSLContext creation and redirect/error chain; replace sockets only.
            calls.append({"host": request.host, "tunnel": getattr(request, "_tunnel_host", None),
                          "url": request.full_url, "body": request.data,
                          "verify_mode": handler._context.verify_mode,
                          "check_hostname": handler._context.check_hostname,
                          "ca_file": os.environ.get("SSL_CERT_FILE"),
                          "ca_dir": os.environ.get("SSL_CERT_DIR")})
            if error:
                raise error
            headers = {"Location": location} if location else {}
            response = addinfourl(io.BytesIO(json.dumps(reply).encode()), headers, request.full_url, status)
            response.msg = "Synthetic response"
            return response

        with patch("urllib.request.getproxies", side_effect=getproxies_environment), \
             patch("urllib.request.proxy_bypass", side_effect=proxy_bypass_environment), \
             patch("urllib.request.HTTPSHandler.https_open", transport):
            try:
                result = creds.exchange(self.fixture.bundle, "none")
            except creds.CredentialError as caught:
                return calls, caught
        return calls, result

    def test_host_https_proxy_is_used_for_official_endpoint(self):
        with patch.dict(os.environ, {"https_proxy": "http://synthetic-proxy.example:8443"}):
            calls, result = self.exchange_with_host_defaults()
        self.assertEqual(result["access_token"], fixtures.N)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["host"], "synthetic-proxy.example:8443")
        self.assertEqual(calls[0]["tunnel"], "wx.mail.qq.com")
        self.assertEqual(calls[0]["url"], creds.TOKEN_ENDPOINT)

    def test_no_proxy_environment_works_without_invented_proxy(self):
        calls, result = self.exchange_with_host_defaults()
        self.assertEqual(result["access_token"], fixtures.N)
        self.assertEqual(calls[0]["host"], "wx.mail.qq.com")
        self.assertIsNone(calls[0]["tunnel"])

    def test_host_no_proxy_exclusion_is_respected(self):
        with patch.dict(os.environ, {"https_proxy": "http://synthetic-proxy.example:8443",
                                     "no_proxy": "wx.mail.qq.com"}):
            calls, result = self.exchange_with_host_defaults()
        self.assertEqual(result["access_token"], fixtures.N)
        self.assertEqual(calls[0]["host"], "wx.mail.qq.com")
        self.assertIsNone(calls[0]["tunnel"])

    def test_default_tls_verification_and_host_ca_environment_preserved(self):
        # No CA bundle is opened by this fixture. Inspect the environment passed
        # to the real default SSL context factory; never replace it with CERT_NONE.
        expected_file = "/synthetic/host-trust/ca.pem"
        expected_dir = "/synthetic/host-trust/certs"
        factory = ssl._create_default_https_context
        seen = []

        def host_context(*args, **kwargs):
            seen.append((os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR"), args, kwargs))
            return factory(*args, **kwargs)

        with patch.dict(os.environ, {"SSL_CERT_FILE": expected_file, "SSL_CERT_DIR": expected_dir}), \
             patch.object(ssl, "_create_default_https_context", side_effect=host_context):
            calls, result = self.exchange_with_host_defaults()
            self.assertEqual(os.environ["SSL_CERT_FILE"], expected_file)
            self.assertEqual(os.environ["SSL_CERT_DIR"], expected_dir)
        self.assertEqual(result["access_token"], fixtures.N)
        self.assertTrue(seen)
        self.assertEqual(seen[0][:2], (expected_file, expected_dir))
        self.assertEqual(calls[0]["verify_mode"], ssl.CERT_REQUIRED)
        self.assertTrue(calls[0]["check_hostname"])

    def test_malicious_redirects_never_receive_credential_request(self):
        for status in (301, 302, 303, 307, 308):
            for destination in ("https://synthetic-attacker.example/collect", "http://synthetic-attacker.example/collect"):
                with self.subTest(status=status, destination=destination):
                    with patch.dict(os.environ, {"https_proxy": "http://synthetic-proxy.example:8443"}):
                        calls, result = self.exchange_with_host_defaults(status=status, location=destination)
                    self.assertIsInstance(result, creds.CredentialError)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0]["url"], creds.TOKEN_ENDPOINT)
                    self.assertIn(fixtures.R.encode(), calls[0]["body"])
                    self.assertNotIn(fixtures.R, str(result))

    def test_proxy_exception_is_redacted_in_message_and_traceback(self):
        secret_proxy = "http://synthetic-user:" + fixtures.S + "@synthetic-proxy.example:8443"
        with patch.dict(os.environ, {"https_proxy": secret_proxy}):
            calls, result = self.exchange_with_host_defaults(error=URLError(secret_proxy + " " + fixtures.R))
        self.assertIsInstance(result, creds.CredentialError)
        self.assertEqual(len(calls), 1)
        trace = "".join(traceback.format_exception(result))
        for secret in (secret_proxy, fixtures.S, fixtures.R):
            self.assertNotIn(secret, str(result))
            self.assertNotIn(secret, trace)

    def test_rename_then_directory_fsync_failure_stops_and_preserves_guard(self):
        original = creds.sync_directory
        attempts = []

        def fail_after_rename(directory):
            current = self.fixture.load()
            attempts.append(current["refresh_state"])
            if current["refresh_state"] == "ready":
                raise OSError("synthetic directory fsync failure")
            return original(directory)

        with patch.object(creds, "sync_directory", side_effect=fail_after_rename), \
             patch.object(creds, "exchange", return_value=self.fixture.reply) as exchange:
            with self.assertRaisesRegex(creds.CredentialError, "persistence failed"):
                creds.access_token(self.fixture.settings)
            with self.assertRaisesRegex(creds.CredentialError, "pending"):
                creds.access_token(self.fixture.settings)
            exchange.assert_called_once()
        self.assertEqual(attempts, ["pending", "pending", "ready"])
        # New bytes are visible, but the durable guard blocks subsequent consumers.
        self.assertEqual(self.fixture.load()["refresh_state"], "ready")
        self.assertTrue(creds.FileStore(self.fixture.path).commit_guard_path.exists())
        self.assertEqual(self.fixture.load()["refresh_token"], fixtures.RN)

    def test_final_file_fsync_failure_never_returns_token(self):
        original = os.fsync
        calls = 0

        def fail_fifth(fd):
            nonlocal calls
            calls += 1  # Pending and guard files/directories precede final file.
            if calls == 5:
                raise OSError("synthetic file fsync failure")
            return original(fd)

        with patch.object(creds.os, "fsync", side_effect=fail_fifth), \
             patch.object(creds, "exchange", return_value=self.fixture.reply) as exchange:
            with self.assertRaisesRegex(creds.CredentialError, "persistence failed"):
                creds.access_token(self.fixture.settings)
            exchange.assert_called_once()
        self.assertEqual(self.fixture.load()["refresh_state"], "pending")
        self.assertFalse(list(self.fixture.private.glob(".credential-*")))

    def test_host_timeout_ack_is_resolved_only_by_durable_load(self):
        settings = self.fixture.changed(credential_source="host_command", credential_file=None,
                                        credential_command="/synthetic/adapter")
        current = dict(self.fixture.bundle)

        def cas(store, old, new):
            nonlocal current
            current = dict(new)
            if new["refresh_state"] == "ready":
                raise creds.HostSaveAcknowledgementUnknown("synthetic lost acknowledgement")
            return True

        with patch.object(creds.HostStore, "load", side_effect=lambda: current), \
             patch.object(creds.HostStore, "cas", cas), \
             patch.object(creds, "exchange", return_value=self.fixture.reply) as exchange:
            self.assertEqual(creds.access_token(settings), fixtures.N)
            exchange.assert_called_once()

    def test_explicit_host_storage_error_cannot_be_treated_as_lost_ack(self):
        settings = self.fixture.changed(credential_source="host_command", credential_file=None,
                                        credential_command="/synthetic/adapter")
        loads = []

        def load():
            loads.append(True)
            return self.fixture.bundle

        with patch.object(creds.HostStore, "load", side_effect=load), \
             patch.object(creds.HostStore, "cas", side_effect=[True, creds.CredentialError("synthetic host fsync failure")]), \
             patch.object(creds, "exchange", return_value=self.fixture.reply):
            with self.assertRaisesRegex(creds.CredentialError, "host fsync failure"):
                creds.access_token(settings)
        self.assertEqual(len(loads), 1)

    def test_host_request_distinguishes_timeout_from_explicit_error(self):
        store = creds.HostStore("/synthetic/adapter")
        with patch.object(creds.subprocess, "run", side_effect=subprocess.TimeoutExpired("adapter", 20, output=fixtures.R)):
            with self.assertRaises(creds.HostSaveAcknowledgementUnknown):
                store.cas(self.fixture.bundle, self.fixture.bundle)
        with patch.object(creds.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "adapter", stderr=fixtures.R)):
            with self.assertRaises(creds.CredentialError) as caught:
                store.cas(self.fixture.bundle, self.fixture.bundle)
            self.assertNotIsInstance(caught.exception, creds.HostSaveAcknowledgementUnknown)
        with patch.object(store, "request", return_value={"saved": False, "error": "synthetic fsync failure"}):
            with self.assertRaises(creds.CredentialError):
                store.cas(self.fixture.bundle, self.fixture.bundle)


if __name__ == "__main__":
    unittest.main()
