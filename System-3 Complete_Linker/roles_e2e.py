"""
Offline tests for roles, login redirects, the users-table migration and the
learner's persistent System 1 employee_id.

Same style as smoke_e2e.py: Flask test client, temp SQLite DB, System 1's
client functions stubbed (no servers, network, or LLM needed).

Run with the System 2 venv python:
    ".venv/Scripts/python.exe" roles_e2e.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# ---- env must be set before importing app/db/settings --------------------
TMP = tempfile.mkdtemp(prefix="antahai_roles_")
os.environ["ANTAHAI_DB"] = os.path.join(TMP, "antahai.db")
os.environ["ANTAHAI_FAKE_QUIZ"] = "1"
os.environ["ANTAHAI_SECRET"] = "roles-test-secret"

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import s1_client  # noqa: E402
from app import app, seed_demo_accounts  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


# ---------------------------------------------------------------------------
# Stub System 1: an in-memory employee store with call counters
# ---------------------------------------------------------------------------
S1 = {"employees": {}, "next": 900, "calls": {"register": 0, "compute": [], "skills": []}}


def _meta_roles():
    return [{"role_id": "R001", "designation": "Junior Statistical Officer", "department": "NSO"}]


def _meta_skills():
    return [{"skill_id": "S001", "skill_name": "AI/ML"}, {"skill_id": "S002", "skill_name": "Communication"}]


def _response(employee):
    return {
        "employee": employee,
        "gaps": [],
        "recommendations": [{
            "course_id": "C001", "course_title": "Intro", "description": "d",
            "target_level": 2, "duration_minutes": 60, "mode": "self-paced",
            "provider": "iGOT", "language": "English", "matched_skills": ["S001"], "score": 1.0,
        }],
        "unmatched_gaps": [],
    }


def _echo(payload, employee_id):
    return {
        "employee_id": employee_id, "name": payload.get("name") or "",
        "role_id": payload["role_id"], "designation": payload.get("designation") or "",
        "department": payload.get("department") or "",
        "current_assignment": payload.get("current_assignment"),
        "educational_qualifications": payload.get("educational_qualifications"),
        "work_experience_years": payload.get("work_experience_years"),
        "previous_trainings": payload.get("previous_trainings") or [],
        "self_rated_skills": payload.get("self_rated_skills") or {},
        "quiz_verified_skills": payload.get("quiz_verified_skills") or {},
    }


def _register_employee(payload, top_n=5):
    S1["calls"]["register"] += 1
    employee_id = f"E{S1['next']}"
    S1["next"] += 1
    employee = _echo(payload, employee_id)
    S1["employees"][employee_id] = employee
    return _response(employee)


def _get_employee_profile(employee_id):
    if employee_id not in S1["employees"]:
        raise s1_client.S1Error(f"Employee {employee_id} not found", 404)
    return S1["employees"][employee_id]


def _compute_employee(payload, top_n=5):
    S1["calls"]["compute"].append(payload)
    return _response(_echo(payload, payload.get("employee_id") or "NEW-R001"))


def _update_employee_skills(employee_id, self_rated=None, quiz_verified=None):
    S1["calls"]["skills"].append((employee_id, self_rated, quiz_verified))
    return {"employee_id": employee_id, "updated": True}


s1_client.meta_roles = _meta_roles
s1_client.meta_skills = _meta_skills
s1_client.meta_courses_light = lambda: [{"course_id": "C001", "course_title": "Intro"}]
s1_client.meta_unique_values = lambda: {"current_assignment": [], "educational_qualifications": []}
s1_client.register_employee = _register_employee
s1_client.get_employee_profile = _get_employee_profile
s1_client.compute_employee = _compute_employee
s1_client.update_employee_skills = _update_employee_skills

INTAKE = {
    "name": "Asha", "role_id": "R001", "designation": "Junior Statistical Officer",
    "department": "NSO", "work_experience_years": 3, "self_rated_skills": {"S001": 1},
}


def login(client, username, password):
    return client.post("/login", json={"username": username, "password": password})


def status_and_location(client, path):
    r = client.get(path)
    return r.status_code, r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_migration() -> None:
    print("\n[migration]")
    old_path = os.path.join(TMP, "old_schema.db")
    con = sqlite3.connect(old_path)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
                            password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO users (username, password_hash, created_at) VALUES ('legacy', 'x$y', '2026-01-01');
        """
    )
    con.commit()
    con.close()

    real_path = db.DB_PATH
    db.DB_PATH = old_path
    try:
        db.init_db()
        db.init_db()  # idempotent
        con = sqlite3.connect(old_path)
        cols = [row[1] for row in con.execute("PRAGMA table_info(users)")]
        con.close()
        legacy = db.get_user_by_username("legacy")
    finally:
        db.DB_PATH = real_path
    check("old DB gains role + employee_id columns", "role" in cols and "employee_id" in cols, str(cols))
    check("existing user migrated to learner", legacy["role"] == "learner" and legacy["employee_id"] is None)

    db.init_db()
    con = sqlite3.connect(db.DB_PATH)
    cols = [row[1] for row in con.execute("PRAGMA table_info(users)")]
    con.close()
    check("fresh DB has role + employee_id columns", "role" in cols and "employee_id" in cols)


def test_register_and_seed() -> None:
    print("\n[registration + seeding]")
    client = app.test_client()
    r = client.post("/api/register", json={"username": "sneaky", "password": "pw", "role": "admin"})
    check("self-registration succeeds", r.status_code == 200)
    check("self-registration ignores role -> learner", db.get_user_by_username("sneaky")["role"] == "learner")

    os.environ.pop("ANTAHAI_TRAINER_PASSWORD", None)
    os.environ.pop("ANTAHAI_ADMIN_PASSWORD", None)
    seed_demo_accounts()
    check("no password env -> nothing seeded",
          db.get_user_by_username("trainer") is None and db.get_user_by_username("admin") is None)

    # A learner who grabbed a demo username is reset (role + password), so
    # they cannot inherit the elevated role with their own password.
    client.post("/api/register", json={"username": "boss", "password": "learnerpw"})
    os.environ.update({
        "ANTAHAI_TRAINER_USERNAME": "coach", "ANTAHAI_TRAINER_PASSWORD": "coachpw",
        "ANTAHAI_ADMIN_USERNAME": "boss", "ANTAHAI_ADMIN_PASSWORD": "bosspw",
    })
    seed_demo_accounts()
    seed_demo_accounts()  # idempotent
    check("trainer seeded", db.get_user_by_username("coach")["role"] == "trainer")
    check("admin seeded over existing username", db.get_user_by_username("boss")["role"] == "admin")
    check("old learner password no longer works", login(app.test_client(), "boss", "learnerpw").status_code == 401)
    with sqlite3.connect(db.DB_PATH) as con:
        n = con.execute("SELECT COUNT(*) FROM users WHERE username IN ('coach', 'boss')").fetchone()[0]
    check("re-seeding does not duplicate accounts", n == 2)


def test_login_redirects() -> None:
    print("\n[login redirects]")
    learner = app.test_client()
    learner.post("/api/register", json={"username": "lee", "password": "pw"})
    r = login(learner, "lee", "pw")
    check("learner without employee -> intake", r.get_json().get("redirect") == "/recommendation")

    trainer = app.test_client()
    r = login(trainer, "coach", "coachpw")
    check("trainer -> /trainer", r.get_json().get("redirect") == "/trainer")

    admin = app.test_client()
    r = login(admin, "boss", "bosspw")
    check("admin -> /admin", r.get_json().get("redirect") == "/admin")

    check("logged-in trainer hitting / -> /trainer", status_and_location(trainer, "/")[1].endswith("/trainer"))
    check("logged-in admin hitting /login -> /admin", status_and_location(admin, "/login")[1].endswith("/admin"))


def test_role_protection() -> None:
    print("\n[role protection]")
    anon = app.test_client()
    for path in ("/trainer", "/admin", "/recommendation", "/profile"):
        code, loc = status_and_location(anon, path)
        check(f"anonymous {path} -> login", code == 302 and loc.endswith("/login"), f"{code} {loc}")

    learner = app.test_client()
    login(learner, "lee", "pw")
    check("learner /trainer -> 403", learner.get("/trainer").status_code == 403)
    check("learner /admin -> 403", learner.get("/admin").status_code == 403)
    check("learner /recommendation -> 200", learner.get("/recommendation").status_code == 200)

    trainer = app.test_client()
    login(trainer, "coach", "coachpw")
    check("trainer /trainer -> 200", trainer.get("/trainer").status_code == 200)
    check("trainer /admin -> 403", trainer.get("/admin").status_code == 403)
    check("trainer /recommendation -> 403", trainer.get("/recommendation").status_code == 403)
    check("trainer /profile -> 403", trainer.get("/profile").status_code == 403)
    html = trainer.get("/trainer").get_data(as_text=True)
    check("trainer nav hides Profile link", ">Profile<" not in html and "Logout" in html)

    admin = app.test_client()
    login(admin, "boss", "bosspw")
    check("admin /admin -> 200", admin.get("/admin").status_code == 200)
    check("admin /trainer -> 200", admin.get("/trainer").status_code == 200)
    check("admin /recommendation -> 403", admin.get("/recommendation").status_code == 403)

    # Role is read from the DB per request: a demotion applies immediately.
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute("UPDATE users SET role = 'learner' WHERE username = 'boss'")
    check("demoted admin loses /admin at once", admin.get("/admin").status_code == 403)
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute("UPDATE users SET role = 'admin' WHERE username = 'boss'")

    # A session whose account was deleted is sent back to login.
    ghost = app.test_client()
    ghost.post("/api/register", json={"username": "ghost", "password": "pw"})
    login(ghost, "ghost", "pw")
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute("DELETE FROM users WHERE username = 'ghost'")
    code, loc = status_and_location(ghost, "/recommendation")
    check("deleted account -> login", code == 302 and loc.endswith("/login"))


def test_persistent_employee() -> None:
    print("\n[persistent learner employee_id]")
    client = app.test_client()
    client.post("/api/register", json={"username": "asha", "password": "pw"})
    login(client, "asha", "pw")

    r = client.post("/recommendation", json=INTAKE)
    first = r.get_json()
    emp = db.get_user_by_username("asha")["employee_id"]
    check("first intake registers once", r.status_code == 200 and S1["calls"]["register"] == 1)
    check("employee_id stored on account", emp == "E900", str(emp))

    # System 1 has since recorded a quiz-verified level for this employee.
    S1["employees"][emp]["quiz_verified_skills"] = {"S002": 2}
    r = client.post("/recommendation", json=dict(INTAKE, self_rated_skills={"S001": 2}))
    second = r.get_json()
    check("second intake does not register again", r.status_code == 200 and S1["calls"]["register"] == 1)
    sent = S1["calls"]["compute"][-1] if S1["calls"]["compute"] else {}
    check("second intake computes for stored employee", sent.get("employee_id") == emp)
    check("quiz-verified levels carried over", sent.get("quiz_verified_skills") == {"S002": 2})
    check("self-ratings synced to System 1", S1["calls"]["skills"][-1:] == [(emp, {"S001": 2}, None)])
    check("employee_id unchanged", db.get_user_by_username("asha")["employee_id"] == emp)

    sid1 = int(first["redirect"].rsplit("/", 1)[-1])
    sid2 = int(second["redirect"].rsplit("/", 1)[-1])
    check("both snapshots share the employee_id",
          db.get_submission(sid1)["employee_id"] == db.get_submission(sid2)["employee_id"] == emp)
    check("snapshot keeps quiz-verified levels", db.get_submission(sid2)["quiz_verified_skills"] == {"S002": 2})

    relog = app.test_client()
    r = login(relog, "asha", "pw")
    check("learner with employee -> latest results",
          r.get_json().get("redirect") == f"/recommendation/results/{sid2}", r.get_json().get("redirect"))

    # System 1 lost the employee (e.g. Dataset-5 reset): register a new one.
    del S1["employees"][emp]
    r = client.post("/recommendation", json=INTAKE)
    new_emp = db.get_user_by_username("asha")["employee_id"]
    check("unknown stored id -> re-register + store new id",
          r.status_code == 200 and S1["calls"]["register"] == 2 and new_emp not in (None, emp), str(new_emp))


def main() -> int:
    db.init_db()
    test_migration()
    test_register_and_seed()
    test_login_redirects()
    test_role_protection()
    test_persistent_employee()
    print(f"\n{'-'*46}\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
