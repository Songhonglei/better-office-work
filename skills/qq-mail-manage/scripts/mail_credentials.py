"""Explicit credential sources and one-shot OAuth refresh; never discover user secrets.

Host adapter protocol and recovery contract: references/credentials.md.
Only access_token is handed to the MCP child. No credential is written to profiles.
"""
import base64
import contextlib
import fcntl
import hashlib
import http.client
import json
import math
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote_plus, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

TOKEN_ENDPOINT = "https://wx.mail.qq.com/oauth/token"
SOURCES = ("env", "host_command", "private_file")
POLICIES = ("host", "auto")
CLIENT_AUTH = ("none", "client_secret_basic", "client_secret_post")
ENV_FIELDS = {"access_token": "QQ_MAIL_ACCESS_TOKEN", "refresh_token": "QQ_MAIL_REFRESH_TOKEN",
              "client_id": "QQ_MAIL_CLIENT_ID", "token_type": "QQ_MAIL_TOKEN_TYPE",
              "scope": "QQ_MAIL_SCOPE", "expires_at": "QQ_MAIL_EXPIRES_AT",
              "client_secret": "QQ_MAIL_CLIENT_SECRET"}


class CredentialError(RuntimeError):
    pass


class HostSaveAcknowledgementUnknown(CredentialError):
    """Host CAS timed out; only a durable host read may resolve its acknowledgement."""


def fail(message):
    raise CredentialError(message + "; stop, reconcile with the credential owner; no automatic retry or browser login") from None


def remember(record):
    from mail_config import _runtime_secrets
    for key in ("access_token", "refresh_token", "client_secret"):
        value = record.get(key)
        if isinstance(value, str) and value:
            _runtime_secrets.add(value)


def validate_record(record, *, complete=False):
    if not isinstance(record, dict):
        fail("Invalid credential record")
    remember(record)
    access = record.get("access_token")
    if not isinstance(access, str) or not access or any(ord(c) < 33 or ord(c) > 126 for c in access):
        fail("MCP access-token variable is missing, empty or invalid; no authentication fallback")
    if record.get("refresh_state", "ready") != "ready":
        fail("Credential refresh is pending, rejected or unknown")
    if str(record.get("token_type", "Bearer")).lower() != "bearer":
        fail("Only Bearer MCP credentials are supported")
    if "expires_at" in record:
        expiry = record["expires_at"]
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= 0:
            fail("expires_at must be a positive UTC Unix timestamp")
    if complete:
        for key in ("refresh_token", "client_id", "scope", "token_type"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                fail("Automatic refresh requires the complete original credential bundle")
        if "expires_at" not in record or not isinstance(record.get("revision"), str) or not record["revision"]:
            fail("Automatic refresh requires expires_at and a store revision")
    return record


def credential_env_names(settings=None):
    names = set(ENV_FIELDS.values())
    if settings:
        names.add(settings.token_env_var)
        names.update(settings.credential_env_vars.values())
    return names - {None}


def env_record(settings):
    mapping = {**ENV_FIELDS, **settings.credential_env_vars, "access_token": settings.token_env_var}
    result = {key: os.environ[name] for key, name in mapping.items() if name in os.environ}
    remember(result)
    if "expires_at" in result:
        try:
            result["expires_at"] = float(result["expires_at"])
        except (ValueError, OverflowError):
            fail("expires_at must be a positive UTC Unix timestamp")
    return validate_record(result)


def private_path(path, *, directory=False):
    """Reject links, wrong owner, group/world bits and hard-linked secret files."""
    path = Path(path).expanduser().absolute()
    if path != path.resolve():
        fail("Credential paths must not contain symlinks")
    info = path.lstat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        fail("Credential directory/file must be owned by this user with mode 700/600")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
        fail("Credential path has an unsafe file type or link count")
    return path


def absolute_unlinked(path):
    path = Path(path).expanduser()
    if not path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise ValueError("Credential paths must be explicit absolute paths without traversal or .git components")
    if path != path.resolve():
        fail("Credential paths must not contain symlinks")
    return path


def repository_markers(path, *, allow_empty=False):
    """Classify every ancestor; never let an empty marker hide a real repository."""
    for parent in path.parents:
        marker = parent / ".git"
        if os.path.lexists(marker):
            try:
                info = marker.lstat()
                if not allow_empty or not stat.S_ISDIR(info.st_mode) or any(marker.iterdir()):
                    raise ValueError("Credential file must be outside the skill and any repository; nonempty or unclassified .git")
            except OSError:
                fail("Cannot classify .git marker; refusing credential path")
        # Bare repositories have no .git entry. Corrupt/partial Git structures
        # also remain rejected rather than being treated as sandbox placeholders.
        if os.path.lexists(parent / "HEAD") or (os.path.lexists(parent / "objects") and os.path.lexists(parent / "refs")):
            raise ValueError("Credential file must be outside the skill and any repository; bare or unclassified Git structure")


def confirm_not_repository(directory):
    """A failed rev-parse alone is insufficient: require known not-a-repo output.

    Structural marker checks run both before and after this read-only probe.
    No hooks, credential helpers, global Git config or QQ secrets are needed.
    """
    from mail_config import subprocess_env
    binary = shutil.which("git")
    if not binary:
        fail("Git is required to verify an explicit credential state directory")
    env = {key: value for key, value in subprocess_env().items() if not key.startswith("GIT_")}
    env.update(LC_ALL="C", LANG="C", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0", GIT_DISCOVERY_ACROSS_FILESYSTEM="1")
    try:
        result = subprocess.run([binary, "-C", str(directory), "rev-parse", "--absolute-git-dir"],
                                capture_output=True, text=True, timeout=5, check=False, env=env)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        fail("Git repository check failed; refusing credential path")
    if result.returncode == 0:
        raise ValueError("Credential file must be outside the skill and any repository")
    if (result.returncode != 128 or not isinstance(result.stdout, str) or not isinstance(result.stderr, str) or result.stdout.strip() or
            result.stderr.strip() != "fatal: not a git repository (or any of the parent directories): .git"):
        fail("Git repository check is unclassified; refusing credential path")


def outside_package(path, state_dir=None):
    path = absolute_unlinked(path)
    skill = Path(__file__).resolve().parent.parent
    if path.is_relative_to(skill):
        raise ValueError("Credential file must be outside the skill and any repository")
    if state_dir is None:
        repository_markers(path)
    else:
        root = absolute_unlinked(state_dir)
        if root.is_relative_to(skill) or skill.is_relative_to(root) or not path.is_relative_to(root) or path == root:
            raise ValueError("Credential file must be contained in an independent state directory outside skill code")
        # The host explicitly creates these private directories. No automatic
        # creation, chmod, sandbox edits or temporary-directory fallback.
        for directory in (path.parent, *path.parent.parents):
            private_path(directory, directory=True)
            if directory == root:
                break
        if os.path.lexists(path):
            private_path(path)
        repository_markers(path, allow_empty=True)
        confirm_not_repository(path.parent)
        repository_markers(path, allow_empty=True)
    return path


def read_file(path):
    private_path(path.parent, directory=True)
    private_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
            fail("Unsafe credential file permissions")
        try:
            result = json.load(stream)
        except (ValueError, UnicodeError):
            fail("Invalid credential file JSON")
    if isinstance(result, dict):
        remember(result)
    return result


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_record(path, record):
    private_path(path.parent, directory=True)
    fd, temporary = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            # Deliberately not mail_config.write_private: credentials must not be redacted.
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class FileStore:
    def __init__(self, path, state_dir=None):
        self.state_dir = state_dir
        self.path = outside_package(path, state_dir)
        private_path(self.path.parent, directory=True)

    def validate_location(self):
        outside_package(self.path, self.state_dir)
        private_path(self.path.parent, directory=True)

    def write_record(self, path, record):
        if path not in (self.path, self.commit_guard_path):
            raise ValueError("FileStore can only write its configured record or pending guard")
        self.validate_location()
        if os.path.lexists(path):
            private_path(path)
        atomic_record(path, record)

    def load(self):
        self.validate_location()
        if os.path.lexists(self.commit_guard_path):
            private_path(self.commit_guard_path)
            fail("Credential file persistence is pending; visible records are not a durable acknowledgement")
        return read_file(self.path)

    @property
    def commit_guard_path(self):
        return self.path.with_name(self.path.name + ".pending")

    def cas(self, previous, replacement):
        current = self.load()
        if current != previous:
            fail("Credential record changed; refusing to overwrite newer values")
        finalizing = previous.get("refresh_state") == "pending" and replacement.get("refresh_state") == "ready"
        try:
            if finalizing:
                # Durable, non-secret guard survives a visible-but-not-durable
                # final rename. A restart must not mistake that record for success.
                self.write_record(self.commit_guard_path, {"revision": previous["revision"]})
            self.write_record(self.path, replacement)
            if finalizing:
                self.validate_location()
                self.commit_guard_path.unlink()
                sync_directory(self.path.parent)
        except OSError:
            # Never recover a disk/fsync failure merely by reading visible bytes.
            fail("Credential file persistence failed; readable values do not prove a durable save")
        return True

    @property
    def lock_path(self):
        self.validate_location()
        return self.path.with_name(self.path.name + ".lock")


class HostStore:
    def __init__(self, command):
        self.command = command

    def request(self, payload):
        from mail_config import subprocess_env
        try:
            result = subprocess.run([self.command], input=json.dumps(payload), capture_output=True,
                                    text=True, timeout=20, check=True, env=subprocess_env())
            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            if payload.get("operation") == "compare_and_swap":
                raise HostSaveAcknowledgementUnknown("Host CAS acknowledgement timed out; durable state must be checked") from None
            fail("Host credential adapter timed out")
        except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
            fail("Host credential adapter failed or returned an unknown result")
        if isinstance(data, dict) and isinstance(data.get("record"), dict):
            remember(data["record"])
        return data

    def load(self):
        data = self.request({"operation": "load", "protocol": 1})
        if not isinstance(data, dict) or not isinstance(data.get("record"), dict):
            fail("Host adapter did not return a credential record")
        return data["record"]

    def cas(self, previous, replacement):
        data = self.request({"operation": "compare_and_swap", "protocol": 1,
                             "expected_revision": previous["revision"], "record": replacement})
        if not isinstance(data, dict) or set(data) != {"saved"} or type(data.get("saved")) is not bool:
            fail("Host save failed or returned an invalid acknowledgement")
        return data["saved"]

    @property
    def lock_path(self):
        from mail_config import data_home, private_dir
        root = private_dir(data_home() / "credential-locks")
        digest = hashlib.sha256(self.command.encode()).hexdigest()
        return root / (digest + ".lock")


@contextlib.contextmanager
def store_lock(store):
    path = store.lock_path
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
            fail("Unsafe credential lock permissions")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def exchange(record, method):
    """One POST, fixed official URL, host proxy/CA defaults, no redirects/retries."""
    fields = {"grant_type": "refresh_token", "refresh_token": record["refresh_token"]}
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if method == "none":
        fields["client_id"] = record["client_id"]
    else:
        secret = record.get("client_secret")
        if not isinstance(secret, str) or not secret:
            fail("Original confidential client requires its client_secret")
        if method == "client_secret_basic":
            encoded = base64.b64encode((quote_plus(record["client_id"], safe="") + ":" + quote_plus(secret, safe="")).encode()).decode()
            headers["Authorization"] = "Basic " + encoded
        elif method == "client_secret_post":
            fields.update(client_id=record["client_id"], client_secret=secret)
        else:
            fail("Unsupported original client authentication method")
    request = Request(TOKEN_ENDPOINT, data=urlencode(fields).encode(), headers=headers, method="POST")
    # urllib defaults honor the host's proxy and TLS trust configuration. Do not
    # replace its proxy handler, CA roots, hostname checks or verification mode.
    opener = build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            if response.status != 200:
                fail("OAuth refresh response is unknown")
            payload = response.read(65537)
            if len(payload) > 65536:
                fail("OAuth refresh response is too large")
            result = json.loads(payload)
    except HTTPError as error:
        # Do not print the error, body, request, headers or credential-bearing URL.
        if error.code == 400:
            try:
                reason = json.loads(error.read(65536)).get("error")
            except (ValueError, AttributeError, OSError):
                reason = None
            if reason == "invalid_grant":
                fail("OAuth invalid_grant; refresh token rejected or already rotated")
        fail("OAuth refresh rejected or redirected")
    except (OSError, ValueError, http.client.HTTPException):
        fail("OAuth refresh outcome unknown (timeout, response loss or malformed response)")
    if not isinstance(result, dict):
        fail("OAuth refresh response is invalid")
    remember(result)
    return result


def refreshed_record(previous, payload, started):
    access = payload.get("access_token")
    if not isinstance(access, str) or not access or any(ord(c) < 33 or ord(c) > 126 for c in access):
        fail("OAuth response lacks a valid access_token")
    lifetime = payload.get("expires_in")
    if isinstance(lifetime, bool) or not isinstance(lifetime, (int, float)) or not math.isfinite(lifetime) or lifetime <= 0:
        fail("OAuth response lacks a valid expires_in")
    if not isinstance(payload.get("token_type"), str) or payload["token_type"].lower() != "bearer":
        fail("OAuth response lacks Bearer token_type")
    result = {**previous, "access_token": access, "expires_at": started + lifetime,
              "token_type": payload["token_type"], "refresh_state": "ready", "revision": uuid.uuid4().hex}
    # RFC 6749 6: replacement is optional; if present it replaces the old token.
    for field in ("refresh_token", "scope"):
        if field in payload:
            if not isinstance(payload[field], str) or not payload[field].strip():
                fail("OAuth response has invalid refresh_token or scope")
            result[field] = payload[field]
    remember(result)
    return validate_record(result, complete=True)


def access_token(settings):
    if settings.credential_source == "env":
        record = env_record(settings)
        if "expires_at" in record and record["expires_at"] <= time.time() + settings.refresh_skew:
            fail("Injected credential is near expiry; host must atomically refresh, persist and reinject the complete bundle")
        return record["access_token"]
    store = FileStore(settings.credential_file, settings.credential_state_dir) if settings.credential_source == "private_file" else HostStore(settings.credential_command)
    with store_lock(store):
        # Always reread under the common source lock; no stale in-memory overwrite.
        record = validate_record(store.load(), complete=settings.refresh_policy == "auto")
        if "expires_at" not in record or record["expires_at"] > time.time() + settings.refresh_skew:
            return record["access_token"]
        if settings.refresh_policy != "auto":
            fail("Credential is near expiry; refresh is owned by the host")
        method = settings.client_auth_method
        if method != "none" and not record.get("client_secret"):
            fail("Original client authentication requires client_secret")
        # Persist before touching network. Any interruption leaves a durable barrier.
        pending = {**record, "revision": uuid.uuid4().hex, "refresh_state": "pending"}
        if not store.cas(record, pending):
            fresh = validate_record(store.load(), complete=True)
            if fresh["expires_at"] > time.time() + settings.refresh_skew:
                return fresh["access_token"]
            fail("Concurrent credential update; no refresh attempted")
        started = time.time()
        payload = exchange(pending, method)
        replacement = refreshed_record(pending, payload, started)
        try:
            saved = store.cas(pending, replacement)
        except HostSaveAcknowledgementUnknown:
            # The host load contract returns durable commits only. This recovery
            # is never used for file/fsync/disk errors or explicit host failures.
            saved = store.load() == replacement
        if not saved:
            fail("Credential rotation save is unknown or conflicted; do not reuse old tokens")
        if replacement["expires_at"] <= time.time():
            fail("Refreshed access token expired before use")
        return replacement["access_token"]
