# Configuration

The controller uses only Python 3.9+ standard library; the configured MLX runtime must be Python 3.12. Keep the skill portable by locating resources relative to its own file, never by username.

Initialize once:

```sh
"$SKILL_DIR/scripts/music" init-config
# Alternative installation and separate profile:
"$SKILL_DIR/scripts/music" --config ./studio.json init-config --root /Volumes/AudioLab/YuE2-MLX
"$SKILL_DIR/scripts/music" --config ./studio.json show-config
```

Default configuration lives at `${XDG_CONFIG_HOME:-$HOME/.config}/local-music-creation/config.json`. `LOCAL_MUSIC_CONFIG` selects another file; `--config` has highest priority and must precede the command. The bundled `assets/config.example.json` is a complete example. No config is written into the skill's own folder.

`~` and existing environment variables expand. `{root}` expands to the configured installation root, `{skill}` to the current skill folder. Other relative paths are relative to the configuration file's directory, not the current working directory. Missing variables fail explicitly. Paths containing spaces are supported; no shell is used to execute jobs. Interpreter symlinks are preserved to retain the virtual environment.

| Field | Meaning |
| --- | --- |
| `schema` | Must be `1` |
| `root` | Installation/deployment root and shared job lock location |
| `expected_commit` | Reviewed source revision; mismatch blocks generation |
| `paths.source` | Local mlx-Yue Git checkout |
| `paths.python` | Core environment's `bin/python` (not global Python) |
| `paths.model` / `paths.vae` | Separate, strict validated generator and VAE trees |
| `paths.snapshot` | Complete pinned Hub snapshot for verification/staging |
| `paths.output` | Parent of all new job directories and suite receipts |
| `paths.cache` | Private Hugging Face, XDG and uv caches |
| `paths.extras_python` | Optional, independent transcription/cover/RealAudio environment |
| `paths.sheetsage` / `paths.mert` | Verified local SheetSage2 and MERT checkpoint directories |
| `paths.realaudio` | Preconverted RealAudio tokenizer/LoRA directory |
| `paths.hf_cache` | Optional models' offline Hub cache; see migration instructions |
| `paths.ffmpeg_bin` | Optional directory containing the ffmpeg executable |
| `runtime.precision` | Default AR precision: `8bit` or `bf16` |
| `runtime.memory_budget_gib` | Native memory budget, default 16 GiB; not a guarantee of total system headroom |
| `runtime.vae_core_frames` | VAE chunk size, default 256 |
| `runtime.require_ac` | Default true; false is an explicit opt-out, recorded in each job |
| `runtime.min_free_disk_gib` | Free disk preflight threshold, default 10 GiB |
| `runtime.timeout_seconds` | Per-process limit, default 7200 seconds |

Command-line precision overrides the default for one job. `precision 8bit` or `precision bf16` edits only the selected profile, without modifying the original deployment's `settings.json` or weights. Output directory names must be unique ASCII labels; otherwise timestamp plus random suffix is used. The original non-ASCII inputs and lyrics remain UTF-8.

## Job contract

Jobs produce `<paths.output>/<name>/execution.json`, `run.log`, `resources.json`, and native `artifacts/` (FLAC, ABC if present, arrays, result/config/manifest). Requests are normalized and copied into `input.json`; an `abc_path` is resolved relative to the original request. Plan jobs contain native plan artifacts; cover places the finished song in `artifacts/song/`; transcription contains score/MIDI/labels. Doctor writes `doctor.json` at the job root. `batch` uses `input.jsonl` and verifies every returned song.

Receipts record resolved arguments, source revision, selected precision, power, wall time, memory counters, checks and truncation. These are local operational records and may contain local absolute paths; do not post them publicly without reviewing/redacting. Sharing the skill ZIP does not share these records.

Result statuses: `passed`, `needs_review`, `failed`, `cancelled`, `timed_out`. A successful capped diagnostic may have `natural_end=false`; a natural-ending test cannot pass if truncated. Subjective quality stays `unrated` until a human listens. `--dry-run` checks prerequisites and shows arguments but creates no job or inference process. `preflight` reports power but allows inspection on battery; actual jobs enforce the configured AC requirement.
