---
name: local-music-creation
description: Create, reproduce, and evaluate local music with YuE2 MLX on Apple Silicon Macs, including lyrics-to-song, ABC score control, precision comparison, transcription, and cover workflows. Use the configured isolated runtime and portable scripts; ComfyUI integration is a separate task.
---

# Local Music Creation

Use the bundled runner to call the verified native YuE2 MLX CLI. Keep the core MLX environment separate from optional audio-input dependencies and from Qwen/ComfyUI. No weights or virtual environments are embedded in this skill.

## First use

`SKILL_DIR` below means the directory containing this file, resolved at runtime; do not paste a previous machine's absolute path.

1. Read [configuration.md](references/configuration.md). Run `"$SKILL_DIR/scripts/music" show-config`. If missing, run `init-config`; use `--root` or edit JSON for this Mac's installation. Configuration lookup: `--config` > `LOCAL_MUSIC_CONFIG` > `${XDG_CONFIG_HOME:-~/.config}/local-music-creation/config.json`. Never overwrite an existing config.
2. Run `preflight`, then `doctor` (includes full model hashes) before the first generation on a new machine. For missing environment or models, read [migration.md](references/migration.md). Do not upgrade an existing deployment to fix discovery errors.
3. Choose a request JSON and precision. Default is AR 8bit; NAR remains BF16 and VAE FP32. BF16 changes AR, and does not promise better music. `--precision` overrides one job; `precision bf16` changes only this skill's default JSON setting. No conversion or download occurs during generation.
4. Use `--dry-run` when checking configured arguments. Execute the requested workflow and report the saved receipt plus playable audio/score. [workflows.md](references/workflows.md) lists exact commands and evaluation cases.

## Creative workflow

Turn the user's intent into a request with `style`, section-tagged `lyrics`, `cot` (`full`, `melody`, `off`), and a fixed integer `seed`; optionally supply `abc` or `abc_path`. Preserve the source request in the job receipt. Use `plan` then `render-plan` when the user wants to review or edit the score first. Keep melody mode free of chord labels. `off` bypasses score conditioning, not vocals. For instrumental music use the bundled `instrumental-jazz.json` pattern (Ins notes, Vocal rests, no lyric lines); the upstream convenience helper has open issues. Never promise zero vocals.

For comparison change one factor at a time and retain seed/requests. `test short` is intentionally capped and cannot prove a full song. `test smoke` checks natural-ending 8bit/BF16 cases; `test expanded` reruns 13 portable scenario requests and the plan/render stage. Only run the larger matrix when the user requests evaluation. A new wrapper smoke test need not repeat every expensive model benchmark.

## Operational invariants

- Generation is offline, serial per deployment, and defaults to AC power, 16 GiB budget and 256-frame VAE chunks. Preflight blocks elevated memory pressure and insufficient disk. The native resource monitor records power, process and MLX memory and aborts power/critical-pressure problems. Do not silently lower precision, token budget or completeness requirements to hide failures.
- Each job gets a fresh directory with `input.json` (when applicable), `execution.json`, `run.log`, `resources.json` and native artifacts. Existing names are rejected. Timeout/cancellation terminates only that job's child process group and retains its receipt.
- Do not stop Qwen, ComfyUI or unrelated processes automatically. If memory blocks work, inspect the cause and follow the current user's specific authorization; preserve models/configuration and log any authorized stop. Authorization from the original installation is not a universal permission on another Mac.
- Code/model/dependency updates to this user's existing deployment require their explicit confirmation. Fresh migration setup is a separate explicit action. The skill does not submit issues/PRs or schedule upstream monitoring.
- Distinguish artifact integrity, finite/non-silent 48 kHz stereo audio, natural ending and measured speed/memory from subjective music quality. A limited diagnostic can pass technically while truncated. Report truncation and unrated listening quality clearly.
- Optional `transcribe`, `cover` and `realaudio` need a configured extras Python and verified optional weights; fail with a clear missing prerequisite rather than installing packages into the core environment. Additional model licenses are documented in migration.md.

## References

- [configuration.md](references/configuration.md): every configurable field, path expansion and output contract.
- [workflows.md](references/workflows.md): generation, score planning, replay, batch, audio-input workflows and reproducible evaluation.
- [migration.md](references/migration.md): transferring to another Mac, fresh frozen setup, hash verification and limits of what was tested.
- [provenance.md](references/provenance.md): pinned source/model baseline, known upstream issues and evidence boundaries.
