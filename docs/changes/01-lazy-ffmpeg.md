# 01 — Lazy ffmpeg resolution (System 3 boots without ffmpeg)

## What changed
`settings.FFMPEG_DIR` is no longer computed at import time. It is resolved on
first read via a module-level `__getattr__`, then cached. The lookup order and
error message are unchanged (`ANTAHAI_FFMPEG_DIR` → WinGet default path →
`ffmpeg` on `PATH` → `RuntimeError`). A failed lookup is not cached.

## Why
`settings.py` raised `RuntimeError: ffmpeg not found` on import, so System 3
(and `smoke_e2e.py`, and `ANTAHAI_FAKE_QUIZ=1` demo mode) could not start on any
machine without ffmpeg, even though ffmpeg is only needed for real video quizzes.

## Files
- `System-3 Complete_Linker/settings.py`

Not touched: `s2_bridge.py` (still reads `settings.FFMPEG_DIR` in
`ensure_ready()`, now the point where resolution happens), System 1,
`mcq_generator.py`.

## Behaviour
- App start, login, intake, results, profile, fake quizzes: no ffmpeg needed.
- Real quiz generation without ffmpeg: the background job fails and the attempt
  is marked `error` with the same "ffmpeg not found…" message (was: app would
  not start at all).
- With ffmpeg installed/configured: identical to before.

## Testing
- `python -c "import settings"` without ffmpeg: failed before, passes now.
- `settings.FFMPEG_DIR`: raises the same `RuntimeError` without ffmpeg; honours
  `ANTAHAI_FFMPEG_DIR`; finds `ffmpeg` on `PATH`; unknown attributes still
  raise `AttributeError`.
- `smoke_e2e.py`: crashed on import before; now 24 passed, 0 failed.
- `_run_quiz_job` with fake quiz off and no ffmpeg: attempt stored as `error`
  with the ffmpeg message.

## Rollback
`git revert <this commit>` — or restore the last line of the ffmpeg block in
`settings.py` to `FFMPEG_DIR = _resolve_ffmpeg_dir()`.
