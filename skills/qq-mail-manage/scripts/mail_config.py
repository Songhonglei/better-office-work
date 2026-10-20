"""Portable profiles: official OAuth/keyring or an injected MCP access-token variable."""
import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

ENDPOINT = "https://api.mail.qq.com/mcp"
READ_TOOLS = ("GetMe", "ListMessages", "SearchMessages", "GetMessage", "ListAttachments", "DownloadAttachment")
WRITE_TOOLS = ("SendMessage", "ReplyMessage", "ForwardMessage", "DeleteMessage")
MODES = {"read": ("mail:read",), "read_send": ("mail:read", "mail:send"), "manage": ("mail:read", "mail:send", "mail:delete")}
AUTH_MODES = ("oauth_keyring", "env_token")
DEFAULT_TOKEN_ENV = "QQ_MAIL_ACCESS_TOKEN"
_known_token_names = {DEFAULT_TOKEN_ENV}
_runtime_secrets = set()


def validate_token_env_var(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in {
        "PATH", "HOME", "CODEX_HOME", "QQ_MAIL_HOME", "QQ_MAIL_PROFILE", "PYTHONPATH", "LD_PRELOAD", "RUST_LOG"}:
        raise ValueError("Invalid token environment variable name; use a dedicated credential variable")
    _known_token_names.add(name)
    return name


def token_value(settings):
    name = validate_token_env_var(settings.token_env_var)
    value = os.environ.get(name)
    if value is None or not value.strip() or any(c.isspace() for c in value):
        raise RuntimeError("MCP access-token variable is missing, empty or invalid; securely inject/update it, then verify; no authentication fallback")
    _runtime_secrets.add(value)
    return value


def token_names(extra=()):
    """Read variable names only from profiles, never credentials or OAuth stores."""
    names = set(_known_token_names)
    names.update(n for n in extra if isinstance(n, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n))
    try:
        paths = list((data_home() / "profiles").glob("*.json"))
    except (ValueError, OSError):
        paths = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("token_env_var") if isinstance(data, dict) else None
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                names.add(name)
        except (ValueError, OSError):
            continue  # A broken unrelated profile cannot enable secret inheritance.
    return names


def subprocess_env(settings=None, *, for_mcp=False, extra_names=()):
    names = token_names((*extra_names, settings.token_env_var if settings else None))
    result = {k: v for k, v in os.environ.items() if k not in names}
    if for_mcp and settings and settings.auth_mode == "env_token":
        result[settings.token_env_var] = token_value(settings)
    return result


def redact(value):
    """Redact current runtime tokens before output, diagnostics or receipt persistence."""
    secrets = set(_runtime_secrets) | {os.environ[n] for n in token_names() if os.environ.get(n)}
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            for form in {secret, quote(secret, safe=""), json.dumps(secret)[1:-1]}:
                value = value.replace(form, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def contains_runtime_secret(value):
    return redact(value) != value


def codex_home():
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()


def data_home():
    result = Path(os.environ.get("QQ_MAIL_HOME", str(codex_home() / "qq-mail-manage"))).expanduser().resolve()
    if result.is_relative_to(Path(__file__).resolve().parent.parent):
        raise ValueError("QQ_MAIL_HOME must be outside the installed skill; choose a private data directory")
    return result


def profile_name(value=None):
    value = value or os.environ.get("QQ_MAIL_PROFILE", "default")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", value):
        raise ValueError("Profile must be 1..40 lowercase letters, digits, hyphens or underscores")
    return value


def select_profile(value):
    os.environ["QQ_MAIL_PROFILE"] = profile_name(value)


def profile_path(name=None):
    return data_home() / "profiles" / (profile_name(name) + ".json")


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def write_private(path, value):
    private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".profile-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(redact(value), stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class Settings:
    profile: str
    account: str
    server: str
    mode: str
    auth_mode: str = "oauth_keyring"
    token_env_var: str | None = None

    @property
    def scopes(self):
        return MODES[self.mode]

    @property
    def state_dir(self):
        return data_home() / "state" / self.profile

    def as_dict(self):
        result = {"version": 2, "profile": self.profile, "account": self.account, "server": self.server,
                  "mode": self.mode, "auth_mode": self.auth_mode}
        if self.auth_mode == "env_token":
            result["token_env_var"] = self.token_env_var
        return result


def settings_from(data):
    required = {"profile", "account", "server", "mode"}
    if not isinstance(data, dict) or not required <= data.keys() or any(not isinstance(data[k], str) or not data[k] for k in required):
        raise ValueError("Invalid mailbox profile fields; repair the non-secret profile or onboard a new profile")
    name = profile_name(data["profile"])
    account = data["account"].strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]*@(qq\.com|foxmail\.com)", account):
        raise ValueError("Use the intended QQ Mail or Foxmail alias, not an arbitrary provider")
    server = data["server"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", server):
        raise ValueError("Invalid MCP server name")
    if data["mode"] not in MODES:
        raise ValueError("Mode must be read, read_send or manage")
    auth_mode = data.get("auth_mode", "oauth_keyring")
    if auth_mode not in AUTH_MODES:
        raise ValueError("Unknown authentication mode; use oauth_keyring or env_token")
    token_env_var = data.get("token_env_var")
    if auth_mode == "env_token":
        token_env_var = validate_token_env_var(DEFAULT_TOKEN_ENV if token_env_var is None else token_env_var)
    elif token_env_var is not None:
        raise ValueError("token_env_var is only valid in env_token mode")
    return Settings(name, account, server, data["mode"], auth_mode, token_env_var)


def load_settings():
    path = profile_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError("No mailbox profile. Run scripts/onboard.py init --account YOUR@qq.com first") from None
    except (ValueError, OSError) as error:
        raise RuntimeError("Cannot read mailbox profile; repair its JSON or onboard a new profile") from error
    result = settings_from(data)
    if result.profile != profile_name():
        raise ValueError("Profile identity mismatch")
    return result


def account():
    return load_settings().account


def codex_binary():
    if os.name != "posix":
        raise RuntimeError("This bridge currently supports macOS/Linux; use WSL on Windows")
    found = shutil.which("codex")
    fallback = Path.home() / ".local" / "bin" / "codex"
    if found:
        return found
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    raise RuntimeError("Real Codex CLI is missing from PATH; install Codex before onboarding")


def overrides(settings, tools=READ_TOOLS, *, automatic=False):
    key = "mcp_servers." + settings.server
    values = [
        key + '.url=' + json.dumps(ENDPOINT),
        key + '.enabled=true',
        key + '.scopes=' + json.dumps(settings.scopes),
        key + '.enabled_tools=' + json.dumps(tools),
        key + '.disabled_tools=[]',
        key + '.default_tools_approval_mode=' + json.dumps("auto" if automatic else "prompt"),
        key + '.startup_timeout_sec=30',
    ]
    if settings.auth_mode == "oauth_keyring":
        values.append('mcp_oauth_credentials_store="keyring"')
    else:
        # No model turn is used; avoid even the CLI's unrelated cached-login store.
        values.append('cli_auth_credentials_store="ephemeral"')
        values.append(key + '.bearer_token_env_var=' + json.dumps(validate_token_env_var(settings.token_env_var)))
    # Suppress unrelated configured servers only in this child process.
    config = codex_home() / "config.toml"
    if config.exists():
        servers = tomllib.loads(config.read_text(encoding="utf-8")).get("mcp_servers", {})
        selected = servers.get(settings.server)
        if selected is not None:
            safe_fields = {"url", "enabled", "scopes", "enabled_tools", "disabled_tools", "default_tools_approval_mode", "startup_timeout_sec", "tool_timeout_sec"}
            if settings.auth_mode == "env_token":
                safe_fields.add("bearer_token_env_var")
            if not isinstance(selected, dict) or selected.get("url") != ENDPOINT or set(selected) - safe_fields:
                raise RuntimeError("The chosen MCP name conflicts with existing transport/auth configuration; onboard a new profile/server name instead")
            if "bearer_token_env_var" in selected and selected["bearer_token_env_var"] != settings.token_env_var:
                raise RuntimeError("The chosen MCP name conflicts with the profile's token variable; use a matching variable or a new server name")
        for server in servers:
            if server != settings.server:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", server):
                    raise RuntimeError("An unrelated MCP name cannot be safely overridden; rename that server to letters/digits/hyphens/underscores")
                values.append("mcp_servers." + server + ".enabled=false")
    return [arg for value in values for arg in ("-c", value)]
