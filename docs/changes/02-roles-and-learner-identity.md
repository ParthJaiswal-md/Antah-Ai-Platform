# 02 — Roles and persistent learner identity

## What changed
- `users` gains `role` (`learner` | `trainer` | `admin`, default `learner`) and
  `employee_id` (the learner's System 1 id). `db.init_db()` adds them to an
  existing database with `ALTER TABLE` (idempotent); existing accounts become
  learners with no `employee_id`.
- Self-registration always creates a learner (a `role` in the request is ignored).
- Demo trainer/admin accounts are seeded at startup from
  `ANTAHAI_TRAINER_USERNAME` / `ANTAHAI_TRAINER_PASSWORD` and
  `ANTAHAI_ADMIN_USERNAME` / `ANTAHAI_ADMIN_PASSWORD` (usernames default to
  `trainer` / `admin`; no password set = not seeded). Seeding creates the
  account or resets an existing one's password + role.
- `role_required(*roles)`: role is read from the DB on every request (role
  changes apply immediately); anonymous/deleted accounts → `/login`, wrong
  role → 403. All learner pages (`/recommendation`, results, quiz, `/profile`)
  now require `learner`. New placeholder `/trainer` (trainer, admin) and
  `/admin` (admin) dashboards.
- Login (and `/`, `/login` while logged in) redirects by role: admin →
  `/admin`, trainer → `/trainer`, learner with an `employee_id` → their latest
  recommendations, otherwise → intake (unchanged flow).
- Intake: a learner's first submission registers a System 1 employee (as
  before) and stores the id on the account. Later submissions call
  `POST /employees/compute` with that id (no new Dataset-5 row), carry over
  the quiz-verified levels System 1 holds (`GET /employees/{id}/profile`), and
  sync the new self-ratings back (`POST /employees/{id}/skills`). If System 1
  no longer knows the id (404), a new employee is registered and stored.
- Nav: brand link goes to the role's home; "Profile" is shown to learners only.

## Why
P0 #2: trainer/admin features need roles, and the score → skill update →
new recommendations loop needs one stable employee per learner.

## Files
- `System-3 Complete_Linker/db.py`, `app.py`, `s1_client.py` (additive
  wrappers for existing S1 endpoints + `S1Error.status`), `settings.py`
  (`demo_accounts()`), `templates/base.html`
- New: `templates/trainer_dashboard.html`, `templates/admin_dashboard.html`,
  `roles_e2e.py`

System 1, System 2 and `mcq_generator.py` untouched.

## Known limitations
- System 1 has no profile-update endpoint, so if a learner changes
  designation/department on a later intake, the recommendations shown use the
  new role but System 1's stored record keeps the original role.
- `POST /employees/{id}/skills` merges, so a skill left unrated in a later
  intake keeps its previous self-rating in System 1's stored record.
- Existing accounts are not backfilled (their old submissions may be for
  different employees); their next intake registers and stores an id.

## Testing
- `roles_e2e.py` (new): 43 passed, 0 failed — migration of an old-schema DB,
  fresh schema, learner-only self-registration, seeding (skip without
  password, idempotent, resets a pre-existing username), login redirects per
  role, 302/403 route protection, immediate demotion, deleted-account session,
  persistent employee_id (register once, compute after, quiz-verified carry-over,
  self-rating sync, 404 → re-register).
- `smoke_e2e.py`: 24 passed, 0 failed.
- Live check against the real System 1 (temp dataset copy): two intakes → one
  Dataset-5 row, same employee_id, quiz-verified level carried over, S1
  self-ratings updated, real Dataset-5 untouched.
- `python app.py` with the demo env vars seeds both accounts.

## Rollback
`git revert <this commit>`. The two added columns are harmless to the old code
(it never selects them by position); to drop them from a DB, recreate it or use
`ALTER TABLE users DROP COLUMN role` / `DROP COLUMN employee_id` (SQLite ≥ 3.35).
