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

from mail_config import (MODES, codex_binary, data_home, load_settings, overrides,
                         profile_name, profile_path, select_profile, settings_from, write_private)


def doctor():
    binary = codex_binary()
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, check=True)
        help_result = subprocess.run([binary, "app-server", "--help"], capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Codex CLI could not report its version/app-server capabilities") from error
    if "--listen" not in help_result.stdout:
        raise RuntimeError("Codex app-server lacks --listen; use a compatible Codex CLI")
    return {"platform": platform.system(), "python": platform.python_version(), "codex": version.stdout.strip(),
            "profile": profile_name(), "profile_exists": profile_path().exists(), "data_home": str(data_home()),
            "transport": "stdio", "credentials": "Codex secure keyring (availability confirmed at OAuth/verify)"}


def configure(account, mode="read", server=None):
    name = profile_name()
    path = profile_path()
    previous = load_settings() if path.exists() else None
    settings = settings_from({"profile": name, "account": account, "mode": mode,
                              "server": server or (previous.server if previous else "qq-mail-" + name)})
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
    # Inherit the terminal for the real Codex authorization flow. Never capture tokens.
    command = [codex_binary(), "mcp", "login", settings.server,
               "--scopes", ",".join(settings.scopes), *overrides(settings)]
    try:
        subprocess.run(command, check=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Official Codex OAuth did not complete; profile remains unverified") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="Local mailbox profile; default: QQ_MAIL_PROFILE or default")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check runtime without starting OAuth or accessing mail")
    commands.add_parser("verify", help="Read GetMe and verify exact account and granted scopes")
    commands.add_parser("login", help="Reauthorize the selected configured profile and verify it")
    init = commands.add_parser("init")
    init.add_argument("--account", required=True, help="Intended QQ Mail or Foxmail alias")
    init.add_argument("--mode", choices=MODES, default="read")
    init.add_argument("--server", help="Use an existing real Codex MCP name when migrating; otherwise profile-specific")
    group = init.add_mutually_exclusive_group()
    group.add_argument("--reuse-auth", action="store_true", help="Reuse this machine's existing official authorization; still verify GetMe")
    group.add_argument("--configure-only", action="store_true", help="Write non-secret settings only; explicitly leaves authentication/verification pending")
    args = parser.parse_args()
    if args.profile:
        select_profile(args.profile)
    runtime = doctor()
    if args.command == "doctor":
        result = runtime
    elif args.command == "verify":
        result = asyncio.run(verify())
    elif args.command == "login":
        login(load_settings())
        result = asyncio.run(verify())
    else:
        settings = configure(args.account, args.mode, args.server)
        if args.configure_only:
            result = {"state": "configured_not_verified", **settings.as_dict(), "next": "onboard.py login"}
        else:
            if not args.reuse_auth:
                login(settings)
            result = asyncio.run(verify())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11+ is required")
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, asyncio.TimeoutError) as error:
        print(f"Onboarding incomplete: {error}", file=sys.stderr)
        sys.exit(1)
