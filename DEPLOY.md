# Deploying AntahAI

There are two deployable editions. They share one recommendation engine
(`pathways/engine.py`, ported line for line to `demo/engine.js`; a parity check
confirms that both produce identical output for every demo learner and goal).

| | Full web app (Flask + SQLite) | Browser edition (`demo/`) |
|---|---|---|
| Accounts / login | Server accounts (register, log in) | Pick a demo learner or type a name |
| Storage | SQLite on a persistent disk | Each visitor's browser |
| Round-1 role recommender | Yes (needs System-1 running) | No |
| Resume upload | .txt and .pdf | .txt or pasted text |
| Hosting | Any Docker host (Render blueprint included) | Any static host, or the published claude.ai page |

## 1. Full web app on Render (recommended for judges)

Everything needed is in the repo: `Dockerfile`, `render.yaml`, `wsgi.py`,
`System-3 Complete_Linker/requirements-web.txt` and a `/healthz` endpoint.

1. Sign in at https://render.com with the GitHub account that owns this repository.
2. Open https://render.com/deploy?repo=https://github.com/ParthJaiswal-md/Antah-Ai-Platform
   and choose the branch `feature/learning-pathways-roadmap` (or merge it into `main` first).
3. Click **Apply**. Render builds the Docker image and attaches a 1 GB disk at `/data`
   for `antahai.db`. It also generates `ANTAHAI_SECRET`, so logins survive restarts.
4. When the health check at `/healthz` turns green, open `https://<service>.onrender.com/login`
   and log in as `demo_asha` or `demo_ravi` (password `demo1234`).

Notes
- The persistent disk needs a paid instance (`plan: starter`). On the free plan,
  change `plan` to `free` and remove the `disk` block. The app still works, but
  data resets when the instance restarts.
- On first start the app creates its tables, loads the course catalogue, imports
  the department list and creates the two demo learners.
- The Round-1 video quiz generator (System 2: Whisper, ffmpeg, Groq) is not in
  the image. The Learning Pathways features do not use it.

Any other Docker host works the same way: `docker build -t antahai . && docker run -p 8080:8080 -v antahai-data:/data antahai`.

## 2. Browser edition

`demo/index.html` plus its scripts and stylesheets. All logic runs in the
browser, and progress is stored in the browser. It is published as a claude.ai
page; to host it elsewhere, copy `demo/` together with `style.css`,
`pathways.css`, `pw-common.js` and `roadmap.js` from
`System-3 Complete_Linker/static/` into one folder, then add a
`<!doctype html><html><head><meta charset="utf-8"></head><body>` wrapper
around `index.html`.

## Verified locally before publishing

- 49 pathway unit, service and HTTP tests, plus the 24 Round-1 smoke checks.
- The production entry point (`wsgi:app`) run from the same file layout the
  Dockerfile produces, on a fresh database in a separate data folder.
- Browser run of the full journey on that server: register → log in → profile
  → resume upload → confirm a suggestion → gaps and recommendations → generate
  roadmap → open a course from the dashboard roadmap → quiz fail and targeted
  revision → retry and pass → validated competency → roadmap recalculated →
  log out and back in with progress kept.
