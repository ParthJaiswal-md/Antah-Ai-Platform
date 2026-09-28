"""
Antah.ai (System 3) - full-stack web shell tying Systems 1 & 2 together.

Routes / auth / page flow only - the recommendation pipeline runs in
System 1 (called over HTTP via ``s1_client``) and the quiz pipeline runs
in-process against System 2's utils via ``s2_bridge``. Our own SQLite DB
(``db``) keeps auth, a submission snapshot per intake, and one row per quiz
attempt.

Page map (post-login pages extend templates/base.html for the shared
header/info dropdown):
    /                      landing (pre-login)
    /login                 login (pre-login)
    (modal)                register, POST /api/register
    /recommendation        employee intake form  -> POST -> S1 register
    /recommendation/results/<id>   top-5 courses + "Take a quiz" per course
    /quiz/<id>             quiz-taking (S2-generated) or status while generating
    /quiz/<id>/results     score / analysis page
    /profile               history for this username
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import threading
from functools import wraps

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db
import s1_client
import s2_bridge
import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [S3] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _secret_key() -> str:
    """ANTAHAI_SECRET, else a key persisted next to the app so logins survive restarts."""
    env = os.environ.get("ANTAHAI_SECRET")
    if env:
        return env
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".antahai_secret")
    try:
        with open(path, encoding="utf-8") as handle:
            key = handle.read().strip()
        if key:
            return key
    except OSError:
        pass
    key = secrets.token_hex(24)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(key)
    except OSError:
        pass
    return key


app.config["SECRET_KEY"] = _secret_key()
app.config["JSON_SORT_KEYS"] = False

RESULTS_LEAD = "On the basis of your current skill portfolio, here are your recommended courses."


# ---------------------------------------------------------------------------
# Context / auth helpers
# ---------------------------------------------------------------------------

@app.context_processor
def inject_user() -> dict:
    """Make ``current_user`` (username) available to every base.html page."""
    return {"current_user": session.get("username", "")}


def _hash_password(username: str, password: str) -> str:
    salt = hashlib.sha256(f"antahai:{username}".encode("utf-8")).hexdigest()[:16]
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return f"{salt}${digest}"


def _verify_password(username: str, password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return hmac.compare_digest(candidate, digest)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def _require_user() -> int:
    return int(session.get("user_id", 0))


def _owned_submission(submission_id: int) -> dict:
    """Fetch a submission, aborting unless it belongs to the logged-in user."""
    submission = db.get_submission(submission_id)
    if not submission or submission["user_id"] != _require_user():
        abort(404)
    return submission


def _owned_attempt(attempt_id: int) -> dict:
    attempt = db.get_attempt(attempt_id)
    if not attempt or attempt["user_id"] != _require_user():
        abort(404)
    return attempt


def _json_body() -> dict | None:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return None


# ---------------------------------------------------------------------------
# Landing / auth
# ---------------------------------------------------------------------------

@app.route("/")
def landing():
    if "user_id" in session:
        return redirect(url_for("pathways.dashboard"))
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("pathways.dashboard"))

    if request.method == "POST":
        body = _json_body() or request.form
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        user = db.get_user_by_username(username)
        if user and _verify_password(username, password, user["password_hash"]):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return jsonify({"ok": True, "redirect": url_for("pathways.dashboard")})
        return jsonify({"ok": False, "error": "Incorrect password. Please try again."}), 401

    return render_template("login.html")


@app.route("/api/register", methods=["POST"])
def api_register():
    body = _json_body()
    if not body:
        return jsonify({"ok": False, "error": "Invalid request."}), 400
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "Please fill in both username and password."}), 400
    if db.get_user_by_username(username):
        return jsonify({"ok": False, "error": "Username already taken. Please log in or choose another."}), 409
    db.create_user(username, _hash_password(username, password))
    # Registration never logs the user in directly - it routes through login.
    return jsonify({"ok": True})


@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("landing"))


# ---------------------------------------------------------------------------
# Recommendation intake (System 1 page)
# ---------------------------------------------------------------------------

def _build_meta() -> dict | None:
    """Metadata for the intake form, or None if System 1 is unreachable."""
    try:
        roles = s1_client.meta_roles()
        skills = [
            {"skill_id": s.get("skill_id"), "skill_name": s.get("skill_name", "")}
            for s in s1_client.meta_skills()
            if s.get("skill_id")
        ]
        courses = s1_client.meta_courses_light()
        unique = s1_client.meta_unique_values()
    except (s1_client.S1Unavailable, s1_client.S1Error):
        return None
    return {
        "roles": roles,
        "skills": skills,
        "courses": courses,
        "assignments": unique.get("current_assignment") or [],
        "qualifications": unique.get("educational_qualifications") or [],
    }


@app.route("/recommendation", methods=["GET", "POST"])
@login_required
def recommendation():
    if request.method == "POST":
        return _register_employee()

    meta = _build_meta()
    return render_template(
        "recommendation.html",
        meta=meta,
        s1_down=meta is None,
        s1_url=settings.S1_URL,
    )


def _register_employee():
    body = _json_body()
    if not body:
        return jsonify({"ok": False, "error": "Invalid request."}), 400

    designation = (body.get("designation") or "").strip()
    department = (body.get("department") or "").strip()
    role_id = (body.get("role_id") or "").strip()

    # Resolve role_id from designation + department if the client didn't send
    # it (mirrors System 1's frontend: role = designation/department pair).
    if not role_id and designation and department:
        try:
            for role in s1_client.meta_roles():
                if role.get("designation") == designation and role.get("department") == department:
                    role_id = role.get("role_id", "")
                    break
        except (s1_client.S1Unavailable, s1_client.S1Error):
            return jsonify({"ok": False, "error": "Cannot reach the recommendation engine."}), 503

    payload = {
        "name": (body.get("name") or "").strip(),
        "role_id": role_id,
        "designation": designation,
        "department": department,
        "current_assignment": (body.get("current_assignment") or "").strip() or None,
        "educational_qualifications": (body.get("educational_qualifications") or "").strip() or None,
        "work_experience_years": body.get("work_experience_years"),
        "self_rated_skills": body.get("self_rated_skills") or {},
        "quiz_verified_skills": {},
        "previous_trainings": body.get("previous_trainings") or [],
    }

    # Server-side presence checks (role_id must be non-empty / meaningful).
    if not payload["role_id"]:
        return jsonify({"ok": False, "error": "Please choose a designation and department."}), 400
    if not isinstance(payload["work_experience_years"], int):
        return jsonify({"ok": False, "error": "Work experience must be a whole number of years."}), 400

    try:
        result = s1_client.register_employee(payload, top_n=5)
    except s1_client.S1Unavailable as err:
        return jsonify({"ok": False, "error": str(err)}), 503
    except s1_client.S1Error as err:
        return jsonify({"ok": False, "error": f"The engine rejected this profile: {err}"}), 422

    employee = result["employee"]
    recommendations = result["recommendations"]

    # Enrich each recommendation with human skill names for the results /
    # profile pages (they render offline, without calling System 1 again).
    try:
        skill_names = {s["skill_id"]: s.get("skill_name", s["skill_id"]) for s in s1_client.meta_skills()}
    except (s1_client.S1Unavailable, s1_client.S1Error):
        skill_names = {}
    enriched = []
    for rec in recommendations:
        rec = dict(rec)
        rec["matched_skill_names"] = [
            skill_names.get(sid, sid) for sid in (rec.get("matched_skills") or [])
        ]
        enriched.append(rec)

    submission_id = db.create_submission(
        _require_user(),
        {
            "employee_id": employee["employee_id"],
            "name": employee.get("name") or "",
            "role_id": employee.get("role_id") or "",
            "designation": employee.get("designation") or "",
            "department": employee.get("department") or "",
            "current_assignment": employee.get("current_assignment"),
            "educational_qualifications": employee.get("educational_qualifications"),
            "work_experience_years": employee.get("work_experience_years"),
            "previous_trainings": employee.get("previous_trainings") or [],
            "self_rated_skills": employee.get("self_rated_skills") or {},
            "quiz_verified_skills": {},
            "recommendations": enriched,
        },
    )
    return jsonify({"ok": True, "redirect": url_for("submission_results", submission_id=submission_id)})


# ---------------------------------------------------------------------------
# Recommendation results page
# ---------------------------------------------------------------------------

def _course_rows(submission: dict) -> list[dict]:
    """[(course, latest_attempt)] for each recommendation, in recommendation order.

    Shared by the results and profile pages so both render one action per course
    from the same shape (latest_attempt is the newest quiz_attempts row).
    """
    attempts_by_course: dict[str, list[dict]] = {}
    for attempt in db.list_attempts_for_submission(submission["id"]):
        attempts_by_course.setdefault(attempt["course_id"], []).append(attempt)
    rows = []
    for rec in submission.get("recommendations") or []:
        attempts = attempts_by_course.get(rec.get("course_id")) or []
        rows.append({"course": rec, "latest_attempt": attempts[-1] if attempts else None})
    return rows


def _recommendation_summary(submission: dict) -> tuple[str, str]:
    """(lead, sub) copy shown above the course cards (matches System 1's tone)."""
    recs = submission.get("recommendations") or []
    lead = RESULTS_LEAD
    if not recs:
        return lead, "No matching courses were found for this profile."
    addressed = {s for rec in recs for s in (rec.get("matched_skills") or [])}
    n = len(addressed)
    designation = submission.get("designation") or "your role"
    department = submission.get("department") or "your department"
    noun = "skill gap" if n == 1 else "skill gaps"
    sub = (
        f"These courses address the {n} {noun} identified for your "
        f"{designation} role in {department}."
    )
    return lead, sub


@app.route("/recommendation/results/<int:submission_id>")
@login_required
def submission_results(submission_id: int):
    submission = _owned_submission(submission_id)

    courses = _course_rows(submission)

    lead, sub = _recommendation_summary(submission)
    return render_template(
        "results.html",
        submission=submission,
        courses=courses,
        lead=lead,
        sub=sub,
    )


# ---------------------------------------------------------------------------
# Quiz: start (random Dataset-6 link -> background S2 pipeline)
# ---------------------------------------------------------------------------

def _random_dataset6_link() -> str:
    if not settings.DATASET6_CSV.exists():
        raise RuntimeError(f"Dataset-6 missing at {settings.DATASET6_CSV}")
    with open(settings.DATASET6_CSV, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        links = [row["Link"].strip() for row in reader if (row.get("Link") or "").strip()]
    if not links:
        raise RuntimeError("Dataset-6 contains no video links")
    return random.choice(links)


def _run_quiz_job(attempt_id: int, course_title: str, link: str) -> None:
    """Background worker: run S2's pipeline, persist ready/error to the DB."""
    if os.environ.get("ANTAHAI_FAKE_QUIZ") == "1":
        # Offline demo/test hook: skip network + LLM and serve canned MCQs.
        db.set_attempt_ready(attempt_id, _canned_quiz())
        return
    try:
        questions, _transcript = s2_bridge.generate_quiz(
            link, topic=course_title, num_questions=settings.QUIZ_QUESTION_COUNT
        )
    except Exception as error:  # noqa: BLE001 - store any failure on the row
        logger.exception("quiz generation failed for attempt %s", attempt_id)
        db.set_attempt_error(attempt_id, str(error) or "Quiz generation failed.")
        return
    db.set_attempt_ready(attempt_id, questions)


def _canned_quiz() -> list[dict]:
    """Three static MCQs used when ANTAHAI_FAKE_QUIZ=1 (offline demo/tests)."""
    return [
        {
            "id": 1,
            "question": "Which option best matches the lecture's main topic?",
            "options": ["Statistical methods", "Cooking recipes", "Vehicle repair", "Gardening"],
            "answer": "Statistical methods",
            "explanation": "Demo question - replace by running the real pipeline.",
            "verification_status": "verified",
        },
        {
            "id": 2,
            "question": "What is sampled in a sample survey?",
            "options": ["A subset of the population", "The entire population", "Only outliers", "Nothing"],
            "answer": "A subset of the population",
            "explanation": "A sample survey observes a subset and infers about the population.",
            "verification_status": "verified",
        },
        {
            "id": 3,
            "question": "Which is a measure of central tendency?",
            "options": ["Mean", "Range", "Variance", "Skewness"],
            "answer": "Mean",
            "explanation": "Mean, median and mode locate the centre of a distribution.",
            "verification_status": "verified",
        },
    ]


@app.route("/quiz/start", methods=["POST"])
@login_required
def quiz_start():
    submission_id = int(request.form.get("submission_id") or 0)
    course_id = (request.form.get("course_id") or "").strip()
    submission = _owned_submission(submission_id)

    course = next(
        (c for c in submission.get("recommendations") or [] if c.get("course_id") == course_id),
        None,
    )
    if not course:
        abort(404)

    # Reuse an in-flight or ready-but-ungraded attempt for this course rather
    # than spawning a duplicate generation.
    for attempt in db.list_attempts_for_submission(submission_id):
        if attempt["course_id"] == course_id and attempt["status"] in ("generating", "ready"):
            return redirect(url_for("quiz_attempt", attempt_id=attempt["id"]))

    try:
        link = _random_dataset6_link()
    except RuntimeError as error:
        logger.error("Dataset-6 read failed: %s", error)
        return "Dataset-6 could not be read by the server.", 500

    course_title = course.get("course_title") or course_id
    attempt_id = db.create_attempt(
        _require_user(), submission_id, course_id, course_title, source_link=link
    )
    thread = threading.Thread(
        target=_run_quiz_job,
        args=(attempt_id, course_title, link),
        name=f"quiz-{attempt_id}",
        daemon=True,
    )
    thread.start()
    return redirect(url_for("quiz_attempt", attempt_id=attempt_id))


@app.route("/quiz/<int:attempt_id>", methods=["GET", "POST"])
@login_required
def quiz_attempt(attempt_id: int):
    attempt = _owned_attempt(attempt_id)

    if attempt["status"] == "graded":
        return redirect(url_for("quiz_results", attempt_id=attempt_id))

    # Generation still running (or failed) - show the status/poll view.
    if attempt["status"] != "ready":
        return render_template("quiz_status.html", attempt=attempt)

    if request.method == "POST":
        try:
            quiz = json.loads(attempt["quiz"]) if attempt.get("quiz") else []
        except json.JSONDecodeError:
            abort(500)
        answers = {}
        for q in quiz:
            value = request.form.get(f"q_{q['id']}")
            if value:
                answers[str(q["id"])] = value
        db.grade_attempt(attempt_id, answers, quiz)
        return redirect(url_for("quiz_results", attempt_id=attempt_id))

    # Render only what the quiz-taker may see (correct answers stay hidden).
    try:
        quiz = json.loads(attempt["quiz"]) if attempt.get("quiz") else []
    except json.JSONDecodeError:
        abort(500)
    questions = [
        {"id": q.get("id"), "question": q.get("question", ""), "options": q.get("options", [])}
        for q in quiz
    ]
    return render_template("quiz.html", attempt=attempt, questions=questions)


@app.route("/quiz/<int:attempt_id>/status.json")
@login_required
def quiz_status_json(attempt_id: int):
    attempt = _owned_attempt(attempt_id)
    return jsonify({"status": attempt["status"], "error": attempt.get("error")})


@app.route("/quiz/<int:attempt_id>/results")
@login_required
def quiz_results(attempt_id: int):
    attempt = _owned_attempt(attempt_id)
    if attempt["status"] != "graded":
        return redirect(url_for("quiz_attempt", attempt_id=attempt_id))
    review = db.graded_review(attempt_id) or {
        "score": 0, "total": 0, "accuracy": 0.0, "details": []
    }
    return render_template(
        "quiz_results.html",
        attempt=attempt,
        review=review,
        notice=settings.ONE_ATTEMPT_NOTICE,
    )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@app.route("/profile")
@login_required
def profile():
    try:
        skill_names = {
            s["skill_id"]: s.get("skill_name", s["skill_id"])
            for s in s1_client.meta_skills()
        }
    except (s1_client.S1Unavailable, s1_client.S1Error):
        skill_names = {}

    submissions = []
    for submission in db.list_submissions(_require_user()):
        submissions.append({"submission": submission, "courses": _course_rows(submission)})

    return render_template(
        "profile.html",
        submissions=submissions,
        skill_names=skill_names,
    )


# ---------------------------------------------------------------------------
# Learning Pathways (competency profile, goals, recommendations, roadmaps,
# course player, assessments). Lives in ./pathways; shares auth + DB.
# ---------------------------------------------------------------------------

import pathways.web as pathways_web  # noqa: E402

pathways_web.init_app(
    app,
    _hash_password,
    dataset2_csv=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "System-1 Recommandation_Engine", "datasets", "Dataset-2_Required_Competency.csv",
    ),
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    db.init_db()
    logger.info("Antah.ai running on http://%s:%s  (System 1: %s)",
                settings.FLASK_HOST, settings.FLASK_PORT, settings.S1_URL)
    app.run(host=settings.FLASK_HOST, port=settings.FLASK_PORT, threaded=True, debug=False)
