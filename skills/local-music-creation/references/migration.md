# Migration to another Mac

The ZIP contains this skill, configuration example, request matrix, frozen source dependency metadata and SHA-256 manifests. It contains no model/audio files, credentials, machine config, virtual environments or caches. Copy its `local-music-creation/` directory into the target agent's discoverable skills folder (Codex normally `${CODEX_HOME:-~/.codex}/skills`). Other agents can execute the controller if they support filesystem skills, but their skill discovery is not validated here.

## Connect to an existing installation

Run `init-config --root <target-installation>`, adjust JSON paths as needed, then `show-config`, `preflight`, `doctor`, `test short --precision 8bit`. Default portable extras paths are `<root>/extras/.venv` and `<root>/extras/bin`; the current Mac profile intentionally points to its already verified extras environment. Update the local profile when migrating; do not copy another computer's resolved paths.

Do not copy `.venv` between Macs: interpreter and executable paths can retain the old prefix. Rebuild it from fixed source/dependencies. The entry script itself can run with macOS developer Python 3.9+, while inference is fixed at Python 3.12.13. Native arm64 execution is required. macOS 26.5.1 on an M5 Pro with 48 GiB is the tested baseline. Other Apple chips, RAM sizes and macOS releases need their own doctor and smoke test; no universal macOS upgrade is performed or recommended automatically. The locked MLX wheels determine the actual OS floor, and uv may reject an incompatible target.

## Fresh installation only

Have Git/Command Line Tools and uv 0.12.3 available first. If missing, explain the requirement before installing tools; this package does not invoke system installers or run downloaded shell scripts. uv is available as the exact `uv==0.12.3` Python package in an isolated user tools environment; alternatively use the official fixed release. Do not change another agent's Python environment to provide it.

```sh
"$SKILL_DIR/scripts/music" init-config --root /path/to/new/YuE2-MLX
python3 "$SKILL_DIR/scripts/migrate.py" setup
```

`setup` refuses an existing source directory. It clones the public source and checks out the fixed commit, restores bundled verified pyproject/uv.lock, installs Python 3.12.13 under the new deployment, and uses `uv sync --frozen --no-dev`. It does not regenerate the lock. The bundled metadata incorporates the locally verified urllib3 2.8.0 change; its upstream Issue is #5. Core setup does not install optional Torch packages.

Default paths assume a conventional `<root>/src/.venv`; `setup` also supports a configured alternative `<venv>/bin/python`, and refuses an existing venv. A failed fresh setup leaves files for diagnosis and refuses to overwrite them on retry; inspect them or choose a fresh root rather than force-resetting. Network downloads and a truly clean second-Mac install have not been executed as part of the packaging smoke test. The exact source+frozen metadata were verified on the current Mac.

## Models: transfer or pinned download

Transfer the complete raw `models/mlx-Yue2-3B/` tree from a trusted disk, or run the explicit download below after fresh setup:

```sh
python3 "$SKILL_DIR/scripts/migrate.py" download-models
python3 "$SKILL_DIR/scripts/migrate.py" verify-models
python3 "$SKILL_DIR/scripts/migrate.py" stage-models
"$SKILL_DIR/scripts/music" doctor
"$SKILL_DIR/scripts/music" test short --precision 8bit
"$SKILL_DIR/scripts/music" test short --precision bf16
```

`download-models` fetches only the bundled fixed snapshot revision, then verifies all listed file sizes/SHA-256. `stage-models` verifies again, builds separate strict generator and VAE trees with hardlinks and never replaces a differing target. Do not edit hardlinked weights in place. Cross-filesystem targets require `stage-models --copy` and extra storage. The full raw snapshot is about 9.73 GiB; staging on the same filesystem avoids duplicate weight data. Provision additional room for Python/packages, caches, song artifacts and arrays (roughly 25–40 GiB free is a planning allowance, not an exact minimum). Keep original license files.

## Optional extras

Transcription/cover/RealAudio require a separate environment. `assets/frozen/extras-requirements.txt` records the exact previously installed package versions (without the local editable project); it is a version-pinned inventory, not a hashed cross-platform uv lock. Create a separate Python 3.12 environment, sync that inventory with uv, then install the configured source as editable using `--no-deps`. Do not sync it into the core environment. New-machine wheel availability and optional workflow success still need validation.

Point `paths.extras_python` at that interpreter. Place an ffmpeg executable in `paths.ffmpeg_bin` (the verified extras use imageio-ffmpeg 0.6.0). The source's optional transcription dependencies are not a substitute for this full measured extras inventory.

Transfer SheetSage2 and MERT directories, then run `python3 "$SKILL_DIR/scripts/migrate.py" verify-extras` to verify files against `assets/optional-model-manifest.json` by filename/size/SHA-256 (if configured RealAudio exists it is checked too). These models are fixed at the recorded revisions. The cover implementation also resolves the model IDs through the configured Hub cache: create corresponding `models--m-a-p--SheetSage2/snapshots/<revision>/` and `models--m-a-p--MERT-v2-FullSong/snapshots/<revision>/` directories under `paths.hf_cache`, containing the verified config.json/model.safetensors (hardlinks on the same filesystem are sufficient). This is an upstream cache-layout requirement, separate from normal generation.

For RealAudio, transfer the already converted `realaudio-converted/` tree and verify it using `assets/realaudio-converted-manifest.json`. Re-conversion from public `.pt` checkpoints is optional: enforce the recorded source hashes, CPU conversion and `torch.load(weights_only=True)`; do not execute an untrusted pickle. No conversion command is automated in this skill.

The optional SheetSage2, MERT and RealAudio model cards declare CC-BY-NC-4.0. Review their fixed model cards before commercial use of those optional workflows. The core project/model carries separate licenses. This is a specific recorded model limitation, not a blanket conclusion about every generated song.

## Evidence boundary

Current-Mac wrapper tests, path/lock/cancellation checks and package validation are summarized in the delivered validation report. A simulated relocated path tests path handling; it is not a second physical Mac test. Any code, dependencies or weights newer than the bundled baseline require separate review and this user's confirmation before changing their current installation.
