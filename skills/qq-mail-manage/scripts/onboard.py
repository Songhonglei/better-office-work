#!/usr/bin/env python3
"""Initialize portable QQ Mail profiles and authorize the real local Codex CLI."""
import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone

from mail_config import (MODES, AUTH_MODES, DEFAULT_TOKEN_ENV, codex_binary, data_home, load_settings, overrides,
                         profile_name, profile_path, select_profile, settings_from, write_private,
                         validate_token_env_var, subprocess_env, redact)
from mail_credentials import SOURCES, POLICIES, CLIENT_AUTH, ENV_FIELDS


def apply_credential_options(data, options):
    source = options.get("credential_source")
    if source is not None and source != data.get("credential_source", "env"):
        for key in ("credential_file", "credential_command", "refresh_policy", "client_auth_method"):
            data.pop(key, None)
    data.update({key: value for key, value in options.items() if value is not None})


def doctor(settings=None, *, auth_mode=None, token_env_var=None, **credential_options):
    if settings is None and profile_path().exists():
        settings = load_settings()
    mode = auth_mode or (settings.auth_mode if settings else "oauth_keyring")
    name = token_env_var if token_env_var is not None else (settings.token_env_var if settings and settings.auth_mode == mode else None)
    if mode == "env_token":
        name = validate_token_env_var(DEFAULT_TOKEN_ENV if name is None else name)
    elif name is not None:
        raise ValueError("token_env_var is only valid in env_token mode")
    diagnostic_data = settings.as_dict() if settings and settings.auth_mode == mode else {
        "profile": profile_name(), "account": "diagnostic@qq.com", "server": "qq-mail-diagnostic", "mode": "read"}
    diagnostic_data.update(auth_mode=mode, token_env_var=name)
    apply_credential_options(diagnostic_data, credential_options)
    diagnostic = settings_from(diagnostic_data)
    env = subprocess_env(diagnostic, extra_names=(name,))
    binary = codex_binary()
    try:
        version = subprocess.run([binary, "--version"], env=env, capture_output=True, text=True, timeout=15, check=True)
        help_result = subprocess.run([binary, "app-server", "--help"], env=env, capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Codex CLI could not report its version/app-server capabilities") from None
    if "--listen" not in help_result.stdout:
        raise RuntimeError("Codex app-server lacks --listen; use a compatible Codex CLI")
    last_verified = None
    if settings and profile_path().exists():
        last_verified = json.loads(profile_path().read_text()).get("verified_at")
    mapping = {**ENV_FIELDS, **diagnostic.credential_env_vars, "access_token": name}
    return {"platform": platform.system(), "python": platform.python_version(), "codex": redact(version.stdout.strip()),
            "profile": profile_name(), "profile_exists": profile_path().exists(), "data_home": str(data_home()),
            "transport": "stdio", "auth_mode": mode, "token_env_var": name,
            "token_variable_present": bool(name and name in os.environ),
            "token_variable_nonempty": bool(name and os.environ.get(name, "").strip()),
            "credentials": "runtime access-token variable" if mode == "env_token" else "Codex secure keyring",
            "credential_source": diagnostic.credential_source if mode == "env_token" else "Codex keyring",
            "refresh_policy": diagnostic.refresh_policy, "client_auth_method": diagnostic.client_auth_method,
            "credential_variables": {field: {"name": var, "present": bool(var and var in os.environ)}
                                     for field, var in mapping.items()} if mode == "env_token" else {},
            "persistence": "host responsibility; environment variables are not persistent storage",
            "store_inspected": False, "refresh_attempted": False,
            "credential_status": "previously_verified" if last_verified else "unverified",
            "last_verified_at": last_verified, "currently_verified": False}


def configure(account, mode="read", server=None, auth_mode=None, token_env_var=None, **credential_options):
    name = profile_name()
    path = profile_path()
    previous = load_settings() if path.exists() else None
    chosen_auth = auth_mode or (previous.auth_mode if previous else "oauth_keyring")
    chosen_var = token_env_var
    if chosen_auth == "env_token" and chosen_var is None:
        chosen_var = previous.token_env_var if previous and previous.auth_mode == "env_token" else DEFAULT_TOKEN_ENV
    data = previous.as_dict() if previous and previous.auth_mode == chosen_auth else {}
    data.update(profile=name, account=account, mode=mode, auth_mode=chosen_auth,
                token_env_var=chosen_var, server=server or (previous.server if previous else "qq-mail-" + name))
    apply_credential_options(data, credential_options)
    settings = settings_from(data)
    if path.exists():
        if previous.account != settings.account or previous.server != settings.server:
            raise ValueError("An existing profile cannot be rebound to a different account/server; choose a new profile")
    if path.parent.exists():
        for other in path.parent.glob("*.json"):
            if other == path:
                continue
            item = json.loads(other.read_text(encoding="utf-8"))
            if item.get("server") == settings.server:
                raise ValueError("Each profile requires its own MCP server name; credentials must not be shared implicitly")
    # Validate inherited transport/auth before even persisting the new profile.
    overrides(settings)
    # A local non-secret profile; no global Codex config or OAuth files are edited.
    write_private(path, settings.as_dict())
    return settings


async def verify():
    from qq_mail import CodexMail
    async with CodexMail() as mail:
        if mail.status["missing_scopes"]:
            raise RuntimeError("Configured permissions were not fully granted; complete OAuth or select read mode")
        result = {"state": "verified", **mail.status}
    data = load_settings().as_dict()
    data["verified_at"] = datetime.now(timezone.utc).isoformat()
    write_private(profile_path(), data)
    return result


def login(settings):
    if settings.auth_mode != "oauth_keyring":
        raise RuntimeError("env_token never starts OAuth login; securely update the access-token variable, then run verify")
    # Inherit the terminal for the real Codex authorization flow. Never capture tokens.
    command = [codex_binary(), "mcp", "login", settings.server,
               "--scopes", ",".join(settings.scopes), *overrides(settings)]
    try:
        subprocess.run(command, env=subprocess_env(settings), check=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Official Codex OAuth did not complete; profile remains unverified") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Local mailbox profile; default: QQ_MAIL_PROFILE or default")
    commands = parser.add_subparsers(dest="command", required=True)
    diagnostic = commands.add_parser("doctor", help="Check runtime without starting OAuth or accessing mail")
    diagnostic.add_argument("--auth-mode", choices=AUTH_MODES)
    diagnostic.add_argument("--token-env-var", help="Variable name only, never its value")
    commands.add_parser("verify", help="Read GetMe and verify exact account and granted scopes")
    commands.add_parser("login", help="Reauthorize the selected configured profile and verify it")
    init = commands.add_parser("init")
    init.add_argument("--account", required=True, help="Intended QQ Mail or Foxmail alias")
    init.add_argument("--mode", choices=MODES, default="read")
    init.add_argument("--auth-mode", choices=AUTH_MODES, help="Defaults to existing profile mode or oauth_keyring")
    init.add_argument("--token-env-var", help="Name of the injected official MCP access-token variable; never its value")
    for command in (init, diagnostic):
        command.add_argument("--credential-source", choices=SOURCES)
        command.add_argument("--credential-file", help="Explicit unencrypted private-file adapter; absolute path outside repositories")
        command.add_argument("--credential-command", help="Trusted host credential adapter executable (absolute path; no shell)")
        command.add_argument("--credential-env", action="append", metavar="FIELD=VARIABLE", help="Credential field to variable-name mapping; never values")
        command.add_argument("--refresh-policy", choices=POLICIES)
        command.add_argument("--client-auth-method", choices=CLIENT_AUTH, help="Required for auto; use the original issuing client's method")
        command.add_argument("--refresh-skew", type=int, help="Refresh this many seconds before expiry; default 120")
    init.add_argument("--server", help="Use an existing real Codex MCP name when migrating; otherwise profile-specific")
    group = init.add_mutually_exclusive_group()
    group.add_argument("--reuse-auth", action="store_true", help="Reuse this machine's existing official authorization; still verify GetMe")
    group.add_argument("--configure-only", action="store_true", help="Write non-secret settings only; explicitly leaves authentication/verification pending")
    args = parser.parse_args()
    if args.profile:
        select_profile(args.profile)
    options = {}
    if args.command in ("init", "doctor"):
        options = {key: getattr(args, key) for key in ("credential_source", "credential_file", "credential_command",
                   "refresh_policy", "client_auth_method", "refresh_skew")}
        if args.credential_env is not None:
            try:
                mapping = dict(item.split("=", 1) for item in args.credential_env)
            except ValueError:
                raise ValueError("Use --credential-env FIELD=VARIABLE (names only)") from None
            options["credential_env_vars"] = mapping
    if args.command == "doctor":
        result = doctor(auth_mode=args.auth_mode, token_env_var=args.token_env_var, **options)
    elif args.command == "verify":
        doctor()
        result = asyncio.run(verify())
    elif args.command == "login":
        login(load_settings())
        result = asyncio.run(verify())
    else:
        settings = configure(args.account, args.mode, args.server, args.auth_mode, args.token_env_var, **options)
        doctor(settings)
        if args.configure_only:
            result = {"state": "configured_not_verified", **settings.as_dict(), "next": "onboard.py verify" if settings.auth_mode == "env_token" else "onboard.py login"}
        else:
            if settings.auth_mode == "oauth_keyring" and not args.reuse_auth:
                login(settings)
            result = asyncio.run(verify())
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11+ is required")
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, asyncio.TimeoutError) as error:
        print(redact(f"Onboarding incomplete: {error}"), file=sys.stderr)
        sys.exit(1)
