"""
AntahAI Learning Pathways - application services.

Orchestrates store (DB) + rules (evidence/grading) + engine (recommendation,
roadmap). Every state change that can affect recommendations - self-report,
confirmed resume skill, lesson progress, quiz pass, lab pass - ends with
``refresh_all_roadmaps(user_id)`` so that *every* saved roadmap of the learner
reflects the shared competency profile and shared course completions.
"""

from __future__ import annotations

import json
import os

from . import engine, rules, store


class NotFound(LookupError):
    pass


class ValidationError(ValueError):
    pass


def score_weights() -> dict | None:
    """Optional override: ANTAHAI_SCORE_WEIGHTS='{"gap_coverage":0.6,...}'."""
    raw = os.environ.get("ANTAHAI_SCORE_WEIGHTS")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return {k: float(v) for k, v in data.items()}
    except (ValueError, TypeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Learner state
# ---------------------------------------------------------------------------

def levels(user_id: int) -> dict:
    return rules.effective_levels(store.evidence(user_id))


def progress(user_id: int) -> dict[str, dict]:
    """Shared course progress: one record per course, used by every roadmap."""
    out: dict[str, dict] = {}
    lesson_counts = {c["id"]: c for c in store.engine_courses()}
    enr = store.enrollments(user_id)
    atts = store.attempts(user_id)
    labs = store.lab_submissions(user_id)
    for cid, e in enr.items():
        course = lesson_counts.get(cid)
        n_lessons = len(store._rows("SELECT id FROM pw_lessons WHERE course_id=?", (cid,)))
        course_atts = [a for a in atts if a["course_id"] == cid]
        quiz_passed = any(a["passed"] for a in course_atts)
        lab_passed = any(l["passed"] for l in labs if l["course_id"] == cid)
        steps = n_lessons + 1 + (1 if course and course["has_lab"] else 0)
        done = len(e["lessons_done"]) + (1 if quiz_passed else 0) + (1 if lab_passed else 0)
        out[cid] = {
            "status": e["status"],
            "percent": 100 if e["status"] == "completed" else int(round(100 * done / max(1, steps))),
            "lessons_done": e["lessons_done"],
            "quiz_attempts": len(course_atts),
            "quiz_passed": quiz_passed,
            "best_score": max((a["result"]["percent"] for a in course_atts), default=None),
            "lab_passed": lab_passed,
            "started_at": e["started_at"],
            "completed_at": e["completed_at"],
        }
    return out


def learner_name(user_id: int, fallback: str = "You") -> str:
    prof = store.get_profile(user_id)
    return prof.get("display_name") or fallback


def profile_view(user_id: int) -> dict:
    comps = store.competencies()
    lv = levels(user_id)
    ev = store.evidence(user_id)
    rows = []
    for cid, comp in comps.items():
        entry = lv.get(cid) or {"level": 0, "basis": "none", "confidence": 0.0,
                                "self_reported": None, "assessed": None, "suggested": None,
                                "explanation": "No evidence."}
        rows.append({
            "id": cid, "name": comp["name"], "category": comp["category"],
            "description": comp["description"], "s1_skill_id": comp.get("s1_skill_id"),
            **entry,
            "evidence": [
                {k: e[k] for k in ("id", "source", "level", "confidence", "confirmed", "note", "created_at")}
                for e in ev if e["competency_id"] == cid
            ],
        })
    suggestions = [
        {"id": e["id"], "competency": e["competency_id"], "name": comps[e["competency_id"]]["name"],
         "level": e["level"], "note": e["note"]}
        for e in ev if e["source"] == "resume_inferred" and not e["confirmed"]
    ]
    return {"profile": store.get_profile(user_id), "competencies": rows, "suggestions": suggestions,
            "organizations": store.organizations()}


# ---------------------------------------------------------------------------
# Profile updates
# ---------------------------------------------------------------------------

def update_profile(user_id: int, basics: dict, self_levels: dict) -> dict:
    comps = store.competencies()
    clean: dict = {}
    if "display_name" in basics:
        clean["display_name"] = str(basics.get("display_name") or "").strip()[:80]
    if "education" in basics:
        clean["education"] = str(basics.get("education") or "").strip()[:160]
    if "interests" in basics:
        clean["interests"] = str(basics.get("interests") or "").strip()[:300]
    if "experience_years" in basics:
        val = basics.get("experience_years")
        if val in (None, ""):
            clean["experience_years"] = None
        else:
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise ValidationError("Experience must be a whole number of years.")
            if not 0 <= val <= 60:
                raise ValidationError("Experience must be between 0 and 60 years.")
            clean["experience_years"] = val
    if "organization_id" in basics:
        org = basics.get("organization_id") or None
        if org and org not in {o["id"] for o in store.organizations()}:
            raise ValidationError("Unknown organisation.")
        clean["organization_id"] = org
    if clean:
        store.save_profile(user_id, clean)

    current = levels(user_id)
    changed = []
    for cid, value in (self_levels or {}).items():
        if cid not in comps:
            raise ValidationError(f"Unknown competency: {cid}")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"Level for {comps[cid]['name']} must be a number 0-100.")
        if not 0 <= value <= 100:
            raise ValidationError(f"Level for {comps[cid]['name']} must be between 0 and 100.")
        prev = (current.get(cid) or {}).get("self_reported")
        if prev == value or (prev is None and value == 0):
            continue
        store.add_evidence(user_id, cid, "self_reported", value, note="Self-reported rating.")
        changed.append(cid)
    if changed or clean:
        refresh_all_roadmaps(user_id)
    return {"changed": changed}


def confirm_suggestion(user_id: int, evidence_id: int, level: int | None, accept: bool) -> None:
    row = next((e for e in store.evidence(user_id)
                if e["id"] == evidence_id and e["source"] == "resume_inferred"), None)
    if not row:
        raise NotFound("Suggestion not found.")
    if not accept:
        store.delete_evidence(evidence_id, user_id, "resume_inferred")
        return
    level = row["level"] if level is None else int(level)
    if not 0 <= level <= 100:
        raise ValidationError("Level must be between 0 and 100.")
    store.update_evidence(evidence_id, user_id, confirmed=1)
    store.add_evidence(user_id, row["competency_id"], "self_reported", level,
                       note=f"Confirmed by learner from resume suggestion ({row['note']})",
                       origin=f"resume_evidence:{evidence_id}")
    refresh_all_roadmaps(user_id)


def store_resume_suggestions(user_id: int, suggestions: list[dict]) -> int:
    # Replace previous unconfirmed suggestions so re-uploading does not pile up.
    for e in store.evidence(user_id):
        if e["source"] == "resume_inferred" and not e["confirmed"]:
            store.delete_evidence(e["id"], user_id, "resume_inferred")
    for s in suggestions:
        store.add_evidence(user_id, s["competency"], "resume_inferred", s["level"],
                           note=s["note"], origin=s.get("method", "keyword"))
    return len(suggestions)


# ---------------------------------------------------------------------------
# Goals, analysis, roadmaps
# ---------------------------------------------------------------------------

def _goal(goal_id: str) -> dict:
    goal = store.goals().get(goal_id)
    if not goal:
        raise NotFound("Unknown goal.")
    return goal


def analyze_goal(user_id: int, goal_id: str, include_revision: bool = False) -> dict:
    goal = _goal(goal_id)
    comps = store.competencies()
    lv = levels(user_id)
    result = engine.build_recommendations(goal, store.engine_courses(), lv, progress(user_id),
                                          comps, score_weights(), include_revision)
    result["goal"] = goal
    result["entry_prerequisites"] = [
        dict(p, name=comps[p["competency"]]["name"],
             current=engine.level_of(lv, p["competency"]),
             satisfied=engine.level_of(lv, p["competency"]) >= p["min_level"])
        for p in goal.get("entry_prerequisites", [])
    ]
    existing = store.roadmap_for_goal(user_id, goal_id)
    result["roadmap_id"] = existing["id"] if existing else None
    return result


def generate_roadmap(user_id: int, goal_id: str, username: str = "You") -> int:
    goal = _goal(goal_id)
    existing = store.roadmap_for_goal(user_id, goal_id)
    preserved_courses, preserved_edges = ([], [])
    if existing:
        preserved_courses, preserved_edges = store.roadmap_history(existing["id"])
    graph = engine.build_roadmap(
        goal, store.engine_courses(), levels(user_id), progress(user_id), store.competencies(),
        score_weights(), preserved_courses=preserved_courses, preserved_edges=preserved_edges,
        learner_name=learner_name(user_id, username),
    )
    return store.save_roadmap(user_id, goal_id, graph)


def refresh_all_roadmaps(user_id: int) -> list[int]:
    ids = []
    for r in store.list_roadmaps(user_id):
        ids.append(generate_roadmap(user_id, r["goal_id"]))
    return ids


def dashboard(user_id: int) -> dict:
    comps = store.competencies()
    lv = levels(user_id)
    prog = progress(user_id)
    courses = {c["id"]: c for c in store.engine_courses()}
    history = []
    for cid, p in prog.items():
        if cid in courses:
            history.append({"course_id": cid, "title": courses[cid]["title"], **p})
    history.sort(key=lambda h: (h["completed_at"] or h["started_at"] or ""), reverse=True)
    validated = sum(1 for e in lv.values() if e["basis"] == "assessment")
    return {
        "profile": store.get_profile(user_id),
        "roadmaps": store.list_roadmaps(user_id),
        "levels": [
            {"id": cid, "name": comps[cid]["name"], "category": comps[cid]["category"],
             **(lv.get(cid) or {"level": 0, "basis": "none"})}
            for cid in comps
        ],
        "history": history,
        "stats": {
            "validated": validated,
            "self_reported": sum(1 for e in lv.values() if e["basis"] == "self_reported"),
            "completed_courses": sum(1 for p in prog.values() if p["status"] == "completed"),
            "in_progress": sum(1 for p in prog.values() if p["status"] == "in_progress"),
        },
    }


# ---------------------------------------------------------------------------
# Learning loop
# ---------------------------------------------------------------------------

def course_for_learner(user_id: int, course_id: str) -> dict:
    course = store.course_detail(course_id)
    if not course:
        raise NotFound("Unknown course.")
    comps = store.competencies()
    lv = levels(user_id)
    course["prereq_status"] = engine.prerequisite_status(course, lv, comps)
    course["locked"] = any(not p["satisfied"] for p in course["prereq_status"])
    course["progress"] = progress(user_id).get(course_id, {"status": "not_started", "percent": 0,
                                                           "lessons_done": [], "quiz_passed": False,
                                                           "lab_passed": False, "quiz_attempts": 0})
    course["develops_named"] = [
        {"competency": c, "name": comps[c]["name"], "reaches": v,
         "current": engine.level_of(lv, c), "basis": engine.basis_of(lv, c)}
        for c, v in course["develops"].items()
    ]
    return course


def _ensure_startable(user_id: int, course: dict) -> None:
    if course["availability"] != "available":
        raise ValidationError("This course is not available: its content has not been verified.")
    if course["locked"] and course["progress"]["status"] == "not_started":
        missing = "; ".join(f"{p['name']} ≥ {p['min_level']} (you: {p['current']})"
                            for p in course["prereq_status"] if not p["satisfied"])
        raise ValidationError(f"Prerequisites not met: {missing}.")


def start_course(user_id: int, course_id: str) -> dict:
    course = course_for_learner(user_id, course_id)
    _ensure_startable(user_id, course)
    if course["progress"]["status"] == "not_started":
        store.upsert_enrollment(user_id, course_id, "in_progress", [])
        refresh_all_roadmaps(user_id)
    return course_for_learner(user_id, course_id)


def mark_lesson(user_id: int, course_id: str, lesson_id: str) -> dict:
    """Progress only - never changes competency levels."""
    course = start_course(user_id, course_id)
    if lesson_id not in {l["id"] for l in course["lessons"]}:
        raise NotFound("Unknown lesson.")
    done = list(course["progress"].get("lessons_done") or [])
    if lesson_id not in done:
        done.append(lesson_id)
        store.upsert_enrollment(user_id, course_id, None, done)
        refresh_all_roadmaps(user_id)
    return course_for_learner(user_id, course_id)


def _complete_if_done(user_id: int, course: dict) -> bool:
    prog = progress(user_id).get(course["id"], {})
    done = prog.get("quiz_passed") and (not course.get("lab") or prog.get("lab_passed"))
    if done:
        store.upsert_enrollment(user_id, course["id"], "completed")
    return bool(done)


def _level_changes(before: dict, after: dict, comps: dict) -> list[dict]:
    out = []
    for cid in comps:
        b, a = before.get(cid) or {}, after.get(cid) or {}
        if (b.get("level"), b.get("basis")) != (a.get("level"), a.get("basis")):
            out.append({"competency": cid, "name": comps[cid]["name"],
                        "before": b.get("level", 0), "before_basis": b.get("basis", "none"),
                        "after": a.get("level", 0), "after_basis": a.get("basis", "none")})
    return out


def _roadmap_snapshot(user_id: int) -> dict[int, dict]:
    return {r["id"]: r for r in store.list_roadmaps(user_id)}


def _roadmap_changes(before: dict, after: dict) -> list[dict]:
    out = []
    for rid, a in after.items():
        b = before.get(rid, {})
        out.append({"id": rid, "goal_title": a["goal_title"],
                    "progress_before": b.get("progress"), "progress_after": a["progress"],
                    "readiness_before": b.get("readiness"), "readiness_after": a["readiness"],
                    "next_action": a["next_action"]})
    return out


def submit_quiz(user_id: int, course_id: str, raw_answers: dict) -> dict:
    course = course_for_learner(user_id, course_id)
    _ensure_startable(user_id, course)
    if not course["questions"]:
        raise ValidationError("This course has no assessment.")
    answers: dict[str, int | None] = {}
    for q in course["questions"]:
        val = raw_answers.get(q["id"])
        if val in (None, ""):
            answers[q["id"]] = None
            continue
        try:
            idx = int(val)
        except (TypeError, ValueError):
            raise ValidationError("Invalid answer submitted.")
        if not 0 <= idx < len(q["options"]):
            raise ValidationError("Invalid answer submitted.")
        answers[q["id"]] = idx

    comps = store.competencies()
    before_lv = levels(user_id)
    before_rm = _roadmap_snapshot(user_id)
    if course["progress"]["status"] == "not_started":
        store.upsert_enrollment(user_id, course_id, "in_progress", [])

    result = rules.grade_quiz(course["questions"], answers, float(course["assessment"]["pass_threshold"]))
    attempt_id = store.record_attempt(user_id, course_id, answers, result)
    for ev in rules.assessment_evidence(course, result):
        store.add_evidence(user_id, ev["competency"], "assessment", ev["level"], note=ev["note"],
                           origin=f"assessment_attempt:{attempt_id}")
    completed = _complete_if_done(user_id, course)
    refresh_all_roadmaps(user_id)
    after_lv = levels(user_id)
    return {
        "attempt_id": attempt_id,
        "result": result,
        "remediation": [] if result["passed"] else rules.remediation_plan(result, course["lessons"], comps),
        "competency_changes": _level_changes(before_lv, after_lv, comps),
        "course_completed": completed,
        "needs_lab": bool(course.get("lab")) and result["passed"] and not completed,
        "roadmaps": _roadmap_changes(before_rm, _roadmap_snapshot(user_id)),
    }


def submit_lab(user_id: int, course_id: str, answers: dict, interpretation: str) -> dict:
    course = course_for_learner(user_id, course_id)
    if not course.get("lab"):
        raise NotFound("This course has no lab.")
    if not course["progress"].get("quiz_passed"):
        raise ValidationError("Pass the course assessment before submitting the lab.")
    comps = store.competencies()
    before_lv = levels(user_id)
    before_rm = _roadmap_snapshot(user_id)
    interpretation = (interpretation or "").strip()[:4000]
    clean = {t["id"]: str(answers.get(t["id"], ""))[:40] for t in course["lab"]["tasks"]}
    result = rules.check_lab(course["lab"], clean, interpretation)
    sub_id = store.record_lab(user_id, course_id, course["lab"]["id"], clean, interpretation, result)
    for ev in rules.lab_evidence(course, course["lab"], result["passed"]):
        store.add_evidence(user_id, ev["competency"], "assessment", ev["level"], note=ev["note"],
                           origin=f"lab_submission:{sub_id}")
    completed = _complete_if_done(user_id, course)
    refresh_all_roadmaps(user_id)
    return {
        "submission_id": sub_id, "result": result, "course_completed": completed,
        "competency_changes": _level_changes(before_lv, levels(user_id), comps),
        "roadmaps": _roadmap_changes(before_rm, _roadmap_snapshot(user_id)),
    }


# ---------------------------------------------------------------------------
# Demo learners
# ---------------------------------------------------------------------------

def seed_demo_learners(raw: dict, create_user, get_user, force_reset: bool = False) -> list[int]:
    """Create demo learners (idempotent). ``create_user(username, password)`` -> id."""
    ids = []
    for d in raw.get("demo_learners", []):
        user = get_user(d["username"])
        uid = user["id"] if user else create_user(d["username"], d["password"])
        if force_reset:
            store.reset_learner(uid)
        store.save_profile(uid, {"display_name": d["display_name"],
                                 "experience_years": d.get("experience_years"),
                                 "education": d.get("education", ""),
                                 "interests": d.get("interests", ""), "is_demo": 1})
        if not store.evidence(uid):
            for e in d["evidence"]:
                store.add_evidence(uid, e["competency"], e["source"], e["level"],
                                   note=e.get("note") or "Demo learner self-rating (demonstration data).",
                                   origin="demo_seed")
        ids.append(uid)
    return ids
