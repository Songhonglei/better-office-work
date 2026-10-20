"""Run the shipped CLI in a separate process with a fresh, simulated Codex home."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli test-fixture")
elif args[:2] == ["app-server", "--help"]:
    print("--listen stdio://")
elif args[:2] == ["mcp", "login"]:
    assert '--scopes' in args
    assert 'mcp_oauth_credentials_store="keyring"' in args
    assert args[2] == "qq-mail-work"
    print("fixture OAuth complete (no real credentials)")
elif args[0] == "app-server":
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method = msg["method"]
        if method == "initialize":
            result = {}
        elif method == "thread/start":
            result = {"thread": {"id": "fixture-thread"}}
        elif method == "mcpServer/tool/call":
            assert msg["params"]["server"] == "qq-mail-work"
            assert msg["params"]["tool"] == "GetMe"
            result = {"structuredContent": {"data": {"scopes": ["mail:read"],
                "aliases": [{"email": "different@qq.com", "alias_id": "fixture-alias", "is_primary": False}]}}}
        else:
            raise AssertionError(method)
        print(json.dumps({"id": msg["id"], "result": result}), flush=True)
else:
    raise AssertionError(args)
'''


class PortableTests(unittest.TestCase):
    def test_fresh_home_relocated_skill_and_separate_codex_process(self):
        with tempfile.TemporaryDirectory(prefix="qq mail portable ") as temporary:
            root = Path(temporary)
            installed = root / "installed skills" / "qq-mail-manage"
            shutil.copytree(Path(__file__).resolve().parents[1], installed, ignore=shutil.ignore_patterns("__pycache__"))
            binary = root / "bin" / "codex"
            binary.parent.mkdir()
            binary.write_text(FAKE_CODEX)
            binary.chmod(0o700)
            env = {**os.environ, "CODEX_HOME": str(root / "clean-codex"), "QQ_MAIL_HOME": str(root / "private-mail"),
                   "QQ_MAIL_PROFILE": "default", "PATH": str(binary.parent) + os.pathsep + os.environ.get("PATH", "")}
            command = [sys.executable, str(installed / "scripts/onboard.py"), "--profile", "work", "init",
                       "--account", "different@qq.com", "--mode", "read"]
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"state": "verified"', result.stdout)
            self.assertIn('"account": "different@qq.com"', result.stdout)
            self.assertFalse((root / "clean-codex/config.toml").exists())
            profile = json.loads((root / "private-mail/profiles/work.json").read_text())
            self.assertIn("verified_at", profile)
            self.assertFalse((installed / "pending").exists())
            self.assertFalse((installed / "profiles").exists())


if __name__ == "__main__":
    unittest.main()
