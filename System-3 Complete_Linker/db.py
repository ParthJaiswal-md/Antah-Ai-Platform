"""
Antah.ai (System 3) - SQLite persistence layer.

Three tables back the whole web app:
  users          - auth (username + password hash), the account's role
                   (learner / trainer / admin) and, for learners, the System 1
                   employee_id their intake is registered under. System 1/2 know
                   nothing about usernames, so this is the only account data S3
                   tracks.
  submissions    - one row per employee intake form the logged-in user submits
                   through System 1, storing a snapshot of what was submitted
                   plus the exact recommendations System 1 returned (the profile
                   page renders history from these snapshots).
  quiz_attempts  - one row per "Take a quiz" run: which course of which
                   submission, the random Dataset-6 source link, generation
                   status, the question bank once ready, and the grade once the
                   quiz is submitted.

No ORM - plain sqlite3. The DB file lives next to this package.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ANTAHAI_DB", os.path.join(BASE_DIR, "antahai.db"))

ROLES = ("learner", "trainer", "admin")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'learner',
                employee_id TEXT
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                employee_id TEXT NOT NULL,
                name TEXT NOT NULL,
                role_id TEXT NOT NULL,
                designation TEXT NOT NULL,
                department TEXT NOT NULL,
                current_assignment TEXT,
                educational_qualifications TEXT,
                work_experience_years INTEGER,
                previous_trainings TEXT NOT NULL DEFAULT '[]',
                self_rated_skills TEXT NOT NULL DEFAULT '{}',
                quiz_verified_skills TEXT NOT NULL DEFAULT '{}',
                recommendations TEXT NOT NULL DEFAULT '[]',
                submitted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                submission_id INTEGER NOT NULL REFERENCES submissions(id),
                course_id TEXT NOT NULL,
                course_title TEXT NOT NULL,
                source_link TEXT,
                status TEXT NOT NULL DEFAULT 'generating',
                error TEXT,
                quiz TEXT,
                answers TEXT,
                score INTEGER,
                total INTEGER,
                accuracy REAL,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            """
        )
        _migrate_users(conn)
        conn.commit()


def _migrate_users(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release to an existing users
    table (CREATE TABLE IF NOT EXISTS leaves old tables as they were).
    Idempotent; pre-existing accounts become learners with no employee_id."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "role" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'learner'")
    if "employee_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN employee_id TEXT")


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


def create_user(username: str, password_hash: str, role: str = "learner") -> int:
    if role not in ROLES:
        raise ValueError(f"unknown role '{role}'")
    with closing(connect()) as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at, role) VALUES (?, ?, ?, ?)",
            (username, password_hash, _now(), role),
        )
        conn.commit()
        return cur.lastrowid


def upsert_user(username: str, password_hash: str, role: str) -> int:
    """Create the account, or reset an existing one's password + role (used to
    seed the demo trainer/admin accounts from the environment)."""
    existing = get_user_by_username(username)
    if not existing:
        return create_user(username, password_hash, role)
    if role not in ROLES:
        raise ValueError(f"unknown role '{role}'")
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, role = ? WHERE id = ?",
            (password_hash, role, existing["id"]),
        )
        conn.commit()
    return existing["id"]


def set_user_employee_id(user_id: int, employee_id: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE users SET employee_id = ? WHERE id = ?", (employee_id, user_id)
        )
        conn.commit()


def get_user_by_username(username: str) -> dict | None:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# submissions
# ---------------------------------------------------------------------------


def create_submission(user_id: int, data: dict) -> int:
    """Persist one intake submission + the recommendations S1 returned."""
    with closing(connect()) as conn:
        cur = conn.execute(
            """
            INSERT INTO submissions (
                user_id, employee_id, name, role_id, designation, department,
                current_assignment, educational_qualifications, work_experience_years,
                previous_trainings, self_rated_skills, quiz_verified_skills,
                recommendations, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                data["employee_id"],
                data.get("name", ""),
                data.get("role_id", ""),
                data.get("designation", ""),
                data.get("department", ""),
                data.get("current_assignment"),
                data.get("educational_qualifications"),
                data.get("work_experience_years"),
                json.dumps(data.get("previous_trainings", [])),
                json.dumps(data.get("self_rated_skills", {})),
                json.dumps(data.get("quiz_verified_skills", {})),
                json.dumps(data.get("recommendations", [])),
                _now(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def _submission_row(row: sqlite3.Row) -> dict:
    s = dict(row)
    for col in ("previous_trainings", "self_rated_skills",
                "quiz_verified_skills", "recommendations"):
        try:
            s[col] = json.loads(s[col] or "null") or ([] if col.endswith("s") or col == "recommendations" else {})
        except json.JSONDecodeError:
            s[col] = {} if "skills" in col else []
    return s


def get_submission(submission_id: int) -> dict | None:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
    return _submission_row(row) if row else None


def list_submissions(user_id: int) -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM submissions WHERE user_id = ? ORDER BY submitted_at DESC",
            (user_id,),
        ).fetchall()
    return [_submission_row(r) for r in rows]


def latest_submission_for_employee(user_id: int, employee_id: str) -> dict | None:
    """The user's newest submission for this employee_id (a learner's home)."""
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE user_id = ? AND employee_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, employee_id),
        ).fetchone()
    return _submission_row(row) if row else None


# ---------------------------------------------------------------------------
# quiz_attempts
# ---------------------------------------------------------------------------


def create_attempt(user_id: int, submission_id: int, course_id: str,
                   course_title: str, source_link: str | None = None) -> int:
    with closing(connect()) as conn:
        cur = conn.execute(
            """
            INSERT INTO quiz_attempts (
                user_id, submission_id, course_id, course_title, source_link,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'generating', ?)
            """,
            (user_id, submission_id, course_id, course_title, source_link, _now()),
        )
        conn.commit()
        return cur.lastrowid


def set_attempt_ready(attempt_id: int, quiz: list[dict]) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE quiz_attempts SET status = 'ready', quiz = ?, error = NULL WHERE id = ?",
            (json.dumps(quiz), attempt_id),
        )
        conn.commit()


def set_attempt_error(attempt_id: int, message: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE quiz_attempts SET status = 'error', error = ?, finished_at = ? "
            "WHERE id = ?",
            (message, _now(), attempt_id),
        )
        conn.commit()


def get_attempt(attempt_id: int) -> dict | None:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
    return dict(row) if row else None


def grade_attempt(attempt_id: int, answers: dict, quiz: list[dict]) -> dict:
    """Score a finished quiz (S2 convention: case-insensitive full-string match)."""
    details, score, total, accuracy = _score_answers(answers, quiz)

    with closing(connect()) as conn:
        conn.execute(
            """
            UPDATE quiz_attempts
            SET status = 'graded', answers = ?, score = ?, total = ?, accuracy = ?,
                quiz = ?, finished_at = ?
            WHERE id = ?
            """,
            (json.dumps(answers), score, total, accuracy, json.dumps(quiz),
             _now(), attempt_id),
        )
        conn.commit()

    return {"score": score, "total": total, "accuracy": accuracy, "details": details}


def _score_answers(answers: dict, quiz: list[dict]) -> tuple[list[dict], int, int, float]:
    """Shared scorer used by grade_attempt() and graded_review()."""
    details = []
    score = 0
    for q in quiz:
        qid = str(q["id"])
        selected = answers.get(qid, "")
        correct = q.get("answer", "")
        is_correct = bool(selected) and str(selected).lower() == str(correct).lower()
        if is_correct:
            score += 1
        details.append({
            "question_id": q["id"],
            "question": q.get("question", ""),
            "options": q.get("options", []),
            "selected_answer": selected,
            "correct_answer": correct,
            "is_correct": is_correct,
            "verification_status": q.get("verification_status", "unverified"),
            "explanation": q.get("explanation", ""),
        })

    total = len(quiz)
    accuracy = round((score / total) * 100, 2) if total else 0.0
    return details, score, total, accuracy


def graded_review(attempt_id: int) -> dict | None:
    """Recompute a graded attempt's per-question review from stored columns."""
    attempt = get_attempt(attempt_id)
    if not attempt or attempt.get("status") != "graded":
        return None
    try:
        quiz = json.loads(attempt["quiz"]) if attempt.get("quiz") else []
        answers = json.loads(attempt["answers"]) if attempt.get("answers") else {}
    except json.JSONDecodeError:
        return None
    details, score, total, accuracy = _score_answers(answers, quiz)
    return {"score": score, "total": total, "accuracy": accuracy, "details": details}


def list_attempts_for_submission(submission_id: int) -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_attempts WHERE submission_id = ? ORDER BY id",
            (submission_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_attempts_for_user(user_id: int) -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_attempts WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]
