"""Portable, non-secret profiles; OAuth remains exclusively in Codex's keyring."""
import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ENDPOINT = "https://api.mail.qq.com/mcp"
READ_TOOLS = ("GetMe", "ListMessages", "SearchMessages", "GetMessage", "ListAttachments", "DownloadAttachment")
WRITE_TOOLS = ("SendMessage", "ReplyMessage", "ForwardMessage", "DeleteMessage")
MODES = {"read": ("mail:read",), "manage": ("mail:read", "mail:send", "mail:delete")}


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
            json.dump(value, stream, ensure_ascii=False, indent=2)
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

    @property
    def scopes(self):
        return MODES[self.mode]

    @property
    def state_dir(self):
        return data_home() / "state" / self.profile

    def as_dict(self):
        return {"version": 1, "profile": self.profile, "account": self.account, "server": self.server, "mode": self.mode}


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
        raise ValueError("Mode must be read or manage")
    return Settings(name, account, server, data["mode"])


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
        raise RuntimeError("This bridge currently supports macOS/Linux; use WSL with a working secure keyring on Windows")
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
        'mcp_oauth_credentials_store="keyring"',
        key + '.url=' + json.dumps(ENDPOINT),
        key + '.enabled=true',
        key + '.scopes=' + json.dumps(settings.scopes),
        key + '.enabled_tools=' + json.dumps(tools),
        key + '.disabled_tools=[]',
        key + '.default_tools_approval_mode=' + json.dumps("auto" if automatic else "prompt"),
        key + '.startup_timeout_sec=30',
    ]
    # Suppress unrelated configured servers only in this child process.
    config = codex_home() / "config.toml"
    if config.exists():
        servers = tomllib.loads(config.read_text(encoding="utf-8")).get("mcp_servers", {})
        selected = servers.get(settings.server)
        if selected is not None:
            safe_fields = {"url", "enabled", "scopes", "enabled_tools", "disabled_tools", "default_tools_approval_mode", "startup_timeout_sec", "tool_timeout_sec"}
            if not isinstance(selected, dict) or selected.get("url") != ENDPOINT or set(selected) - safe_fields:
                raise RuntimeError("The chosen MCP name conflicts with existing transport/auth configuration; onboard a new profile/server name instead")
        for server in servers:
            if server != settings.server:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", server):
                    raise RuntimeError("An unrelated MCP name cannot be safely overridden; rename that server to letters/digits/hyphens/underscores")
                values.append("mcp_servers." + server + ".enabled=false")
    return [arg for value in values for arg in ("-c", value)]
