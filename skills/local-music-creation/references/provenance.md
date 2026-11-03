# Baseline and known limitations

- Native source: https://github.com/vanch007/mlx-Yue at `c5b5a8190f78c74aa671a4caa19dae8b8e04b3d8`.
- Core converted model: https://huggingface.co/vanch007/mlx-Yue2-3B at `5f7620e546fb3c6130a09a7e18172e3bb7aaeddb`.
- Python 3.12.13; uv 0.12.3; MLX 0.32.2; mlx-lm 0.31.3. Main dependency metadata is frozen in assets/frozen with SHA-256 in its manifest. Only urllib3 was updated from the original source's pin to the previously verified 2.8.0.
- Model file hashes are bundled from the successfully verified pinned public snapshot; this is distinct from blindly trusting a downloaded model's own manifest. Doctor verifies the strict native runtime layout.
- Previous testing on the original M5 Pro included 13 scenarios, plan/render, batch/resume, replay, score edits, transcription, cover and RealAudio. Those historical results do not establish new wrapper coverage automatically, cross-Mac determinism or subjective quality.
- A short capped sample is useful for a quick environment check. `semantic=true` in truncation means it is not a natural-ended full song.
- Instrumental convenience entry points have missing canonical modules ([Issue #2](https://github.com/vanch007/mlx-Yue/issues/2)); configure drops the instrumental flag ([Issue #3](https://github.com/vanch007/mlx-Yue/issues/3)). Native generation with Ins notes/Vocal rests is the verified workaround, with no guarantee of complete vocal suppression.
- The raw Hub snapshot contains metadata/subdirectories rejected by strict generator validation ([Issue #4](https://github.com/vanch007/mlx-Yue/issues/4)). Do not relax integrity validation; stage separate generator/VAE trees.
- Dependency candidate and security rationale: [Issue #5](https://github.com/vanch007/mlx-Yue/issues/5). These are open reports as of publication, not evidence that upstream has merged a fix.

The existing weekly monitor belongs to the original task and is not installed or duplicated by this portable skill. Runtime update confirmation remains the current user's decision.
