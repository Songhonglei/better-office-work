# Workflows

All commands use `"$SKILL_DIR/scripts/music"`, abbreviated below as `$MUSIC`. Select a config with the global `--config` option or `LOCAL_MUSIC_CONFIG`. Run jobs serially; optional jobs use their separate configured Python. No generation command downloads anything.

```sh
MUSIC="$SKILL_DIR/scripts/music"
"$MUSIC" preflight
"$MUSIC" doctor
"$MUSIC" test short --precision 8bit
"$MUSIC" test short --precision bf16
"$MUSIC" test chinese-full
"$MUSIC" generate ./request.json --require-natural
"$MUSIC" generate ./request.json --precision bf16 --dry-run
"$MUSIC" precision 8bit
```

The request format is the native CLI JSON, not the upstream convenience helper's rewritten format:

```json
{
  "id": "evening-song",
  "style": "Mandarin, warm piano pop, intimate female voice, 88 BPM",
  "lyrics": "[Verse]\n晚风轻轻翻过书页\n灯火陪我走过长街\n\n[Chorus]\n把今天唱给明天\n让微光停在眼前",
  "cot": "full",
  "seed": 310021,
  "generation_config": {
    "ode_steps": 32,
    "abc": {"max_tokens": 8192},
    "semantic": {"max_tokens": 12000}
  }
}
```

Use `abc` for embedded score text, or `abc_path` relative to the request file. `full` supports melody/chords; `melody` requires no chord labels; `off` ignores the score. Max-token budgets are ceilings, not exact duration guarantees. Do not shrink a full-song budget to force an acceptance pass.

## Plan, edit, render and replay

```sh
"$MUSIC" plan ./request.json --name song-plan --require-natural
"$MUSIC" render-plan /path/to/song-plan/artifacts --require-natural
"$MUSIC" replay /path/to/completed-song/artifacts --stage decode
"$MUSIC" replay /path/to/completed-song/artifacts --stage synthesize
```

Keep native saved plans immutable: directly editing a hashed `score.abc` invalidates the plan. For score changes, copy score text into a new request and create a new plan/generation. Replay decode uses saved latent through VAE; synthesize uses saved semantic/noise through NAR/VAE. For a strict 8/32-step NAR comparison use saved semantic/noise and the upstream `skills/yue2-music/scripts/compare_steps.py`; inspect its current help, pass explicit configured model/VAE/project and a fresh output, and keep the same deployment lock. This comparison is distinct from regenerating the song with different AR precision.

## Evaluation matrix

`test smoke` runs natural-ending piano-control 8bit and bf16-complete. `test expanded` runs the 13 cases in `assets/matrix.json`, with requests in `assets/requests/`: capped repeat diagnostic, piano/dance styles, melody mode, reharmony, tempo, seed, Chinese ballad, English folk, Japanese plan→render, Chinese rap off mode, instrumental jazz, BF16. The historical repeat source path has intentionally been removed. Equality against an old audio file is not claimed without supplying that external reference.

Each suite gets a fresh timestamped prefix and `.suite.json`. It stops at a failed or review-needed case or elevated pressure; it never silently skips a failure. Existing output names fail rather than overwrite. The full matrix has not been rerun merely to validate this wrapper; previous model evidence and new wrapper verification are recorded separately.

## Serial batch

One native request JSON per UTF-8 line, each with a unique safe `id`:

```sh
"$MUSIC" batch ./songs.jsonl
```

The wrapper intentionally creates a fresh batch. The upstream native `batch --resume` and incompatible-resume rejection were verified previously, but a resume command is not exposed by this wrapper yet. To resume manually, inspect the native help, acquire the same deployment lock, supply identical request/config/weights and preserve existing receipts; never implement resume by overwriting files or ignoring integrity errors.

## Optional audio input

Read migration.md before first use, including optional model license limits. The following work only after extras Python, ffmpeg, checkpoints and cache are configured:

```sh
"$MUSIC" transcribe ./source.flac --task full --require-natural
"$MUSIC" cover ./new-style-request.json --audio ./source.flac --task melody-full --require-natural
"$MUSIC" realaudio ./source.flac
```

For cover remove `abc`/`abc_path` from the request; the audio provides the score. The RealAudio command performs stock/adapted 32/8-step reconstruction comparison, not a guarantee of voice identity or arbitrary editing. This wrapper uses the upstream comparison's seed/style defaults; use the native CLI with reviewed explicit arguments for a more tightly controlled experiment. Additional files are not automatically downloaded. Prior tests used self-generated and synthetic source audio; they do not establish general transcription accuracy on commercial recordings or voice cloning.

Listen for vocal pronunciation, missing/repeated lyrics, melody adherence, rhythm, ending, artifacts and style. Rate those separately from hashes, audio finiteness, speed and memory. Instrumental voice absence and hard BPM adherence remain soft controls.
