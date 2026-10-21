"""Independent state directories: synthetic credentials and local disposable Git fixtures."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_refresh as fixtures

creds, config, onboard = fixtures.creds, fixtures.config, fixtures.onboard
NOT_REPO = "fatal: not a git repository (or any of the parent directories): .git\n"


class StateLocationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RefreshTests()
        self.fixture.setUp()
        # Only the test environment needs a synthetic TMPDIR for Apple's sandboxed
        # Git wrapper; production code does not change host temporary paths.
        os.environ["TMPDIR"] = str(self.fixture.root)
        self.sandbox = self.fixture.root / "sandbox"
        self.sandbox.mkdir(mode=0o700)
        (self.sandbox / ".git").mkdir()
        self.state = self.sandbox / "mail-state"
        self.state.mkdir(mode=0o700)
        self.directory = self.state / "credentials"
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / "bundle.json"
        creds.atomic_record(self.path, self.fixture.bundle)
        self.data = {**self.fixture.settings.as_dict(), "credential_file": str(self.path),
                     "credential_state_dir": str(self.state)}

    def tearDown(self):
        self.fixture.tearDown()

    def settings(self, **changes):
        return config.settings_from({**self.data, **changes})

    def git(self, *arguments):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        return subprocess.run(["git", "-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath="+os.devnull, *map(str, arguments)],
            env=env, capture_output=True, text=True, timeout=10, check=True)

    def private_location(self, base):
        state = base / "mail-state"
        state.mkdir(mode=0o700)
        path = state / "bundle.json"
        creds.atomic_record(path, self.fixture.bundle)
        return state, path

    def test_empty_placeholder_requires_explicit_private_state_root(self):
        with self.assertRaisesRegex(ValueError, "outside the skill"):
            config.settings_from({**self.data, "credential_state_dir": None})
        settings = self.settings()
        store = creds.FileStore(settings.credential_file, settings.credential_state_dir)
        self.assertEqual(store.load()["access_token"], fixtures.A)
        self.assertEqual(settings.as_dict()["credential_state_dir"], str(self.state))
        self.assertEqual(list((self.sandbox / ".git").iterdir()), [])

    def test_multiple_empty_placeholders_are_checked(self):
        (self.state / ".git").mkdir()
        settings = self.settings()
        self.assertEqual(creds.FileStore(settings.credential_file, settings.credential_state_dir).load(), self.fixture.bundle)
        self.assertEqual(list((self.state / ".git").iterdir()), [])

    def test_real_repository_worktree_and_bare_are_rejected(self):
        repository = self.sandbox / "real"
        self.git("init", "-q", repository)
        self.git("-C", repository, "commit", "-qm", "synthetic", "--allow-empty")
        worktree = self.sandbox / "worktree"
        self.git("-C", repository, "worktree", "add", "--detach", worktree, "HEAD")
        bare = self.sandbox / "bare"
        self.git("init", "--bare", "-q", bare)
        for base in (repository, worktree, bare):
            with self.subTest(base=base.name):
                state, path = self.private_location(base)
                with self.assertRaisesRegex(ValueError, "repository"):
                    self.settings(credential_state_dir=str(state), credential_file=str(path))
                with self.assertRaisesRegex(ValueError, "repository"):
                    creds.FileStore(path, state)

    def test_empty_marker_cannot_hide_real_repository_above_it(self):
        repository = self.sandbox / "real"
        self.git("init", "-q", repository)
        nested = repository / "nested"
        nested.mkdir(); (nested / ".git").mkdir()
        state, path = self.private_location(nested)
        with self.assertRaisesRegex(ValueError, "repository"):
            self.settings(credential_state_dir=str(state), credential_file=str(path))

    def test_nonempty_and_unreadable_markers_are_not_bypassed_by_git_failure(self):
        marker = self.sandbox / ".git"
        (marker / "unclassified").write_text("synthetic")
        with patch.object(creds.subprocess, "run", return_value=subprocess.CompletedProcess([], 128, "", NOT_REPO)) as run:
            with self.assertRaises(ValueError): self.settings()
            run.assert_not_called()
        (marker / "unclassified").unlink()
        original = Path.iterdir
        def unreadable(path):
            if path == marker: raise PermissionError("synthetic permission failure")
            return original(path)
        with patch.object(Path, "iterdir", unreadable):
            with self.assertRaisesRegex(creds.CredentialError, "Cannot classify"):
                self.settings()

    def test_git_errors_missing_binary_and_unclassified_output_rejected(self):
        for result in (subprocess.CompletedProcess([], 0, "/synthetic/.git\n", ""),
                       subprocess.CompletedProcess([], 128, "", "fatal: unsafe repository\n"),
                       subprocess.CompletedProcess([], 1, "", NOT_REPO),
                       subprocess.CompletedProcess([], 128, "unexpected", NOT_REPO),
                       subprocess.CompletedProcess([], 128, "", "warning\n"+NOT_REPO)):
            with patch.object(creds.subprocess, "run", return_value=result):
                with self.assertRaises((ValueError, creds.CredentialError)): self.settings()
        for error in (subprocess.TimeoutExpired("git", 5), OSError("synthetic failure")):
            with patch.object(creds.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(creds.CredentialError, "Git repository check failed"): self.settings()
        with patch.object(creds.shutil, "which", return_value=None):
            with self.assertRaisesRegex(creds.CredentialError, "Git is required"): self.settings()

    def test_git_probe_is_read_only_and_strips_secrets_and_git_overrides(self):
        with patch.dict(os.environ, {"QQ_MAIL_ACCESS_TOKEN": fixtures.A, "QQ_MAIL_REFRESH_TOKEN": fixtures.R,
                 "GIT_DIR": "/synthetic/override", "GIT_WORK_TREE": "/synthetic/worktree"}), \
             patch.object(creds.subprocess, "run", return_value=subprocess.CompletedProcess([], 128, "", NOT_REPO)) as run:
            self.settings()
        args, kwargs = run.call_args
        self.assertEqual(args[0][-2:], ["rev-parse", "--absolute-git-dir"])
        self.assertNotIn("QQ_MAIL_ACCESS_TOKEN", kwargs["env"])
        self.assertNotIn("QQ_MAIL_REFRESH_TOKEN", kwargs["env"])
        self.assertNotIn("GIT_DIR", kwargs["env"])
        self.assertNotIn("GIT_WORK_TREE", kwargs["env"])
        self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(kwargs["timeout"], 5)

    def test_boundary_traversal_skill_and_nonabsolute_roots_rejected(self):
        for root, path in ((str(self.state), str(self.fixture.path)),
                           (str(self.state), str(self.state / "credentials/../../escape.json")),
                           (str(self.state), str(self.state)),
                           ("relative", str(self.path)),
                           (str(self.state), str(self.state / ".git/bundle.json"))):
            with self.subTest(root=root, path=path):
                with self.assertRaises((ValueError, creds.CredentialError)):
                    self.settings(credential_state_dir=root, credential_file=path)
        skill = Path(creds.__file__).resolve().parent.parent
        with self.assertRaises(ValueError):
            self.settings(credential_state_dir=str(skill), credential_file=str(skill / "private/bundle.json"))
        with self.assertRaises(ValueError):
            self.settings(credential_state_dir=str(skill.parent), credential_file=str(skill.parent / "bundle.json"))

    def test_unsafe_directory_file_and_owner_permissions_rejected_by_config_and_store(self):
        for path, unsafe, safe in ((self.state, 0o755, 0o700), (self.directory, 0o750, 0o700), (self.path, 0o644, 0o600)):
            path.chmod(unsafe)
            try:
                for operation in (self.settings, lambda: creds.FileStore(self.path, self.state)):
                    with self.assertRaises(creds.CredentialError): operation()
            finally:
                path.chmod(safe)
        with patch.object(creds.os, "getuid", return_value=os.getuid()+1):
            with self.assertRaises(creds.CredentialError): self.settings()

    def test_symlinks_hardlinks_and_git_symlinks_rejected(self):
        alias = self.sandbox / "state-link"
        alias.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(creds.CredentialError):
            self.settings(credential_state_dir=str(alias), credential_file=str(alias / "credentials/bundle.json"))
        link = self.directory / "linked.json"
        link.symlink_to(self.fixture.path)
        with self.assertRaises(creds.CredentialError): self.settings(credential_file=str(link))
        hard = self.directory / "hard.json"
        os.link(self.path, hard)
        with self.assertRaises(creds.CredentialError): self.settings()
        hard.unlink()
        marker = self.sandbox / ".git"
        marker.rmdir(); marker.symlink_to(self.fixture.private, target_is_directory=True)
        with self.assertRaises(ValueError): self.settings()

    def test_runtime_rechecks_location_before_read_write_and_lock_creation(self):
        store = creds.FileStore(self.path, self.state)
        with patch.object(creds, "atomic_record") as write:
            with self.assertRaisesRegex(ValueError, "configured record"):
                store.write_record(self.fixture.path, self.fixture.bundle)
            write.assert_not_called()
        original = self.path.read_bytes()
        (self.sandbox / ".git/HEAD").write_text("unclassified")
        with patch.object(creds, "atomic_record") as write:
            for operation in (store.load, lambda: store.cas(self.fixture.bundle, self.fixture.bundle), lambda: store.lock_path):
                with self.assertRaises(ValueError): operation()
            write.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.path.with_name("bundle.json.lock").exists())

    def test_private_state_survives_replacement_of_skill_code(self):
        installed = self.sandbox / "installed-skill"
        (installed / "scripts").mkdir(parents=True)
        source = Path(creds.__file__)
        script = installed / "scripts/mail_credentials.py"
        shutil.copyfile(source, script)
        spec = importlib.util.spec_from_file_location("synthetic_installed_credentials", script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        before = self.path.read_bytes()
        self.assertEqual(module.FileStore(self.path, self.state).load(), self.fixture.bundle)
        shutil.rmtree(installed)  # Only disposable, synthetic code is replaced.
        script.parent.mkdir(parents=True)
        shutil.copyfile(source, script)
        (installed / "SKILL.md").write_text("synthetic upgraded code")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(module.FileStore(self.path, self.state).load(), self.fixture.bundle)
        self.assertFalse(self.path.is_relative_to(installed))

    def test_lock_cas_and_pending_barrier_survive_directory_fsync_failure(self):
        settings = self.settings()
        original = creds.sync_directory
        def fail_final(directory):
            if json.loads(self.path.read_text())["refresh_state"] == "ready":
                raise OSError("synthetic directory fsync failure")
            return original(directory)
        with patch.object(creds, "exchange", return_value=self.fixture.reply) as exchange, \
             patch.object(creds, "sync_directory", side_effect=fail_final):
            with self.assertRaisesRegex(creds.CredentialError, "persistence failed"): creds.access_token(settings)
            with self.assertRaisesRegex(creds.CredentialError, "pending"): creds.access_token(settings)
            exchange.assert_called_once()
        self.assertTrue(creds.FileStore(self.path, self.state).commit_guard_path.exists())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.with_name("bundle.json.lock").stat().st_mode & 0o777, 0o600)

    def test_reconfigure_retains_state_root_and_source_switch_clears_it(self):
        configured = onboard.configure("target@qq.com", "read_send", auth_mode="env_token",
            credential_source="private_file", credential_file=str(self.path), credential_state_dir=str(self.state),
            refresh_policy="auto", client_auth_method="none")
        self.assertEqual(onboard.configure("target@qq.com", "read_send"), configured)
        changed = onboard.configure("target@qq.com", "read_send", credential_source="env")
        self.assertIsNone(changed.credential_state_dir)
        self.assertIsNone(changed.credential_file)

    def test_cli_configure_only_accepts_explicit_state_root_without_reading_credentials(self):
        self.path.unlink()  # The host has not imported even synthetic credentials yet.
        binary = self.fixture.root / "bin/codex"
        binary.parent.mkdir()
        binary.write_text(fixtures.FAKE_CODEX); binary.chmod(0o700)
        os.environ.update(PATH=str(binary.parent)+os.pathsep+str(Path(sys.executable).parent)+os.pathsep+os.defpath,
                          FIXTURE_EVENTS=str(self.fixture.root / "events"), FIXTURE_AUTH="env_token")
        result = subprocess.run([sys.executable, str(Path(onboard.__file__)), "--profile", "cloud", "init",
            "--account", "target@qq.com", "--mode", "read_send", "--auth-mode", "env_token",
            "--credential-source", "private_file", "--credential-file", str(self.path),
            "--credential-state-dir", str(self.state), "--configure-only"],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["state"], "configured_not_verified")
        self.assertEqual(data["credential_state_dir"], str(self.state))
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
