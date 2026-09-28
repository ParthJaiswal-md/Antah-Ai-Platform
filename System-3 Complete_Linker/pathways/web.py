"""
AntahAI Learning Pathways - Flask blueprint (pages + JSON API).

Mounted by ``app.py`` via ``init_app(app, hash_password)``. Uses System 3's
session login (``session['user_id']``) so there is one account system.
"""

from __future__ import annotations

import html
import logging
import re
import secrets
from functools import wraps

from flask import (Blueprint, abort, current_app, jsonify, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup

import db as core_db

from . import catalogue as cat
from . import engine, resume, rules, service, store

logger = logging.getLogger(__name__)

bp = Blueprint("pathways", __name__)

DISCLAIMER = cat.load_raw()["_meta"]["disclaimer"]


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def init_app(app, hash_password, dataset2_csv=None) -> None:
    """Create tables, seed catalogue/orgs/demo learners, register routes."""
    store.migrate()
    store.seed_catalogue()
    try:
        store.seed_organizations(dataset2_csv)
    except Exception:  # noqa: BLE001 - master data is optional
        logger.warning("organisation seed skipped", exc_info=True)

    def create_user(username, password):
        return core_db.create_user(username, hash_password(username, password))

    service.seed_demo_learners(cat.load_raw(), create_user, core_db.get_user_by_username)
    app.config["PW_HASH"] = hash_password
    app.config.setdefault("MAX_CONTENT_LENGTH", 4 * 1024 * 1024)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.jinja_env.filters["lesson_html"] = lesson_html
    app.jinja_env.filters["minutes"] = fmt_minutes
    app.register_blueprint(bp)

    @app.context_processor
    def _inject():
        return {"csrf_token": csrf_token(), "pw_disclaimer": DISCLAIMER}


def csrf_token() -> str:
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        session["_csrf"] = tok
    return tok


@bp.before_request
def _csrf_protect():
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Your session expired. Reload the page."}), 400
            abort(400)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Please log in."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def uid() -> int:
    return int(session["user_id"])


def api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def api_guard(fn):
    """Translate service exceptions into JSON errors."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except service.NotFound as err:
            return api_error(str(err), 404)
        except (service.ValidationError, resume.ResumeError) as err:
            return api_error(str(err), 422)
        except engine.PrerequisiteCycleError as err:
            return api_error(str(err), 409)
    return wrapped


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _inline(text: str) -> str:
    out = html.escape(text)
    out = _INLINE_CODE.sub(r"<code>\1</code>", out)
    return _BOLD.sub(r"<strong>\1</strong>", out)


def lesson_html(blocks) -> Markup:
    """Render lesson blocks (strings / {"code": [...]}) to safe HTML."""
    parts, items = [], []

    def flush():
        if items:
            parts.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for block in blocks or []:
        if isinstance(block, dict) and "code" in block:
            flush()
            code = html.escape("\n".join(block["code"]))
            parts.append(f'<pre class="code"><code>{code}</code></pre>')
        elif isinstance(block, str) and block.startswith("- "):
            items.append(_inline(block[2:]))
        else:
            flush()
            parts.append(f"<p>{_inline(str(block))}</p>")
    flush()
    return Markup("\n".join(parts))


def fmt_minutes(value) -> str:
    if not value:
        return "Not specified"
    value = int(value)
    h, m = divmod(value, 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@bp.route("/dashboard")
@login_required
def dashboard():
    data = service.dashboard(uid())
    return render_template("pw/dashboard.html", d=data, goals=store.goals())


@bp.route("/competencies")
@login_required
def competencies_page():
    return render_template("pw/competencies.html", v=service.profile_view(uid()))


@bp.route("/goals")
@login_required
def goals_page():
    goals = store.goals()
    comps = store.competencies()
    lv = service.levels(uid())
    saved = {r["goal_id"]: r for r in store.list_roadmaps(uid())}
    cards = []
    for g in goals.values():
        gaps = engine.compute_gaps(g, lv, comps)
        cards.append({"goal": g, "gaps": gaps, "readiness": engine.goal_readiness(gaps),
                      "saved": saved.get(g["id"])})
    return render_template("pw/goals.html", cards=cards)


@bp.route("/goals/<goal_id>")
@login_required
def goal_page(goal_id):
    try:
        analysis = service.analyze_goal(uid(), goal_id,
                                        include_revision=request.args.get("revision") == "1")
    except service.NotFound:
        abort(404)
    return render_template("pw/goal.html", a=analysis, courses={c["id"]: c for c in store.engine_courses()})


@bp.route("/roadmaps/<int:roadmap_id>")
@login_required
def roadmap_page(roadmap_id):
    rm = store.get_roadmap(uid(), roadmap_id)
    if not rm:
        abort(404)
    return render_template("pw/roadmap.html", rm=rm, all_roadmaps=store.list_roadmaps(uid()))


@bp.route("/learn/<course_id>")
@login_required
def course_page(course_id):
    try:
        course = service.course_for_learner(uid(), course_id)
    except service.NotFound:
        abort(404)
    lesson_id = request.args.get("lesson")
    lessons = course["lessons"]
    current = next((l for l in lessons if l["id"] == lesson_id), None)
    if current is None and lessons:
        done = set(course["progress"].get("lessons_done") or [])
        current = next((l for l in lessons if l["id"] not in done), lessons[0])
    return render_template("pw/course.html", c=course, lesson=current,
                           from_roadmap=request.args.get("roadmap"))


@bp.route("/learn/<course_id>/assessment", methods=["GET", "POST"])
@login_required
def assessment_page(course_id):
    try:
        course = service.course_for_learner(uid(), course_id)
    except service.NotFound:
        abort(404)
    if request.method == "POST":
        answers = {q["id"]: request.form.get(f"q_{q['id']}") for q in course["questions"]}
        try:
            out = service.submit_quiz(uid(), course_id, answers)
        except service.ValidationError as err:
            return render_template("pw/assessment.html", c=course, error=str(err)), 422
        # Before/after deltas are only known at submit time; keep them for the result page.
        session["pw_last"] = {"attempt_id": out["attempt_id"],
                              "changes": out["competency_changes"], "roadmaps": out["roadmaps"],
                              "needs_lab": out["needs_lab"], "completed": out["course_completed"]}
        return redirect(url_for("pathways.assessment_result", course_id=course_id,
                                attempt_id=out["attempt_id"], roadmap=request.args.get("roadmap")))
    error = None
    if course["availability"] != "available":
        error = "This course is not available, so it has no assessment."
    elif course["locked"] and course["progress"]["status"] == "not_started":
        error = "Prerequisites are not met yet."
    return render_template("pw/assessment.html", c=course, error=error)


@bp.route("/learn/<course_id>/assessment/<int:attempt_id>")
@login_required
def assessment_result(course_id, attempt_id):
    attempt = store.get_attempt(uid(), attempt_id)
    if not attempt or attempt["course_id"] != course_id:
        abort(404)
    course = service.course_for_learner(uid(), course_id)
    result = attempt["result"]
    comps = store.competencies()
    remediation = [] if result["passed"] else rules.remediation_plan(result, course["lessons"], comps)
    evidence = [e for e in store.evidence(uid()) if e["origin"] == f"assessment_attempt:{attempt_id}"]
    all_attempts = store.attempts(uid(), course_id)
    last = session.get("pw_last") or {}
    fresh = last if last.get("attempt_id") == attempt_id else {}
    return render_template("pw/result.html", c=course, attempt=attempt, r=result,
                           remediation=remediation, evidence=evidence, comps=comps,
                           levels=service.levels(uid()), roadmaps=store.list_roadmaps(uid()),
                           attempts=all_attempts, fresh=fresh, rid=request.args.get("roadmap"))


@bp.route("/learn/<course_id>/lab", methods=["GET", "POST"])
@login_required
def lab_page(course_id):
    try:
        course = service.course_for_learner(uid(), course_id)
    except service.NotFound:
        abort(404)
    if not course.get("lab"):
        abort(404)
    outcome, error = None, None
    form = {}
    if request.method == "POST":
        form = {t["id"]: request.form.get(t["id"], "") for t in course["lab"]["tasks"]}
        form["interpretation"] = request.form.get("interpretation", "")
        try:
            outcome = service.submit_lab(uid(), course_id, form, form["interpretation"])
            course = service.course_for_learner(uid(), course_id)
        except service.ValidationError as err:
            error = str(err)
    return render_template("pw/lab.html", c=course, outcome=outcome, error=error, form=form,
                           submissions=store.lab_submissions(uid(), course_id),
                           roadmaps=store.list_roadmaps(uid()))


@bp.route("/compare")
@login_required
def compare_page():
    goals = store.goals()
    goal_id = request.args.get("goal") or "stat_data_analyst"
    if goal_id not in goals:
        abort(404)
    return render_template("pw/compare.html", goals=goals, goal_id=goal_id)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@bp.route("/api/pathways/profile", methods=["GET", "PUT"])
@login_required
@api_guard
def api_profile():
    if request.method == "PUT":
        body = request.get_json(silent=True) or {}
        out = service.update_profile(uid(), body.get("basics") or {}, body.get("levels") or {})
        return jsonify({"ok": True, **out, "view": service.profile_view(uid())})
    return jsonify({"ok": True, "view": service.profile_view(uid())})


@bp.route("/api/pathways/resume", methods=["POST"])
@login_required
@api_guard
def api_resume():
    upload = request.files.get("file")
    if upload and upload.filename:
        text = resume.text_from_upload(upload.filename, upload.read(resume.MAX_UPLOAD_BYTES + 1))
    else:
        text = (request.form.get("text") or (request.get_json(silent=True) or {}).get("text") or "")
    suggestions = resume.extract(text, store.competencies())
    service.store_resume_suggestions(uid(), suggestions)
    return jsonify({"ok": True, "count": len(suggestions), "view": service.profile_view(uid())})


@bp.route("/api/pathways/resume/<int:evidence_id>", methods=["POST"])
@login_required
@api_guard
def api_resume_decision(evidence_id):
    body = request.get_json(silent=True) or {}
    level = body.get("level")
    service.confirm_suggestion(uid(), evidence_id, None if level in (None, "") else level,
                               bool(body.get("accept")))
    return jsonify({"ok": True, "view": service.profile_view(uid())})


@bp.route("/api/pathways/goals/<goal_id>/analysis")
@login_required
@api_guard
def api_goal_analysis(goal_id):
    return jsonify({"ok": True, "analysis": service.analyze_goal(
        uid(), goal_id, include_revision=request.args.get("revision") == "1")})


@bp.route("/api/pathways/roadmaps", methods=["GET", "POST"])
@login_required
@api_guard
def api_roadmaps():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        goal_id = str(body.get("goal_id") or "")
        if not body.get("confirmed"):
            raise service.ValidationError("Please confirm the goal's competency requirements first.")
        rid = service.generate_roadmap(uid(), goal_id, session.get("username", "You"))
        return jsonify({"ok": True, "id": rid, "url": url_for("pathways.roadmap_page", roadmap_id=rid)})
    return jsonify({"ok": True, "roadmaps": store.list_roadmaps(uid())})


@bp.route("/api/pathways/roadmaps/<int:roadmap_id>", methods=["GET", "DELETE"])
@login_required
@api_guard
def api_roadmap(roadmap_id):
    if request.method == "DELETE":
        if not store.delete_roadmap(uid(), roadmap_id):
            raise service.NotFound("Roadmap not found.")
        return jsonify({"ok": True})
    rm = store.get_roadmap(uid(), roadmap_id)
    if not rm:
        raise service.NotFound("Roadmap not found.")
    return jsonify({"ok": True, "roadmap": rm})


@bp.route("/api/pathways/roadmaps/<int:roadmap_id>/regenerate", methods=["POST"])
@login_required
@api_guard
def api_roadmap_regenerate(roadmap_id):
    rm = store.get_roadmap(uid(), roadmap_id)
    if not rm:
        raise service.NotFound("Roadmap not found.")
    service.generate_roadmap(uid(), rm["goal_id"], session.get("username", "You"))
    return jsonify({"ok": True, "roadmap": store.get_roadmap(uid(), roadmap_id)})


@bp.route("/api/pathways/courses/<course_id>/start", methods=["POST"])
@login_required
@api_guard
def api_course_start(course_id):
    service.start_course(uid(), course_id)
    return jsonify({"ok": True, "url": url_for("pathways.course_page", course_id=course_id)})


@bp.route("/api/pathways/courses/<course_id>/lessons/<lesson_id>/complete", methods=["POST"])
@login_required
@api_guard
def api_lesson_complete(course_id, lesson_id):
    course = service.mark_lesson(uid(), course_id, lesson_id)
    ids = [l["id"] for l in course["lessons"]]
    nxt = ids[ids.index(lesson_id) + 1] if ids.index(lesson_id) + 1 < len(ids) else None
    return jsonify({
        "ok": True, "progress": course["progress"],
        "next": (url_for("pathways.course_page", course_id=course_id, lesson=nxt) if nxt
                 else url_for("pathways.assessment_page", course_id=course_id)),
    })


@bp.route("/api/pathways/compare")
@login_required
@api_guard
def api_compare():
    goal_id = request.args.get("goal") or "stat_data_analyst"
    goal = store.goals().get(goal_id)
    if not goal:
        raise service.NotFound("Unknown goal.")
    out = []
    comps = store.competencies()
    courses = store.engine_courses()
    for d in cat.load_raw()["demo_learners"]:
        user = core_db.get_user_by_username(d["username"])
        if not user:
            continue
        lid = user["id"]
        saved = store.roadmap_for_goal(lid, goal_id)
        hist_courses, hist_edges = store.roadmap_history(saved["id"]) if saved else ([], [])
        graph = engine.build_roadmap(goal, courses, service.levels(lid), service.progress(lid), comps,
                                     service.score_weights(), preserved_courses=hist_courses,
                                     preserved_edges=hist_edges, learner_name=service.learner_name(lid))
        out.append({"username": d["username"], "name": service.learner_name(lid),
                    "profile": store.get_profile(lid), "roadmap": graph})
    return jsonify({"ok": True, "goal": goal, "learners": out})


@bp.route("/api/pathways/demo/reset", methods=["POST"])
@login_required
@api_guard
def api_demo_reset():
    prof = store.get_profile(uid())
    if not prof.get("is_demo"):
        return api_error("Only demo accounts can reset demo data.", 403)
    raw = cat.load_raw()
    hash_fn = current_app.config["PW_HASH"]
    service.seed_demo_learners(
        raw, lambda u, p: core_db.create_user(u, hash_fn(u, p)), core_db.get_user_by_username,
        force_reset=True)
    return jsonify({"ok": True})
