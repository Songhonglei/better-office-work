"""Portable profiles: official OAuth/keyring or an injected MCP access-token variable."""
import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

ENDPOINT = "https://api.mail.qq.com/mcp"
READ_TOOLS = ("GetMe", "ListMessages", "SearchMessages", "GetMessage", "ListAttachments", "DownloadAttachment")
WRITE_TOOLS = ("SendMessage", "ReplyMessage", "ForwardMessage", "DeleteMessage")
MODES = {"read": ("mail:read",), "read_send": ("mail:read", "mail:send"), "manage": ("mail:read", "mail:send", "mail:delete")}
AUTH_MODES = ("oauth_keyring", "env_token")
BACKENDS = ("codex", "direct_http")
HTTP_PROTOCOLS = ("auto", "2026-07-28", "2025-03-26", "2025-06-18", "2025-11-25")
DEFAULT_TOKEN_ENV = "QQ_MAIL_ACCESS_TOKEN"
_known_token_names = {DEFAULT_TOKEN_ENV}
_known_secret_names = {DEFAULT_TOKEN_ENV, "QQ_MAIL_REFRESH_TOKEN", "QQ_MAIL_CLIENT_SECRET"}
_runtime_secrets = set()


def validate_token_env_var(name, *, secret=True):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in {
        "PATH", "HOME", "CODEX_HOME", "QQ_MAIL_HOME", "QQ_MAIL_PROFILE", "PYTHONPATH", "LD_PRELOAD", "RUST_LOG"}:
        raise ValueError("Invalid token environment variable name; use a dedicated credential variable")
    _known_token_names.add(name)
    if secret:
        _known_secret_names.add(name)
    return name


def token_value(settings):
    from mail_credentials import access_token
    return access_token(settings)


def token_names(extra=()):
    """Read variable names only from profiles, never credentials or OAuth stores."""
    names = set(_known_token_names)
    from mail_credentials import credential_env_names
    names.update(credential_env_names())
    names.update(n for n in extra if isinstance(n, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n))
    try:
        paths = list((data_home() / "profiles").glob("*.json"))
    except (ValueError, OSError):
        paths = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("token_env_var") if isinstance(data, dict) else None
            if isinstance(data, dict) and isinstance(data.get("credential_env_vars"), dict):
                names.update(n for n in data["credential_env_vars"].values()
                             if isinstance(n, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n))
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                names.add(name)
        except (ValueError, OSError):
            continue  # A broken unrelated profile cannot enable secret inheritance.
    return names


def subprocess_env(settings=None, *, for_mcp=False, extra_names=()):
    from mail_credentials import credential_env_names
    names = token_names((*extra_names, settings.token_env_var if settings else None))
    names.update(credential_env_names(settings))
    result = {k: v for k, v in os.environ.items() if k not in names}
    if for_mcp and settings and settings.auth_mode == "env_token":
        result[settings.token_env_var] = token_value(settings)
    return result


def redact(value):
    """Redact current runtime tokens before output, diagnostics or receipt persistence."""
    names = set(_known_secret_names)
    # Public scope/type/client metadata must remain intact for GetMe validation.
    try:
        paths = list((data_home() / "profiles").glob("*.json"))
    except (ValueError, OSError):
        paths = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                candidates = [data.get("token_env_var")]
                mapping = data.get("credential_env_vars", {})
                if isinstance(mapping, dict):
                    candidates.extend(mapping.get(key) for key in ("refresh_token", "client_secret"))
                names.update(n for n in candidates if isinstance(n, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n))
        except (ValueError, OSError):
            continue
    secrets = set(_runtime_secrets) | {os.environ[n] for n in names if isinstance(n, str) and os.environ.get(n)}
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
    credential_source: str = "env"
    credential_env_vars: dict = field(default_factory=dict)
    credential_file: str | None = None
    credential_command: str | None = None
    refresh_policy: str = "host"
    client_auth_method: str | None = None
    refresh_skew: int = 120
    allow_extra_delete_scope: bool = False
    credential_state_dir: str | None = None
    backend: str = "codex"
    http_protocol: str = "auto"

    @property
    def scopes(self):
        return MODES[self.mode]

    @property
    def state_dir(self):
        return data_home() / "state" / self.profile

    def as_dict(self):
        result = {"version": 3, "profile": self.profile, "account": self.account, "server": self.server,
                  "mode": self.mode, "auth_mode": self.auth_mode,
                  "allow_extra_delete_scope": self.allow_extra_delete_scope}
        result["backend"] = self.backend
        result["http_protocol"] = self.http_protocol
        if self.auth_mode == "env_token":
            result["token_env_var"] = self.token_env_var
            result.update(credential_source=self.credential_source, credential_env_vars=self.credential_env_vars,
                          refresh_policy=self.refresh_policy, refresh_skew=self.refresh_skew)
            for key in ("credential_file", "credential_command", "client_auth_method", "credential_state_dir"):
                if getattr(self, key) is not None:
                    result[key] = getattr(self, key)
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
    backend = data.get("backend", "codex")
    if backend not in BACKENDS or (backend == "direct_http" and auth_mode != "env_token"):
        raise ValueError("direct_http requires explicit env_token credentials; backend must be codex or direct_http")
    http_protocol = data.get("http_protocol", "auto")
    if http_protocol not in HTTP_PROTOCOLS:
        raise ValueError("Unknown direct HTTP protocol selection")
    token_env_var = data.get("token_env_var")
    if auth_mode == "env_token":
        token_env_var = validate_token_env_var(DEFAULT_TOKEN_ENV if token_env_var is None else token_env_var)
    elif token_env_var is not None:
        raise ValueError("token_env_var is only valid in env_token mode")
    from mail_credentials import SOURCES, POLICIES, CLIENT_AUTH, ENV_FIELDS, outside_package
    source = data.get("credential_source", "env")
    policy = data.get("refresh_policy", "host")
    mapping = data.get("credential_env_vars", {})
    credential_file = data.get("credential_file")
    state_dir = data.get("credential_state_dir")
    command = data.get("credential_command")
    method = data.get("client_auth_method")
    skew = data.get("refresh_skew", 120)
    allow_extra_delete_scope = data.get("allow_extra_delete_scope", False)
    if type(allow_extra_delete_scope) is not bool or (allow_extra_delete_scope and data["mode"] != "read_send"):
        raise ValueError("allow_extra_delete_scope must be boolean and can only be enabled in read_send mode")
    if source not in SOURCES or policy not in POLICIES or type(skew) is not int or not 0 <= skew <= 3600:
        raise ValueError("Invalid credential source, refresh policy or refresh_skew (0..3600 seconds)")
    if not isinstance(mapping, dict) or set(mapping) - (ENV_FIELDS.keys() - {"access_token"}):
        raise ValueError("Invalid credential environment field mapping; access_token uses token_env_var")
    mapping = {key: validate_token_env_var(value, secret=key in ("refresh_token", "client_secret")) for key, value in mapping.items()}
    effective_names = {**ENV_FIELDS, **mapping, "access_token": token_env_var}
    if auth_mode == "env_token" and len(set(effective_names.values())) != len(effective_names):
        raise ValueError("Credential environment variables must be distinct")
    if method is not None and method not in CLIENT_AUTH:
        raise ValueError("Unsupported original client authentication method")
    if policy == "auto" and (auth_mode != "env_token" or source == "env" or method is None):
        raise ValueError("Automatic refresh needs an explicit durable source and original client_auth_method")
    if source == "private_file":
        if not isinstance(credential_file, str) or not Path(credential_file).is_absolute():
            raise ValueError("private_file needs an explicit absolute credential_file")
        if state_dir is not None and (not isinstance(state_dir, str) or not Path(state_dir).is_absolute()):
            raise ValueError("credential_state_dir must be an explicit absolute directory")
        outside_package(credential_file, state_dir)
    elif credential_file is not None or state_dir is not None:
        raise ValueError("credential_file/credential_state_dir require explicit private_file source")
    if source == "host_command":
        if not isinstance(command, str) or not Path(command).is_absolute():
            raise ValueError("host_command needs an explicit absolute executable credential_command")
    elif command is not None:
        raise ValueError("credential_command requires host_command source")
    if auth_mode != "env_token" and (source != "env" or mapping or policy != "host" or method is not None):
        raise ValueError("Credential source and refresh options require env_token mode")
    return Settings(name, account, server, data["mode"], auth_mode, token_env_var, source, mapping,
                    credential_file, command, policy, method, skew, allow_extra_delete_scope, state_dir, backend, http_protocol)


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
    if "DeleteMessage" in tools and "mail:delete" not in settings.scopes:
        raise RuntimeError("Deletion requires mail:delete and manage mode")
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
