"""
AntahAI Learning Pathways - competency evidence and assessment rules (pure).

Evidence sources and how they count toward a learner's *effective* level:

  assessment      Passing a course assessment or lab. Highest trust
                  (confidence 0.9). When present it defines the level, even if
                  a self-report claims more.
  self_reported   The learner's own rating (confidence 0.5). Used when there is
                  no assessment evidence; shown as "unverified".
  resume_inferred Suggested from resume text (confidence 0.3). NEVER counts
                  toward the level until the learner confirms it, at which
                  point it is stored as self_reported (with the resume noted).

Nothing here increases proficiency because a course was opened or a lesson
was marked as read. Only ``assessment_evidence`` / ``lab_evidence`` create
assessment evidence, and only on a pass.
"""

from __future__ import annotations

import math
from statistics import mean, stdev

CONFIDENCE = {"assessment": 0.9, "self_reported": 0.5, "resume_inferred": 0.3}

#: Per-competency accuracy at which the learner is credited with the full
#: level the course develops. Below it the credit scales down linearly.
MASTERY_ACCURACY = 0.8


def effective_levels(evidence: list[dict]) -> dict[str, dict]:
    """Aggregate evidence rows into one effective level per competency.

    Each evidence row: {competency, source, level, created_at, note, confirmed}.
    Rows are expected oldest-first; the latest self-report wins among self-reports.
    """
    out: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = {}
    for row in evidence:
        comp = row.get("competency") or row.get("competency_id")
        grouped.setdefault(comp, []).append(row)

    for comp, rows in grouped.items():
        assessed = [r for r in rows if r["source"] == "assessment"]
        selfrep = [r for r in rows if r["source"] == "self_reported"]
        inferred = [r for r in rows if r["source"] == "resume_inferred" and not r.get("confirmed")]
        entry = {
            "level": 0, "basis": "none", "confidence": 0.0,
            "self_reported": selfrep[-1]["level"] if selfrep else None,
            "assessed": max(r["level"] for r in assessed) if assessed else None,
            "suggested": max(r["level"] for r in inferred) if inferred else None,
            "explanation": "",
        }
        if assessed:
            best = max(assessed, key=lambda r: r["level"])
            entry.update(level=int(best["level"]), basis="assessment",
                         confidence=CONFIDENCE["assessment"],
                         explanation=best.get("note") or "Validated by assessment.")
            if entry["self_reported"] is not None and entry["self_reported"] > entry["level"]:
                entry["explanation"] += (f" Self-rating ({entry['self_reported']}) is higher than the "
                                         "validated level; the validated level is used.")
        elif selfrep:
            entry.update(level=int(selfrep[-1]["level"]), basis="self_reported",
                         confidence=CONFIDENCE["self_reported"],
                         explanation="Self-reported, not yet validated by an assessment.")
        else:
            entry["explanation"] = ("Only a resume suggestion exists - confirm it to use it."
                                    if inferred else "No evidence.")
        out[comp] = entry
    return out


# ---------------------------------------------------------------------------
# Quiz grading
# ---------------------------------------------------------------------------

def grade_quiz(questions: list[dict], answers: dict[str, int | None],
               pass_threshold: float) -> dict:
    """Deterministic grading. ``answers`` maps question id -> chosen option index."""
    per_comp: dict[str, list[int]] = {}
    details = []
    correct_total = 0
    for q in questions:
        chosen = answers.get(q["id"])
        ok = chosen is not None and int(chosen) == int(q["answer"])
        correct_total += 1 if ok else 0
        per_comp.setdefault(q["competency"], [0, 0])
        per_comp[q["competency"]][1] += 1
        if ok:
            per_comp[q["competency"]][0] += 1
        details.append({
            "id": q["id"], "text": q["text"], "options": q["options"],
            "chosen": chosen, "answer": q["answer"], "correct": ok,
            "competency": q["competency"], "lesson": q.get("lesson"),
            "explanation": q.get("explanation", ""),
        })
    total = len(questions)
    score = correct_total / total if total else 0.0
    return {
        "correct": correct_total,
        "total": total,
        "score": round(score, 4),
        "percent": int(round(score * 100)),
        "passed": total > 0 and score + 1e-9 >= pass_threshold,
        "pass_threshold": pass_threshold,
        "per_competency": {
            c: {"correct": v[0], "total": v[1], "accuracy": round(v[0] / v[1], 4)}
            for c, v in per_comp.items()
        },
        "details": details,
    }


def remediation_plan(result: dict, lessons: list[dict], competencies: dict) -> list[dict]:
    """Targeted revision: lessons behind the wrongly answered questions."""
    lesson_by_id = {l["id"]: l for l in lessons}
    grouped: dict[str, dict] = {}
    for d in result["details"]:
        if d["correct"]:
            continue
        lid = d.get("lesson")
        if lid not in lesson_by_id:
            continue
        entry = grouped.setdefault(lid, {
            "lesson_id": lid, "lesson_title": lesson_by_id[lid]["title"],
            "competency": d["competency"],
            "competency_name": (competencies.get(d["competency"]) or {}).get("name", d["competency"]),
            "missed": [],
        })
        entry["missed"].append({"question": d["text"], "explanation": d["explanation"]})
    order = [l["id"] for l in lessons]
    return sorted(grouped.values(), key=lambda e: order.index(e["lesson_id"]))


def assessment_evidence(course: dict, result: dict) -> list[dict]:
    """Evidence created by a *passed* quiz: level scales with per-competency accuracy."""
    if not result.get("passed"):
        return []
    out = []
    for comp, reach in course.get("develops", {}).items():
        stats = result["per_competency"].get(comp)
        if not stats:
            continue  # not assessed by this quiz (e.g. taught through the lab)
        factor = min(1.0, stats["accuracy"] / MASTERY_ACCURACY)
        level = int(round(int(reach) * factor))
        out.append({
            "competency": comp,
            "level": level,
            "note": (f"Passed '{course['title']}' assessment: {stats['correct']}/{stats['total']} "
                     f"correct on this competency -> {level} "
                     f"(course develops up to {reach}; full credit at "
                     f"{int(MASTERY_ACCURACY * 100)}% accuracy)."),
        })
    return out


# ---------------------------------------------------------------------------
# Lab checking
# ---------------------------------------------------------------------------

def lab_expected(lab: dict) -> dict[str, float]:
    """Compute the reference answers from the lab's dataset (never hard-coded)."""
    cols = lab["dataset"]["columns"]
    rows = [dict(zip(cols, r)) for r in lab["dataset"]["rows"]]
    w = [r["weight"] for r in rows]
    x = [r["consumption"] for r in rows]
    weighted_mean = sum(wi * xi for wi, xi in zip(w, x)) / sum(w)
    a = [r["consumption"] for r in rows if r["region"] == "A"]
    b = [r["consumption"] for r in rows if r["region"] == "B"]
    se_a = stdev(a) / math.sqrt(len(a))
    se_diff = math.sqrt(stdev(a) ** 2 / len(a) + stdev(b) ** 2 / len(b))
    welch_t = (mean(a) - mean(b)) / se_diff
    return {
        "weighted_mean": round(weighted_mean, 4),
        "se_region_a": round(se_a, 4),
        "welch_t": round(welch_t, 4),
    }


def check_lab(lab: dict, submitted: dict[str, str], interpretation: str) -> dict:
    expected = lab_expected(lab)
    results = []
    all_ok = True
    for task in lab["tasks"]:
        raw = (submitted.get(task["id"]) or "").strip().replace(",", "")
        try:
            value = float(raw)
            ok = abs(value - expected[task["id"]]) <= float(task["tolerance"])
        except ValueError:
            value, ok = None, False
        all_ok = all_ok and ok
        results.append({"id": task["id"], "label": task["label"], "submitted": raw,
                        "correct": ok,
                        "expected": expected[task["id"]] if ok else None})
    text_ok = len((interpretation or "").strip()) >= int(lab.get("min_interpretation_chars", 0))
    return {
        "tasks": results,
        "interpretation_ok": text_ok,
        "passed": all_ok and text_ok,
    }


def lab_evidence(course: dict, lab: dict, passed: bool) -> list[dict]:
    if not passed:
        return []
    return [{
        "competency": comp, "level": int(level),
        "note": f"Completed practical lab '{lab['title']}' with all numeric answers correct.",
    } for comp, level in lab.get("develops", {}).items()]
