"""
AntahAI Learning Pathways - persistence (SQLite, same database as System 3).

Normalised tables (created by ``migrate()``; versioned in ``pw_schema_version``):

  pw_organizations        ministries / departments (master data, source recorded)
  pw_learner_profiles     one per user: basics, organisation, demo flag
  pw_competencies         competency definitions
  pw_competency_evidence  every piece of evidence (source, level 0-100, confidence, note)
  pw_goals / pw_goal_requirements / pw_goal_entry_prereqs
  pw_courses / pw_course_competencies / pw_course_prerequisites / pw_lessons
  pw_assessments / pw_questions / pw_labs
  pw_enrollments          course progress per learner (shared by all roadmaps)
  pw_assessment_attempts  every quiz attempt with per-competency breakdown
  pw_lab_submissions      lab answers + result
  pw_roadmaps / pw_roadmap_nodes / pw_roadmap_edges   saved roadmaps (one per goal)

Tables are prefixed ``pw_`` so they never collide with Round-1 tables
(users / submissions / quiz_attempts), which are untouched.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import db as core_db  # System-3 connection helper (honours ANTAHAI_DB)

from . import catalogue as cat

SCHEMA_VERSION = 2
SOURCES = ("self_reported", "resume_inferred", "assessment")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    return core_db.connect()


SCHEMA = """
CREATE TABLE IF NOT EXISTS pw_schema_version (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('ministry','department','office')),
    parent_id TEXT REFERENCES pw_organizations(id),
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_learner_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    display_name TEXT NOT NULL DEFAULT '',
    organization_id TEXT REFERENCES pw_organizations(id),
    experience_years INTEGER CHECK (experience_years IS NULL OR experience_years BETWEEN 0 AND 60),
    education TEXT NOT NULL DEFAULT '',
    interests TEXT NOT NULL DEFAULT '',
    is_demo INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_competencies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    s1_skill_id TEXT,
    keywords TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS pw_competency_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    competency_id TEXT NOT NULL REFERENCES pw_competencies(id),
    source TEXT NOT NULL CHECK (source IN ('self_reported','resume_inferred','assessment')),
    level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 100),
    confidence REAL NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pw_evidence_user ON pw_competency_evidence(user_id, competency_id);
CREATE TABLE IF NOT EXISTS pw_goals (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, tagline TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '', icon TEXT NOT NULL DEFAULT '',
    is_prototype INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pw_goal_requirements (
    goal_id TEXT NOT NULL REFERENCES pw_goals(id),
    competency_id TEXT NOT NULL REFERENCES pw_competencies(id),
    target INTEGER NOT NULL CHECK (target BETWEEN 1 AND 100),
    weight INTEGER NOT NULL CHECK (weight BETWEEN 1 AND 3),
    PRIMARY KEY (goal_id, competency_id)
);
CREATE TABLE IF NOT EXISTS pw_goal_entry_prereqs (
    goal_id TEXT NOT NULL REFERENCES pw_goals(id),
    competency_id TEXT NOT NULL REFERENCES pw_competencies(id),
    min_level INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (goal_id, competency_id)
);
CREATE TABLE IF NOT EXISTS pw_courses (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL CHECK (difficulty IN ('beginner','intermediate','advanced')),
    duration_minutes INTEGER,
    duration_verified INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    availability TEXT NOT NULL CHECK (availability IN ('available','unavailable')),
    outcomes TEXT NOT NULL DEFAULT '[]',
    is_prototype INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pw_course_competencies (
    course_id TEXT NOT NULL REFERENCES pw_courses(id),
    competency_id TEXT NOT NULL REFERENCES pw_competencies(id),
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 100),
    PRIMARY KEY (course_id, competency_id)
);
CREATE TABLE IF NOT EXISTS pw_course_prerequisites (
    course_id TEXT NOT NULL REFERENCES pw_courses(id),
    competency_id TEXT NOT NULL REFERENCES pw_competencies(id),
    min_level INTEGER NOT NULL CHECK (min_level BETWEEN 1 AND 100),
    PRIMARY KEY (course_id, competency_id)
);
CREATE TABLE IF NOT EXISTS pw_lessons (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES pw_courses(id),
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    minutes INTEGER,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_assessments (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL UNIQUE REFERENCES pw_courses(id),
    pass_threshold REAL NOT NULL CHECK (pass_threshold > 0 AND pass_threshold <= 1)
);
CREATE TABLE IF NOT EXISTS pw_questions (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES pw_assessments(id),
    qid TEXT NOT NULL,
    position INTEGER NOT NULL,
    competency_id TEXT NOT NULL REFERENCES pw_competencies(id),
    lesson_id TEXT REFERENCES pw_lessons(id),
    text TEXT NOT NULL,
    options TEXT NOT NULL,
    answer_index INTEGER NOT NULL,
    explanation TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pw_labs (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL UNIQUE REFERENCES pw_courses(id),
    title TEXT NOT NULL,
    spec TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_enrollments (
    user_id INTEGER NOT NULL REFERENCES users(id),
    course_id TEXT NOT NULL REFERENCES pw_courses(id),
    status TEXT NOT NULL CHECK (status IN ('in_progress','completed')),
    lessons_done TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (user_id, course_id)
);
CREATE TABLE IF NOT EXISTS pw_assessment_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    assessment_id TEXT NOT NULL REFERENCES pw_assessments(id),
    course_id TEXT NOT NULL REFERENCES pw_courses(id),
    answers TEXT NOT NULL,
    correct INTEGER NOT NULL,
    total INTEGER NOT NULL,
    score REAL NOT NULL,
    passed INTEGER NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_lab_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    lab_id TEXT NOT NULL REFERENCES pw_labs(id),
    course_id TEXT NOT NULL REFERENCES pw_courses(id),
    answers TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    passed INTEGER NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pw_roadmaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    goal_id TEXT NOT NULL REFERENCES pw_goals(id),
    version INTEGER NOT NULL DEFAULT 1,
    progress INTEGER NOT NULL DEFAULT 0,
    readiness INTEGER NOT NULL DEFAULT 0,
    next_action TEXT,
    analysis TEXT NOT NULL DEFAULT '{}',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, goal_id)
);
CREATE TABLE IF NOT EXISTS pw_roadmap_nodes (
    roadmap_id INTEGER NOT NULL REFERENCES pw_roadmaps(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    type TEXT NOT NULL,
    course_id TEXT REFERENCES pw_courses(id),
    state TEXT NOT NULL,
    recommended INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL, y REAL NOT NULL, layer INTEGER NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (roadmap_id, node_id)
);
CREATE TABLE IF NOT EXISTS pw_roadmap_edges (
    roadmap_id INTEGER NOT NULL REFERENCES pw_roadmaps(id) ON DELETE CASCADE,
    edge_id TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (roadmap_id, edge_id)
);
"""


def migrate() -> None:
    core_db.init_db()  # Round-1 tables (users etc.) must exist for FKs
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        # v2: external learning resources per course (additive migration).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(pw_courses)").fetchall()}
        if "resources" not in cols:
            conn.execute("ALTER TABLE pw_courses ADD COLUMN resources TEXT NOT NULL DEFAULT '[]'")
        row = conn.execute("SELECT MAX(version) FROM pw_schema_version").fetchone()
        if not row or row[0] is None or row[0] < SCHEMA_VERSION:
            conn.execute("INSERT OR REPLACE INTO pw_schema_version VALUES (?, ?)",
                         (SCHEMA_VERSION, now()))
        conn.commit()


# ---------------------------------------------------------------------------
# Seeding (idempotent upserts - safe on every start)
# ---------------------------------------------------------------------------

def seed_catalogue(raw: dict | None = None) -> None:
    raw = raw or cat.load_raw()
    cat.validate(raw)
    with closing(connect()) as conn:
        for c in raw["competencies"]:
            conn.execute(
                """INSERT INTO pw_competencies (id, name, category, description, s1_skill_id, keywords)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name, category=excluded.category, description=excluded.description,
                   s1_skill_id=excluded.s1_skill_id, keywords=excluded.keywords""",
                (c["id"], c["name"], c["category"], c["description"], c.get("s1_skill_id"),
                 json.dumps(c.get("keywords", []))),
            )
        for connector in cat.connectors(raw):
            for c in connector.listings():
                _upsert_course(conn, c)
        for g in raw["goals"]:
            conn.execute(
                """INSERT INTO pw_goals (id, title, tagline, description, icon, is_prototype)
                   VALUES (?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                   tagline=excluded.tagline, description=excluded.description, icon=excluded.icon""",
                (g["id"], g["title"], g.get("tagline", ""), g.get("description", ""), g.get("icon", "")),
            )
            conn.execute("DELETE FROM pw_goal_requirements WHERE goal_id=?", (g["id"],))
            conn.execute("DELETE FROM pw_goal_entry_prereqs WHERE goal_id=?", (g["id"],))
            for r in g["requirements"]:
                conn.execute("INSERT INTO pw_goal_requirements VALUES (?,?,?,?)",
                             (g["id"], r["competency"], int(r["target"]), int(r.get("weight", 1))))
            for p in g.get("entry_prerequisites", []):
                conn.execute("INSERT INTO pw_goal_entry_prereqs VALUES (?,?,?,?)",
                             (g["id"], p["competency"], int(p["min_level"]), p.get("note", "")))
        conn.commit()


def _upsert_course(conn: sqlite3.Connection, c: dict) -> None:
    conn.execute(
        """INSERT INTO pw_courses (id, title, summary, difficulty, duration_minutes, duration_verified,
               source, availability, outcomes, is_prototype)
           VALUES (?,?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
           summary=excluded.summary, difficulty=excluded.difficulty,
           duration_minutes=excluded.duration_minutes, duration_verified=excluded.duration_verified,
           source=excluded.source, availability=excluded.availability, outcomes=excluded.outcomes""",
        (c["id"], c["title"], c.get("summary", ""), c["difficulty"], c.get("duration_minutes"),
         1 if c.get("duration_verified") else 0, c.get("source", "local"),
         c.get("availability", "available"), json.dumps(c.get("outcomes", []))),
    )
    conn.execute("UPDATE pw_courses SET resources=? WHERE id=?",
                 (json.dumps(c.get("resources", [])), c["id"]))
    conn.execute("DELETE FROM pw_course_competencies WHERE course_id=?", (c["id"],))
    conn.execute("DELETE FROM pw_course_prerequisites WHERE course_id=?", (c["id"],))
    for comp, lvl in (c.get("develops") or {}).items():
        conn.execute("INSERT INTO pw_course_competencies VALUES (?,?,?)", (c["id"], comp, int(lvl)))
    for p in c.get("prerequisites", []):
        conn.execute("INSERT INTO pw_course_prerequisites VALUES (?,?,?)",
                     (c["id"], p["competency"], int(p["min_level"])))
    for pos, lesson in enumerate(c.get("lessons", [])):
        conn.execute(
            """INSERT INTO pw_lessons (id, course_id, position, title, minutes, body) VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET position=excluded.position, title=excluded.title,
               minutes=excluded.minutes, body=excluded.body""",
            (lesson["id"], c["id"], pos, lesson["title"], lesson.get("minutes"), json.dumps(lesson["body"])),
        )
    quiz = c.get("quiz")
    if quiz:
        aid = f"{c['id']}-quiz"
        conn.execute(
            """INSERT INTO pw_assessments (id, course_id, pass_threshold) VALUES (?,?,?)
               ON CONFLICT(id) DO UPDATE SET pass_threshold=excluded.pass_threshold""",
            (aid, c["id"], float(quiz.get("pass_threshold", 0.7))),
        )
        conn.execute("DELETE FROM pw_questions WHERE assessment_id=?", (aid,))
        for pos, q in enumerate(quiz["questions"]):
            conn.execute(
                "INSERT INTO pw_questions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"{aid}:{q['id']}", aid, q["id"], pos, q["competency"], q.get("lesson"),
                 q["text"], json.dumps(q["options"]), int(q["answer"]), q.get("explanation", "")),
            )
    lab = c.get("lab")
    if lab:
        conn.execute(
            """INSERT INTO pw_labs (id, course_id, title, spec) VALUES (?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, spec=excluded.spec""",
            (lab["id"], c["id"], lab["title"], json.dumps(lab)),
        )


def seed_organizations(dataset2_csv: Path | None) -> int:
    """Master organisation list from existing project data (department names only).

    The Round-1 role table lists departments; it does NOT define competency
    requirements for the prototype goals, and none are inferred from it.
    """
    if not dataset2_csv or not Path(dataset2_csv).exists():
        return 0
    with open(dataset2_csv, encoding="utf-8") as fh:
        names = sorted({(r.get("department") or "").strip() for r in csv.DictReader(fh)} - {""})
    return import_organizations([("", n) for n in names],
                                source=f"{Path(dataset2_csv).name} (department names only)")


def import_organizations(pairs: list[tuple[str, str]], source: str) -> int:
    """Import (ministry, department) pairs. Idempotent; returns rows touched."""
    count = 0
    with closing(connect()) as conn:
        for ministry, dept in pairs:
            parent = None
            if ministry:
                parent = "min:" + _slug(ministry)
                conn.execute("INSERT OR IGNORE INTO pw_organizations VALUES (?,?,?,?,?)",
                             (parent, ministry, "ministry", None, source))
            conn.execute(
                """INSERT INTO pw_organizations VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE
                   SET name=excluded.name, parent_id=COALESCE(excluded.parent_id, parent_id)""",
                ("dept:" + _slug(dept), dept, "department", parent, source))
            count += 1
        conn.commit()
    return count


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")[:80]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _rows(sql: str, args: tuple = ()) -> list[dict]:
    with closing(connect()) as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _row(sql: str, args: tuple = ()) -> dict | None:
    rows = _rows(sql, args)
    return rows[0] if rows else None


def competencies() -> dict[str, dict]:
    out = {}
    for r in _rows("SELECT * FROM pw_competencies ORDER BY category, name"):
        r["keywords"] = json.loads(r["keywords"])
        out[r["id"]] = r
    return out


def goals() -> dict[str, dict]:
    gs = {g["id"]: dict(g, requirements=[], entry_prerequisites=[])
          for g in _rows("SELECT * FROM pw_goals ORDER BY title")}
    for r in _rows("SELECT * FROM pw_goal_requirements ORDER BY weight DESC, competency_id"):
        gs[r["goal_id"]]["requirements"].append(
            {"competency": r["competency_id"], "target": r["target"], "weight": r["weight"]})
    for r in _rows("SELECT * FROM pw_goal_entry_prereqs"):
        gs[r["goal_id"]]["entry_prerequisites"].append(
            {"competency": r["competency_id"], "min_level": r["min_level"], "note": r["note"]})
    return gs


def engine_courses() -> list[dict]:
    """Courses in the exact shape engine.py expects, built from normalised tables."""
    courses = {}
    for r in _rows("SELECT * FROM pw_courses ORDER BY id"):
        courses[r["id"]] = {
            "id": r["id"], "title": r["title"], "summary": r["summary"],
            "outcomes": json.loads(r["outcomes"]), "difficulty": r["difficulty"],
            "duration_minutes": r["duration_minutes"],
            "duration_verified": bool(r["duration_verified"]),
            "availability": r["availability"], "source": r["source"],
            "develops": {}, "prerequisites": [], "has_quiz": False, "has_lab": False, "lab_title": "",
            "resources": json.loads(r.get("resources") or "[]"),
        }
    for r in _rows("SELECT * FROM pw_course_competencies ORDER BY competency_id"):
        courses[r["course_id"]]["develops"][r["competency_id"]] = r["level"]
    for r in _rows("SELECT * FROM pw_course_prerequisites ORDER BY competency_id"):
        courses[r["course_id"]]["prerequisites"].append(
            {"competency": r["competency_id"], "min_level": r["min_level"]})
    for r in _rows("SELECT a.course_id FROM pw_assessments a "
                   "WHERE EXISTS (SELECT 1 FROM pw_questions q WHERE q.assessment_id=a.id)"):
        courses[r["course_id"]]["has_quiz"] = True
    for r in _rows("SELECT course_id, title FROM pw_labs"):
        courses[r["course_id"]]["has_lab"] = True
        courses[r["course_id"]]["lab_title"] = r["title"]
    return list(courses.values())


def course_detail(course_id: str) -> dict | None:
    base = next((c for c in engine_courses() if c["id"] == course_id), None)
    if not base:
        return None
    lessons = _rows("SELECT * FROM pw_lessons WHERE course_id=? ORDER BY position", (course_id,))
    for l in lessons:
        l["body"] = json.loads(l["body"])
    assessment = _row("SELECT * FROM pw_assessments WHERE course_id=?", (course_id,))
    questions = []
    if assessment:
        for q in _rows("SELECT * FROM pw_questions WHERE assessment_id=? ORDER BY position",
                       (assessment["id"],)):
            questions.append({"id": q["qid"], "competency": q["competency_id"], "lesson": q["lesson_id"],
                              "text": q["text"], "options": json.loads(q["options"]),
                              "answer": q["answer_index"], "explanation": q["explanation"]})
    lab_row = _row("SELECT * FROM pw_labs WHERE course_id=?", (course_id,))
    return dict(base, lessons=lessons, assessment=assessment, questions=questions,
                lab=json.loads(lab_row["spec"]) if lab_row else None)


def organizations() -> list[dict]:
    return _rows("SELECT * FROM pw_organizations ORDER BY name")


# ---- learner ----------------------------------------------------------------

def get_profile(user_id: int) -> dict:
    row = _row("SELECT * FROM pw_learner_profiles WHERE user_id=?", (user_id,))
    if row:
        return row
    return {"user_id": user_id, "display_name": "", "organization_id": None,
            "experience_years": None, "education": "", "interests": "", "is_demo": 0}


def save_profile(user_id: int, fields: dict) -> None:
    cur = get_profile(user_id)
    cur.update({k: v for k, v in fields.items() if k in
                ("display_name", "organization_id", "experience_years", "education", "interests", "is_demo")})
    with closing(connect()) as conn:
        conn.execute(
            """INSERT INTO pw_learner_profiles (user_id, display_name, organization_id, experience_years,
                   education, interests, is_demo, updated_at) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name,
               organization_id=excluded.organization_id, experience_years=excluded.experience_years,
               education=excluded.education, interests=excluded.interests, is_demo=excluded.is_demo,
               updated_at=excluded.updated_at""",
            (user_id, cur["display_name"] or "", cur["organization_id"], cur["experience_years"],
             cur["education"] or "", cur["interests"] or "", int(cur.get("is_demo") or 0), now()),
        )
        conn.commit()


def evidence(user_id: int) -> list[dict]:
    return _rows("SELECT * FROM pw_competency_evidence WHERE user_id=? ORDER BY id", (user_id,))


def add_evidence(user_id: int, competency_id: str, source: str, level: int, note: str = "",
                 origin: str = "", confirmed: bool = False, confidence: float | None = None) -> int:
    from .rules import CONFIDENCE
    if source not in SOURCES:
        raise ValueError(f"bad evidence source {source}")
    level = int(level)
    if not 0 <= level <= 100:
        raise ValueError("level must be 0-100")
    with closing(connect()) as conn:
        cur = conn.execute(
            """INSERT INTO pw_competency_evidence (user_id, competency_id, source, level, confidence,
                   confirmed, note, origin, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, competency_id, source, level,
             confidence if confidence is not None else CONFIDENCE[source],
             1 if confirmed else 0, note, origin, now()),
        )
        conn.commit()
        return cur.lastrowid


def update_evidence(evidence_id: int, user_id: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("confirmed", "level", "note")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    with closing(connect()) as conn:
        conn.execute(f"UPDATE pw_competency_evidence SET {sets} WHERE id=? AND user_id=?",
                     (*allowed.values(), evidence_id, user_id))
        conn.commit()


def delete_evidence(evidence_id: int, user_id: int, source: str) -> None:
    with closing(connect()) as conn:
        conn.execute("DELETE FROM pw_competency_evidence WHERE id=? AND user_id=? AND source=?",
                     (evidence_id, user_id, source))
        conn.commit()


def enrollments(user_id: int) -> dict[str, dict]:
    out = {}
    for r in _rows("SELECT * FROM pw_enrollments WHERE user_id=?", (user_id,)):
        r["lessons_done"] = json.loads(r["lessons_done"])
        out[r["course_id"]] = r
    return out


def upsert_enrollment(user_id: int, course_id: str, status: str | None = None,
                      lessons_done: list[str] | None = None) -> dict:
    current = enrollments(user_id).get(course_id)
    with closing(connect()) as conn:
        if not current:
            conn.execute(
                "INSERT INTO pw_enrollments (user_id, course_id, status, lessons_done, started_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, course_id, status or "in_progress", json.dumps(lessons_done or []), now()))
        else:
            new_status = status or current["status"]
            if current["status"] == "completed":
                new_status = "completed"  # completion is never undone
            conn.execute(
                "UPDATE pw_enrollments SET status=?, lessons_done=?, completed_at=COALESCE(completed_at, ?) "
                "WHERE user_id=? AND course_id=?",
                (new_status, json.dumps(lessons_done if lessons_done is not None else current["lessons_done"]),
                 now() if new_status == "completed" else None, user_id, course_id))
        conn.commit()
    return enrollments(user_id)[course_id]


def record_attempt(user_id: int, course_id: str, answers: dict, result: dict) -> int:
    with closing(connect()) as conn:
        cur = conn.execute(
            """INSERT INTO pw_assessment_attempts (user_id, assessment_id, course_id, answers, correct,
                   total, score, passed, result, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (user_id, f"{course_id}-quiz", course_id, json.dumps(answers), result["correct"],
             result["total"], result["score"], 1 if result["passed"] else 0, json.dumps(result), now()))
        conn.commit()
        return cur.lastrowid


def attempts(user_id: int, course_id: str | None = None) -> list[dict]:
    if course_id:
        rows = _rows("SELECT * FROM pw_assessment_attempts WHERE user_id=? AND course_id=? ORDER BY id",
                     (user_id, course_id))
    else:
        rows = _rows("SELECT * FROM pw_assessment_attempts WHERE user_id=? ORDER BY id", (user_id,))
    for r in rows:
        r["result"] = json.loads(r["result"])
    return rows


def get_attempt(user_id: int, attempt_id: int) -> dict | None:
    r = _row("SELECT * FROM pw_assessment_attempts WHERE id=? AND user_id=?", (attempt_id, user_id))
    if r:
        r["result"] = json.loads(r["result"])
    return r


def record_lab(user_id: int, course_id: str, lab_id: str, answers: dict, interpretation: str,
               result: dict) -> int:
    with closing(connect()) as conn:
        cur = conn.execute(
            """INSERT INTO pw_lab_submissions (user_id, lab_id, course_id, answers, interpretation,
                   passed, result, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (user_id, lab_id, course_id, json.dumps(answers), interpretation,
             1 if result["passed"] else 0, json.dumps(result), now()))
        conn.commit()
        return cur.lastrowid


def lab_submissions(user_id: int, course_id: str | None = None) -> list[dict]:
    sql = "SELECT * FROM pw_lab_submissions WHERE user_id=?"
    args: tuple = (user_id,)
    if course_id:
        sql += " AND course_id=?"
        args += (course_id,)
    rows = _rows(sql + " ORDER BY id", args)
    for r in rows:
        r["result"] = json.loads(r["result"])
    return rows


# ---- roadmaps ---------------------------------------------------------------

def save_roadmap(user_id: int, goal_id: str, graph: dict) -> int:
    summary = graph["summary"]
    with closing(connect()) as conn:
        existing = conn.execute("SELECT id, version FROM pw_roadmaps WHERE user_id=? AND goal_id=?",
                                (user_id, goal_id)).fetchone()
        if existing:
            rid = existing["id"]
            conn.execute(
                """UPDATE pw_roadmaps SET version=version+1, progress=?, readiness=?, next_action=?,
                   analysis=?, width=?, height=?, updated_at=? WHERE id=?""",
                (summary["progress"], summary["readiness"], json.dumps(summary["next_action"]),
                 json.dumps(graph["analysis"]), graph["size"]["width"], graph["size"]["height"], now(), rid))
            conn.execute("DELETE FROM pw_roadmap_nodes WHERE roadmap_id=?", (rid,))
            conn.execute("DELETE FROM pw_roadmap_edges WHERE roadmap_id=?", (rid,))
        else:
            cur = conn.execute(
                """INSERT INTO pw_roadmaps (user_id, goal_id, progress, readiness, next_action, analysis,
                   width, height, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, goal_id, summary["progress"], summary["readiness"],
                 json.dumps(summary["next_action"]), json.dumps(graph["analysis"]),
                 graph["size"]["width"], graph["size"]["height"], now(), now()))
            rid = cur.lastrowid
        for n in graph["nodes"]:
            conn.execute(
                "INSERT INTO pw_roadmap_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, n["id"], n["type"], n.get("course_id"), n["state"], 1 if n.get("recommended") else 0,
                 n["title"], n.get("subtitle", ""), n["x"], n["y"], n["layer"], json.dumps(n.get("data", {}))))
        for e in graph["edges"]:
            conn.execute("INSERT INTO pw_roadmap_edges VALUES (?,?,?,?,?,?)",
                         (rid, e["id"], e["source"], e["target"], e["kind"], e.get("label", "")))
        conn.commit()
    return rid


def list_roadmaps(user_id: int) -> list[dict]:
    rows = _rows(
        "SELECT r.*, g.title AS goal_title, g.tagline AS goal_tagline, g.icon AS goal_icon "
        "FROM pw_roadmaps r JOIN pw_goals g ON g.id = r.goal_id WHERE r.user_id=? ORDER BY r.updated_at DESC, r.id DESC",
        (user_id,))
    for r in rows:
        r["next_action"] = json.loads(r["next_action"]) if r["next_action"] else None
        r.pop("analysis", None)
    return rows


def get_roadmap(user_id: int, roadmap_id: int) -> dict | None:
    r = _row("SELECT r.*, g.title AS goal_title, g.tagline AS goal_tagline FROM pw_roadmaps r "
             "JOIN pw_goals g ON g.id=r.goal_id WHERE r.id=? AND r.user_id=?", (roadmap_id, user_id))
    if not r:
        return None
    r["next_action"] = json.loads(r["next_action"]) if r["next_action"] else None
    r["analysis"] = json.loads(r["analysis"])
    nodes = _rows("SELECT * FROM pw_roadmap_nodes WHERE roadmap_id=? ORDER BY layer, y", (roadmap_id,))
    for n in nodes:
        n["data"] = json.loads(n["data"])
        n["recommended"] = bool(n["recommended"])
        n["id"] = n.pop("node_id")
    edges = _rows("SELECT * FROM pw_roadmap_edges WHERE roadmap_id=?", (roadmap_id,))
    for e in edges:
        e["id"] = e.pop("edge_id")
    r["nodes"], r["edges"] = nodes, edges
    return r


def roadmap_history(roadmap_id: int) -> tuple[list[str], list[tuple[str, str]]]:
    """(course ids, course->course prerequisite edges) of the stored version."""
    nodes = _rows("SELECT node_id, course_id, type FROM pw_roadmap_nodes WHERE roadmap_id=?", (roadmap_id,))
    course_of = {n["node_id"]: n["course_id"] for n in nodes if n["course_id"]}
    courses = [n["course_id"] for n in nodes if n["type"] == "course"]
    edges = []
    for e in _rows("SELECT source, target FROM pw_roadmap_edges WHERE roadmap_id=? AND kind='prerequisite'",
                   (roadmap_id,)):
        s, t = course_of.get(e["source"]), course_of.get(e["target"])
        if s and t and s != t:
            edges.append((s, t))
    return courses, edges


def roadmap_for_goal(user_id: int, goal_id: str) -> dict | None:
    return _row("SELECT * FROM pw_roadmaps WHERE user_id=? AND goal_id=?", (user_id, goal_id))


def delete_roadmap(user_id: int, roadmap_id: int) -> bool:
    with closing(connect()) as conn:
        owned = conn.execute("SELECT 1 FROM pw_roadmaps WHERE id=? AND user_id=?",
                             (roadmap_id, user_id)).fetchone()
        if not owned:
            return False
        conn.execute("DELETE FROM pw_roadmap_nodes WHERE roadmap_id=?", (roadmap_id,))
        conn.execute("DELETE FROM pw_roadmap_edges WHERE roadmap_id=?", (roadmap_id,))
        conn.execute("DELETE FROM pw_roadmaps WHERE id=?", (roadmap_id,))
        conn.commit()
    return True


def reset_learner(user_id: int) -> None:
    """Remove all pathway data for one learner (used to reset demo accounts)."""
    with closing(connect()) as conn:
        for rid, in conn.execute("SELECT id FROM pw_roadmaps WHERE user_id=?", (user_id,)).fetchall():
            conn.execute("DELETE FROM pw_roadmap_nodes WHERE roadmap_id=?", (rid,))
            conn.execute("DELETE FROM pw_roadmap_edges WHERE roadmap_id=?", (rid,))
        for table in ("pw_roadmaps", "pw_lab_submissions", "pw_assessment_attempts", "pw_enrollments",
                      "pw_competency_evidence"):
            conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
        conn.commit()
