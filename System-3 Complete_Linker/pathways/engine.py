"""
AntahAI Learning Pathways - deterministic recommendation + roadmap engine.

Everything in this module is pure (no DB, no network, no AI) so that ranking,
gap calculation, prerequisite ordering and graph generation are reproducible
and unit-testable. Inputs are plain dicts produced by ``pathways.store``:

    competencies : {comp_id: {"id", "name", ...}}
    courses      : [{"id", "title", "difficulty", "availability", "develops": {comp: level},
                     "prerequisites": [{"competency", "min_level"}], "duration_minutes", ...}]
    goal         : {"id", "title", "requirements": [{"competency", "target", "weight"}]}
    levels       : {comp_id: {"level": 0-100, "basis": "assessment"|"self_reported"|"none", ...}}
    progress     : {course_id: {"status": "not_started"|"in_progress"|"completed", "percent": int}}

Key rules (see README_PATHWAYS.md for the full description):
  * Prerequisites are *competency thresholds*, not course IDs. A learner who
    already meets a threshold is never sent through the course that teaches it.
  * A hard prerequisite can never be overridden by a high score: a course with
    an unmet prerequisite is "locked" and cannot be a "start now" recommendation.
  * Completed courses are excluded from recommendations (unless revision is
    requested) but are kept on the roadmap as completed history.
  * Course metadata is data. Nothing here references a specific course ID.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Starting weights for the transparent score. They are configurable starting
#: points (see ``ANTAHAI_SCORE_WEIGHTS``), not claims of calibrated accuracy.
DEFAULT_WEIGHTS: dict[str, float] = {
    "gap_coverage": 0.50,
    "goal_relevance": 0.25,
    "prereq_readiness": 0.15,
    "level_fit": 0.10,
}

DIFFICULTY_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}

#: Learner "band" thresholds on the 0-100 scale, used for difficulty fit.
BAND_THRESHOLDS = (35, 65)

#: Node footprint (px) used by the server-side layout. The front-end draws
#: nodes centred on the computed (x, y), so these must match the CSS widths.
NODE_SIZE = {
    "start": (230, 120),
    "course": (250, 118),
    "assessment": (176, 64),
    "lab": (196, 72),
    "milestone": (200, 70),
    "goal": (250, 130),
}
LAYER_GAP = 70        # horizontal gap between layers
ROW_GAP = 46          # vertical gap between nodes in a layer
WAVE_AMPLITUDE = 70   # vertical "winding" of the journey, px
WAVE_FREQUENCY = 0.95


class PrerequisiteCycleError(ValueError):
    """Raised when course prerequisites form a cycle (roadmap would be invalid)."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(
            "Prerequisite cycle detected: " + " -> ".join(cycle)
            + ". Fix the course prerequisite definitions; no roadmap was generated."
        )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Return non-negative weights that sum to 1 (falls back to defaults)."""
    merged = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, value in weights.items():
            if key in merged:
                merged[key] = max(0.0, float(value))
    total = sum(merged.values())
    if total <= 0:
        merged, total = dict(DEFAULT_WEIGHTS), 1.0
    return {k: v / total for k, v in merged.items()}


def level_of(levels: dict, comp: str) -> int:
    entry = levels.get(comp)
    if not entry:
        return 0
    return int(entry.get("level") or 0)


def basis_of(levels: dict, comp: str) -> str:
    entry = levels.get(comp)
    return (entry or {}).get("basis") or "none"


def learner_band(level: float) -> int:
    lo, hi = BAND_THRESHOLDS
    if level < lo:
        return 0
    if level < hi:
        return 1
    return 2


def comp_name(competencies: dict, comp: str) -> str:
    return (competencies.get(comp) or {}).get("name", comp)


# ---------------------------------------------------------------------------
# 1. Gap calculation
# ---------------------------------------------------------------------------

def compute_gaps(goal: dict, levels: dict, competencies: dict) -> list[dict]:
    """Per-requirement gap rows for a goal, largest weighted gap first."""
    rows = []
    for req in goal.get("requirements", []):
        comp = req["competency"]
        target = int(req["target"])
        current = level_of(levels, comp)
        gap = max(0, target - current)
        rows.append({
            "competency": comp,
            "name": comp_name(competencies, comp),
            "current": current,
            "target": target,
            "gap": gap,
            "weight": int(req.get("weight", 1)),
            "basis": basis_of(levels, comp),
            "met": gap == 0,
            # Missing evidence is explicit: "none" means we have no data at all,
            # which is treated as level 0 but flagged in the UI.
            "no_evidence": basis_of(levels, comp) == "none",
        })
    rows.sort(key=lambda r: (-r["gap"] * r["weight"], r["competency"]))
    return rows


def goal_readiness(gaps: list[dict]) -> int:
    """Weighted % of the goal's target proficiency already reached (0-100)."""
    num = sum(r["weight"] * min(r["current"], r["target"]) for r in gaps)
    den = sum(r["weight"] * r["target"] for r in gaps)
    return int(round(100 * num / den)) if den else 100


# ---------------------------------------------------------------------------
# 2. Prerequisites
# ---------------------------------------------------------------------------

def prerequisite_status(course: dict, levels: dict, competencies: dict) -> list[dict]:
    out = []
    for pre in course.get("prerequisites", []):
        comp = pre["competency"]
        need = int(pre["min_level"])
        have = level_of(levels, comp)
        out.append({
            "competency": comp,
            "name": comp_name(competencies, comp),
            "min_level": need,
            "current": have,
            "satisfied": have >= need,
            "basis": basis_of(levels, comp),
        })
    return out


def unmet_prerequisites(course: dict, levels: dict) -> list[dict]:
    return [p for p in course.get("prerequisites", [])
            if level_of(levels, p["competency"]) < int(p["min_level"])]


def detect_prerequisite_cycles(courses: list[dict]) -> None:
    """Raise PrerequisiteCycleError if the provider graph of the catalogue has a cycle.

    Edge P -> C exists when C requires competency k at level m and P develops
    k to at least m. A cycle means no valid learning order exists.
    """
    by_id = {c["id"]: c for c in courses}
    edges: dict[str, list[str]] = {c["id"]: [] for c in courses}
    for course in courses:
        for pre in course.get("prerequisites", []):
            for provider in courses:
                if provider["id"] == course["id"]:
                    continue
                if int(provider.get("develops", {}).get(pre["competency"], 0)) >= int(pre["min_level"]):
                    # Only a cycle if *every* provider path loops; we flag any
                    # provider whose own prerequisites lead back (strict check).
                    edges[provider["id"]].append(course["id"])

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {cid: WHITE for cid in by_id}
    stack: list[str] = []

    def visit(node: str) -> None:
        colour[node] = GREY
        stack.append(node)
        for nxt in sorted(set(edges[node])):
            if colour[nxt] == GREY:
                start = stack.index(nxt)
                raise PrerequisiteCycleError(stack[start:] + [nxt])
            if colour[nxt] == WHITE:
                visit(nxt)
        stack.pop()
        colour[node] = BLACK

    for cid in sorted(by_id):
        if colour[cid] == WHITE:
            visit(cid)


# ---------------------------------------------------------------------------
# 3. Scoring
# ---------------------------------------------------------------------------

def score_course(course: dict, gaps: list[dict], levels: dict,
                 weights: dict[str, float] | None = None) -> dict:
    """Transparent 0-1 score with its four components."""
    w = normalize_weights(weights)
    develops = course.get("develops", {})
    gap_rows = {g["competency"]: g for g in gaps}

    total_gap = sum(g["weight"] * g["gap"] for g in gaps)
    closable = 0.0
    for comp, reach in develops.items():
        g = gap_rows.get(comp)
        if g and g["gap"] > 0:
            closable += g["weight"] * max(0, min(int(reach), g["target"]) - g["current"])
    gap_coverage = closable / total_gap if total_gap else 0.0

    # Relevance: how focused the course is on what this goal needs
    # (weighted share of its competencies that the goal requires).
    if develops:
        relevance = sum(
            (gap_rows[c]["weight"] / 3.0) if c in gap_rows else 0.0 for c in develops
        ) / len(develops)
    else:
        relevance = 0.0

    prereqs = course.get("prerequisites", [])
    if prereqs:
        readiness = sum(
            min(1.0, level_of(levels, p["competency"]) / max(1, int(p["min_level"])))
            for p in prereqs
        ) / len(prereqs)
    else:
        readiness = 1.0

    mean_level = (
        sum(level_of(levels, c) for c in develops) / len(develops) if develops else 0
    )
    difficulty = DIFFICULTY_RANK.get(course.get("difficulty", "beginner"), 0)
    fit = 1.0 - abs(difficulty - learner_band(mean_level)) / 2.0

    components = {
        "gap_coverage": round(gap_coverage, 4),
        "goal_relevance": round(relevance, 4),
        "prereq_readiness": round(readiness, 4),
        "level_fit": round(fit, 4),
    }
    total = sum(w[k] * components[k] for k in components)
    return {"total": round(total, 4), "components": components, "weights": w}


# ---------------------------------------------------------------------------
# 4. Plan selection (which courses) + prerequisite closure
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    selected: list[str] = field(default_factory=list)            # gap-closing courses
    prereq_added: dict[str, list[str]] = field(default_factory=dict)  # course -> [dependents]
    dependencies: list[tuple[str, str, str]] = field(default_factory=list)  # (provider, dependent, comp)
    unresolved: dict[str, list[dict]] = field(default_factory=dict)  # course -> unmet prereqs w/o provider
    uncovered: list[str] = field(default_factory=list)            # gap comps no course can close
    skipped: list[dict] = field(default_factory=list)


def _available(course: dict) -> bool:
    return course.get("availability", "available") == "available"


def _provider_key(course: dict, comp: str):
    # Prefer available, then easiest, then highest reach, then id (stable).
    return (
        0 if _available(course) else 1,
        DIFFICULTY_RANK.get(course.get("difficulty", "beginner"), 0),
        -int(course.get("develops", {}).get(comp, 0)),
        course["id"],
    )


def select_plan(goal: dict, courses: list[dict], levels: dict, completed: set[str],
                competencies: dict, weights: dict | None = None,
                include_revision: bool = False) -> Plan:
    """Greedy weighted set-cover over goal gaps, then prerequisite closure."""
    detect_prerequisite_cycles(courses)
    by_id = {c["id"]: c for c in courses}
    gaps = compute_gaps(goal, levels, competencies)
    targets = {g["competency"]: g["target"] for g in gaps}
    weight_of = {g["competency"]: g["weight"] for g in gaps}
    projected = {g["competency"]: g["current"] for g in gaps}
    plan = Plan()

    eligible = [c for c in courses if include_revision or c["id"] not in completed]

    def marginal(course: dict) -> float:
        gain = 0.0
        for comp, reach in course.get("develops", {}).items():
            if comp in targets:
                gain += weight_of[comp] * max(0, min(int(reach), targets[comp]) - projected[comp])
        return gain

    # Available courses first; unavailable ones only for gaps nothing else closes.
    for pool_available in (True, False):
        while True:
            pool = [c for c in eligible
                    if c["id"] not in plan.selected and _available(c) == pool_available]
            best, best_key = None, None
            for course in pool:
                gain = marginal(course)
                if gain <= 0:
                    continue
                score = score_course(course, gaps, levels, weights)["total"]
                key = (-gain, -score,
                       DIFFICULTY_RANK.get(course.get("difficulty"), 0), course["id"])
                if best_key is None or key < best_key:
                    best, best_key = course, key
            if best is None:
                break
            plan.selected.append(best["id"])
            for comp, reach in best.get("develops", {}).items():
                if comp in projected:
                    projected[comp] = max(projected[comp], min(int(reach), targets[comp]))

    plan.uncovered = [c for c in targets if projected[c] < targets[c]]

    # Prerequisite closure: for each unmet prerequisite, route through a provider.
    in_plan = list(plan.selected)
    queue = list(plan.selected)
    visiting: list[str] = []

    def resolve(cid: str, trail: list[str]) -> None:
        if cid in trail:
            raise PrerequisiteCycleError(trail[trail.index(cid):] + [cid])
        course = by_id[cid]
        for pre in unmet_prerequisites(course, levels):
            comp, need = pre["competency"], int(pre["min_level"])
            providers = [
                p for p in courses
                if p["id"] != cid and int(p.get("develops", {}).get(comp, 0)) >= need
                and p["id"] not in completed
            ]
            if not providers:
                plan.unresolved.setdefault(cid, []).append(pre)
                continue
            already = [p for p in providers if p["id"] in in_plan]
            provider = min(already or providers, key=lambda p: _provider_key(p, comp))
            plan.dependencies.append((provider["id"], cid, comp))
            if provider["id"] not in in_plan:
                in_plan.append(provider["id"])
                plan.prereq_added.setdefault(provider["id"], []).append(cid)
                resolve(provider["id"], trail + [cid])
            elif provider["id"] in plan.prereq_added and cid not in plan.prereq_added[provider["id"]]:
                plan.prereq_added[provider["id"]].append(cid)

    for cid in queue:
        resolve(cid, visiting)

    # Explain relevant catalogue courses that were *not* included.
    plan_ids = set(in_plan)
    explained: set[str] = set()
    # (a) Foundation courses skipped because the learner already meets the
    #     prerequisite they would provide (e.g. strong Python -> no Python 101).
    for cid in in_plan:
        for pre in by_id[cid].get("prerequisites", []):
            comp, need = pre["competency"], int(pre["min_level"])
            have = level_of(levels, comp)
            if have < need:
                continue
            for provider in courses:
                pid = provider["id"]
                if pid in plan_ids or pid in explained or pid == cid:
                    continue
                if int(provider.get("develops", {}).get(comp, 0)) < need:
                    continue
                if any(c in targets for c in provider.get("develops", {})):
                    continue  # handled by the goal-gap explanation below
                basis = " (assessment-validated)" if basis_of(levels, comp) == "assessment" else " (self-reported)"
                plan.skipped.append({
                    "course_id": pid, "title": provider["title"], "kind": "prereq_met",
                    "reason": (f"Not needed: {by_id[cid]['title']} requires "
                               f"{comp_name(competencies, comp)} ≥ {need} and you are at "
                               f"{have}{basis}."),
                })
                explained.add(pid)
    for course in courses:
        if course["id"] in explained:
            continue
        if course["id"] in plan_ids:
            continue
        touches = [c for c in course.get("develops", {}) if c in targets]
        if not touches:
            continue
        if course["id"] in completed and not include_revision:
            reason = "Already completed - excluded (request revision to include it)."
            kind = "completed"
        elif all(projected[c] >= targets[c] and level_of(levels, c) >= targets[c] for c in touches):
            names = ", ".join(
                f"{comp_name(competencies, c)} ({level_of(levels, c)}"
                f"{', validated' if basis_of(levels, c) == 'assessment' else ''})"
                for c in touches
            )
            reason = f"You already meet the goal level for {names}."
            kind = "already_met"
        else:
            reason = "Another selected course already closes the same gap."
            kind = "redundant"
        plan.skipped.append({"course_id": course["id"], "title": course["title"],
                             "kind": kind, "reason": reason})
    plan.selected = in_plan
    return plan


# ---------------------------------------------------------------------------
# 5. Recommendations with explanations
# ---------------------------------------------------------------------------

def _fmt_levels(changes: list[tuple[str, int, int, int]]) -> str:
    parts = [f"{name} {cur} → {min(reach, tgt)} (goal {tgt})"
             for name, cur, reach, tgt in changes]
    return "; ".join(parts)


def build_recommendations(goal: dict, courses: list[dict], levels: dict,
                          progress: dict, competencies: dict,
                          weights: dict | None = None,
                          include_revision: bool = False,
                          plan: Plan | None = None) -> dict:
    completed = {cid for cid, p in progress.items() if p.get("status") == "completed"}
    plan = plan or select_plan(goal, courses, levels, completed, competencies, weights,
                               include_revision)
    by_id = {c["id"]: c for c in courses}
    gaps = compute_gaps(goal, levels, competencies)
    gap_rows = {g["competency"]: g for g in gaps}

    recs = []
    for cid in plan.selected:
        course = by_id[cid]
        if cid in completed and not include_revision:
            continue
        score = score_course(course, gaps, levels, weights)
        prereqs = prerequisite_status(course, levels, competencies)
        unmet = [p for p in prereqs if not p["satisfied"]]
        if not _available(course):
            status = "unavailable"
        elif unmet:
            status = "locked"
        else:
            status = "ready"

        develops = []
        changes = []
        for comp, reach in course.get("develops", {}).items():
            g = gap_rows.get(comp)
            develops.append({
                "competency": comp,
                "name": comp_name(competencies, comp),
                "course_reaches": int(reach),
                "current": level_of(levels, comp),
                "target": g["target"] if g else None,
                "basis": basis_of(levels, comp),
                "in_goal": g is not None,
            })
            if g and g["gap"] > 0:
                changes.append((g["name"], g["current"], int(reach), g["target"]))

        reasons = []
        if changes:
            reasons.append(
                f"Closes {round(score['components']['gap_coverage'] * 100)}% of your weighted "
                f"gap for {goal['title']}: {_fmt_levels(changes)}."
            )
        if cid in plan.prereq_added:
            deps = ", ".join(by_id[d]["title"] for d in plan.prereq_added[cid])
            needed: dict[str, int] = {}
            for (p, d, comp) in plan.dependencies:
                if p != cid:
                    continue
                for pre in by_id[d].get("prerequisites", []):
                    if pre["competency"] == comp:
                        needed[comp] = max(needed.get(comp, 0), int(pre["min_level"]))
            need_txt = ", ".join(
                f"{comp_name(competencies, c)} ≥ {m} (you: {level_of(levels, c)})"
                for c, m in sorted(needed.items())
            )
            reasons.append(f"Foundation step: {deps} requires {need_txt}.")
        if status == "locked":
            reasons.append("Locked until: " + "; ".join(
                f"{p['name']} ≥ {p['min_level']} (you: {p['current']})" for p in unmet
            ) + ".")
        elif status == "unavailable":
            reasons.append("No available content: this is an unverified external listing, "
                           "so it cannot be started here.")
        elif prereqs:
            reasons.append("All prerequisites met.")
        else:
            reasons.append("No prerequisites - you can start immediately.")

        missing = [d["name"] for d in develops if d["in_goal"] and d["basis"] == "none"]
        if missing:
            reasons.append("No evidence yet for " + ", ".join(missing)
                           + " - treated as 0 until you self-report or pass an assessment.")

        recs.append({
            "course_id": cid,
            "title": course["title"],
            "summary": course.get("summary", ""),
            "outcomes": course.get("outcomes", []),
            "difficulty": course.get("difficulty"),
            "duration_minutes": course.get("duration_minutes") if course.get("duration_verified") else None,
            "availability": course.get("availability", "available"),
            "source": course.get("source", "local"),
            "status": status,
            "role": "prerequisite" if (cid in plan.prereq_added and not changes) else "gap",
            "score": score,
            "develops": develops,
            "prerequisites": prereqs,
            "reasons": reasons,
            "progress": progress.get(cid, {"status": "not_started", "percent": 0}),
            "resources": course.get("resources", []),
        })

    order = {"ready": 0, "locked": 1, "unavailable": 2}
    recs.sort(key=lambda r: (order[r["status"]], -r["score"]["total"], r["course_id"]))
    for rank, rec in enumerate(recs, 1):
        rec["rank"] = rank
    return {
        "goal": {"id": goal["id"], "title": goal["title"]},
        "gaps": gaps,
        "readiness": goal_readiness(gaps),
        "recommendations": recs,
        "skipped": plan.skipped,
        "uncovered": [
            {"competency": c, "name": comp_name(competencies, c)} for c in plan.uncovered
        ],
        "weights": normalize_weights(weights),
    }


# ---------------------------------------------------------------------------
# 6. Roadmap graph
# ---------------------------------------------------------------------------

def _course_state(course: dict, levels: dict, progress: dict) -> str:
    p = progress.get(course["id"]) or {}
    if p.get("status") == "completed":
        return "completed"
    if not _available(course):
        return "unavailable"
    if unmet_prerequisites(course, levels):
        return "locked"
    if p.get("status") == "in_progress":
        return "in_progress"
    return "available"


def build_roadmap(goal: dict, courses: list[dict], levels: dict, progress: dict,
                  competencies: dict, weights: dict | None = None,
                  preserved_courses: list[str] | None = None,
                  preserved_edges: list[tuple[str, str]] | None = None,
                  learner_name: str = "You") -> dict:
    """Generate the roadmap graph (nodes, edges, positions) from data.

    ``preserved_courses``/``preserved_edges`` come from the previous version of
    this roadmap: completed courses (and the edges that led out of them) are
    kept so learning history never disappears on recalculation.
    """
    completed = {cid for cid, p in progress.items() if p.get("status") == "completed"}
    by_id = {c["id"]: c for c in courses}
    plan = select_plan(goal, courses, levels, completed, competencies, weights)
    rec = build_recommendations(goal, courses, levels, progress, competencies, weights,
                                plan=plan)
    gaps = rec["gaps"]
    gap_rows = {g["competency"]: g for g in gaps}

    course_ids: list[str] = list(plan.selected)
    for cid in preserved_courses or []:
        if cid in by_id and cid in completed and cid not in course_ids:
            course_ids.append(cid)

    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = {}

    def add_edge(src: str, dst: str, kind: str = "flow", label: str = "") -> None:
        if src == dst or (src, dst) in edges:
            return
        edges[(src, dst)] = {"id": f"{src}->{dst}", "source": src, "target": dst,
                             "kind": kind, "label": label}

    met_at_start = [
        {"competency": g["competency"], "name": g["name"], "level": g["current"], "basis": g["basis"]}
        for g in gaps if g["met"] and not any(
            g["competency"] in by_id[c].get("develops", {}) for c in course_ids)
    ]
    nodes["start"] = {
        "id": "start", "type": "start", "state": "completed",
        "title": learner_name,
        "subtitle": "Current competency state",
        "data": {
            "readiness": rec["readiness"],
            "met": met_at_start,
            "levels": [
                {"competency": g["competency"], "name": g["name"], "current": g["current"],
                 "target": g["target"], "basis": g["basis"]} for g in gaps
            ],
        },
    }

    recs_by_id = {r["course_id"]: r for r in rec["recommendations"]}
    ready_ranked = [r for r in rec["recommendations"] if r["status"] == "ready"]
    next_ids = {r["course_id"] for r in ready_ranked[:1]}

    chain_end: dict[str, str] = {}
    for cid in course_ids:
        course = by_id[cid]
        state = _course_state(course, levels, progress)
        info = recs_by_id.get(cid)
        pstat = progress.get(cid) or {}
        nodes[f"course:{cid}"] = {
            "id": f"course:{cid}", "type": "course", "state": state,
            "course_id": cid,
            "title": course["title"],
            "subtitle": course.get("difficulty", "").title(),
            "recommended": cid in next_ids,
            "data": {
                "summary": course.get("summary", ""),
                "outcomes": course.get("outcomes", []),
                "duration_minutes": course.get("duration_minutes") if course.get("duration_verified") else None,
                "source": course.get("source", "local"),
                "availability": course.get("availability", "available"),
                "develops": [
                    {"competency": c, "name": comp_name(competencies, c), "reaches": int(v),
                     "current": level_of(levels, c),
                     "target": gap_rows[c]["target"] if c in gap_rows else None}
                    for c, v in course.get("develops", {}).items()
                ],
                "prerequisites": prerequisite_status(course, levels, competencies),
                "reasons": info["reasons"] if info else ["Completed earlier - kept as learning history."],
                "score": info["score"] if info else None,
                "rank": info["rank"] if info else None,
                "resources": course.get("resources", []),
                "progress": {"status": pstat.get("status", "not_started"),
                             "percent": int(pstat.get("percent") or 0)},
            },
        }
        end = f"course:{cid}"
        if course.get("has_quiz") and _available(course):
            qstate = ("completed" if pstat.get("quiz_passed") or state == "completed"
                      else "locked" if state == "locked"
                      else "in_progress" if pstat.get("quiz_attempts")
                      else "available")
            nodes[f"quiz:{cid}"] = {
                "id": f"quiz:{cid}", "type": "assessment", "state": qstate,
                "course_id": cid, "title": "Assessment",
                "subtitle": course["title"],
                "data": {"best_score": pstat.get("best_score"),
                         "attempts": pstat.get("quiz_attempts", 0)},
            }
            add_edge(end, f"quiz:{cid}")
            end = f"quiz:{cid}"
        if course.get("has_lab") and _available(course):
            lstate = ("completed" if pstat.get("lab_passed")
                      else "locked" if not (pstat.get("quiz_passed")) else "available")
            nodes[f"lab:{cid}"] = {
                "id": f"lab:{cid}", "type": "lab", "state": lstate,
                "course_id": cid, "title": "Practical lab",
                "subtitle": course.get("lab_title", ""),
                "data": {},
            }
            add_edge(end, f"lab:{cid}")
            end = f"lab:{cid}"
        chain_end[cid] = end

    # Dependency edges (current unmet prerequisites + preserved history).
    has_incoming: set[str] = set()
    for provider, dependent, comp in plan.dependencies:
        if provider in chain_end and dependent in chain_end:
            add_edge(chain_end[provider], f"course:{dependent}", "prerequisite",
                     comp_name(competencies, comp))
            has_incoming.add(dependent)
    for provider, dependent in preserved_edges or []:
        if provider in chain_end and dependent in chain_end and provider in completed:
            add_edge(chain_end[provider], f"course:{dependent}", "prerequisite")
            has_incoming.add(dependent)
    for cid in course_ids:
        if cid not in has_incoming:
            add_edge("start", f"course:{cid}")

    # Milestones: one per goal competency that the roadmap works on.
    goal_state = "completed" if all(g["met"] for g in gaps) else "locked"
    for g in gaps:
        comp = g["competency"]
        contributors = [cid for cid in course_ids if comp in by_id[cid].get("develops", {})]
        if not contributors and g["met"]:
            continue  # already met at start; shown on the start node
        mid = f"milestone:{comp}"
        if g["met"]:
            mstate = "completed"
        elif contributors and all(not _available(by_id[c]) for c in contributors):
            mstate = "unavailable"
        elif not contributors:
            mstate = "unavailable"
        else:
            mstate = "locked"
        nodes[mid] = {
            "id": mid, "type": "milestone", "state": mstate,
            "title": g["name"],
            "subtitle": f"Reach {g['target']}",
            "data": {"current": g["current"], "target": g["target"], "basis": g["basis"],
                     "no_course": not contributors},
        }
        if contributors:
            for cid in contributors:
                add_edge(chain_end[cid], mid, "milestone")
        else:
            add_edge("start", mid, "gap", "no course available")
        add_edge(mid, "goal", "goal")

    nodes["goal"] = {
        "id": "goal", "type": "goal", "state": goal_state,
        "title": goal["title"], "subtitle": "Goal destination",
        "data": {"readiness": rec["readiness"], "tagline": goal.get("tagline", "")},
    }
    if not any(e["target"] == "goal" for e in edges.values()):
        add_edge("start", "goal", "goal")

    node_list = list(nodes.values())
    edge_list = list(edges.values())
    _validate_dag(node_list, edge_list)
    width, height = layout(node_list, edge_list)

    plan_courses = [n for n in node_list if n["type"] == "course"]
    done = sum(1 for n in plan_courses if n["state"] == "completed")
    startable = [n for n in plan_courses if n["state"] in ("available", "in_progress")]
    startable.sort(key=lambda n: (0 if n["state"] == "in_progress" else 1,
                                  (n["data"].get("rank") or 99)))
    next_action = None
    if startable:
        n = startable[0]
        next_action = {
            "course_id": n["course_id"], "title": n["title"],
            "verb": "Continue" if n["state"] == "in_progress" else "Start",
        }
    return {
        "goal": {"id": goal["id"], "title": goal["title"], "tagline": goal.get("tagline", "")},
        "nodes": node_list,
        "edges": edge_list,
        "size": {"width": width, "height": height},
        "summary": {
            "courses_total": len(plan_courses),
            "courses_completed": done,
            "progress": int(round(100 * done / len(plan_courses))) if plan_courses else 100,
            "readiness": rec["readiness"],
            "next_action": next_action,
        },
        "analysis": rec,
        "course_ids": course_ids,
        "dependency_edges": sorted({(p, d) for (p, d, _c) in plan.dependencies}),
    }


def _validate_dag(nodes: list[dict], edges: list[dict]) -> None:
    ids = {n["id"] for n in nodes}
    for e in edges:
        if e["source"] not in ids or e["target"] not in ids:
            raise ValueError(f"Edge references unknown node: {e['id']}")
    order = topological_order(nodes, edges)
    if len(order) != len(nodes):
        raise PrerequisiteCycleError(sorted(ids - set(order)))


def topological_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    indeg = {n["id"]: 0 for n in nodes}
    out: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        out[e["source"]].append(e["target"])
        indeg[e["target"]] += 1
    ready = sorted(n for n, d in indeg.items() if d == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for nxt in sorted(out[node]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort()
    return order


# ---------------------------------------------------------------------------
# 7. Layout (server-side so the graph is reproducible and testable)
# ---------------------------------------------------------------------------

def layout(nodes: list[dict], edges: list[dict]) -> tuple[int, int]:
    """Longest-path layering + barycentre ordering + a gentle wave.

    Mutates each node with ``x``/``y`` (centre) and ``layer``; returns the
    canvas (width, height).
    """
    by_id = {n["id"]: n for n in nodes}
    preds: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        preds[e["target"]].append(e["source"])

    layer: dict[str, int] = {}
    for nid in topological_order(nodes, edges):
        layer[nid] = 1 + max((layer[p] for p in preds[nid]), default=-1)
    # Milestones share one column just before the goal, which sits alone last.
    milestones = [n for n in layer if by_id[n]["type"] == "milestone"]
    if milestones:
        m_col = max(layer[n] for n in milestones)
        for n in milestones:
            layer[n] = m_col
    last = max(layer.values()) if layer else 0
    if "goal" in layer:
        others = [layer[n] for n in layer if n != "goal"]
        layer["goal"] = (max(others) + 1) if others else 0
        last = layer["goal"]

    columns: dict[int, list[str]] = {}
    for nid, lyr in layer.items():
        columns.setdefault(lyr, []).append(nid)

    # Initial order: type, then id (stable), then two barycentre sweeps.
    type_rank = {"start": 0, "course": 1, "assessment": 2, "lab": 3, "milestone": 4, "goal": 5}
    for lyr in columns:
        columns[lyr].sort(key=lambda n: (type_rank.get(by_id[n]["type"], 9), n))
    succs: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        succs[e["source"]].append(e["target"])
    position: dict[str, float] = {}
    for lyr in columns:
        for idx, nid in enumerate(columns[lyr]):
            position[nid] = idx

    def crossings() -> int:
        total = 0
        pairs = [(position[e["source"]], position[e["target"]], layer[e["source"]])
                 for e in edges]
        for i, (a1, b1, l1) in enumerate(pairs):
            for a2, b2, l2 in pairs[i + 1:]:
                if l1 == l2 and (a1 - a2) * (b1 - b2) < 0:
                    total += 1
        return total

    # Barycentre heuristic, alternating downward (preds) and upward (succs)
    # sweeps; keep the best ordering seen (deterministic tie-break on id).
    best = ({l: list(c) for l, c in columns.items()}, crossings())
    order = sorted(columns)
    for it in range(6):
        forward = it % 2 == 0
        for lyr in (order[1:] if forward else list(reversed(order[:-1]))):
            col = columns[lyr]
            ref = preds if forward else succs

            def bary(nid: str) -> float:
                ps = [position[p] for p in ref[nid] if p in position]
                return sum(ps) / len(ps) if ps else position.get(nid, 0)
            col.sort(key=lambda n: (bary(n), n))
            for idx, nid in enumerate(col):
                position[nid] = idx
        score = crossings()
        if score < best[1]:
            best = ({l: list(c) for l, c in columns.items()}, score)
    columns = best[0]
    for lyr, col in columns.items():
        for idx, nid in enumerate(col):
            position[nid] = idx

    x_cursor = 0
    min_y, max_y = math.inf, -math.inf
    for lyr in range(0, last + 1):
        col = columns.get(lyr, [])
        if not col:
            continue
        col_width = max(NODE_SIZE[by_id[n]["type"]][0] for n in col)
        heights = [NODE_SIZE[by_id[n]["type"]][1] for n in col]
        total_h = sum(heights) + ROW_GAP * (len(col) - 1)
        wave = WAVE_AMPLITUDE * math.sin(lyr * WAVE_FREQUENCY) if 0 < lyr < last else 0
        y_cursor = -total_h / 2 + wave
        cx = x_cursor + col_width / 2
        for nid, h in zip(col, heights):
            node = by_id[nid]
            node["layer"] = lyr
            node["x"] = round(cx, 1)
            node["y"] = round(y_cursor + h / 2, 1)
            min_y = min(min_y, y_cursor)
            max_y = max(max_y, y_cursor + h)
            y_cursor += h + ROW_GAP
        x_cursor += col_width + LAYER_GAP

    # Shift so the canvas starts at (60, 60).
    pad = 60
    offset_y = pad - (min_y if min_y != math.inf else 0)
    for n in nodes:
        n["x"] = round(n.get("x", 0) + pad, 1)
        n["y"] = round(n.get("y", 0) + offset_y, 1)
    width = int(x_cursor - LAYER_GAP + 2 * pad)
    height = int((max_y - min_y if max_y != -math.inf else 0) + 2 * pad)
    return width, height
