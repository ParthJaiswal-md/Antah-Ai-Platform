"""Unit tests for the deterministic pathway engine and evidence rules.

Run from the System-3 folder:  python -m pytest tests   (or: python -m unittest discover tests)
"""

import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pathways import catalogue as cat  # noqa: E402
from pathways import engine as E  # noqa: E402
from pathways import rules as R  # noqa: E402

RAW = cat.load_raw()
COMPS = {c["id"]: c for c in RAW["competencies"]}
GOALS = {g["id"]: g for g in RAW["goals"]}
COURSES = [cat.engine_course(c) for con in cat.connectors(RAW) for c in con.listings()]
DEMO = {d["username"]: d for d in RAW["demo_learners"]}


def lv(**levels):
    return {k: {"level": v, "basis": "self_reported"} for k, v in levels.items()}


def demo_levels(name):
    return R.effective_levels([dict(e) for e in DEMO[name]["evidence"]])


class CatalogueTests(unittest.TestCase):
    def test_catalogue_is_valid_and_small(self):
        cat.validate(RAW)
        local = [c for c in COURSES if c["source"] == "local"]
        self.assertTrue(5 <= len(local) <= 8)
        self.assertTrue(3 <= len(RAW["goals"]) <= 5)

    def test_mock_connector_never_claims_availability(self):
        mock = [c for c in COURSES if c["source"] == "igot_mock"]
        self.assertTrue(mock)
        for c in mock:
            self.assertEqual(c["availability"], "unavailable")
            self.assertFalse(c["duration_verified"])

    def test_validation_rejects_bad_metadata(self):
        bad = copy.deepcopy(RAW)
        bad["courses"][0]["develops"]["no_such_skill"] = 50
        with self.assertRaises(cat.CatalogueError):
            cat.validate(bad)


class GapTests(unittest.TestCase):
    def test_gap_calculation(self):
        goal = GOALS["stat_data_analyst"]
        gaps = {g["competency"]: g for g in E.compute_gaps(goal, lv(py_stats=40, sql=70), COMPS)}
        self.assertEqual(gaps["py_stats"]["gap"], 25)
        self.assertEqual(gaps["sql"]["gap"], 0)
        self.assertTrue(gaps["sql"]["met"])
        self.assertEqual(gaps["dataviz"]["current"], 0)
        self.assertTrue(gaps["dataviz"]["no_evidence"])

    def test_readiness_is_weighted(self):
        goal = {"id": "g", "title": "G", "requirements": [
            {"competency": "sql", "target": 50, "weight": 3},
            {"competency": "dataviz", "target": 50, "weight": 1}]}
        gaps = E.compute_gaps(goal, lv(sql=50), COMPS)
        self.assertEqual(E.goal_readiness(gaps), 75)


class ScoreTests(unittest.TestCase):
    def test_weights_normalised(self):
        w = E.normalize_weights({"gap_coverage": 5, "goal_relevance": 5, "prereq_readiness": 0, "level_fit": 0})
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertAlmostEqual(w["gap_coverage"], 0.5)

    def test_score_bounded_and_components(self):
        goal = GOALS["stat_data_analyst"]
        gaps = E.compute_gaps(goal, {}, COMPS)
        for c in COURSES:
            s = E.score_course(c, gaps, {})
            self.assertGreaterEqual(s["total"], 0.0)
            self.assertLessEqual(s["total"], 1.0)
            self.assertEqual(set(s["components"]), set(E.DEFAULT_WEIGHTS))

    def test_course_closing_more_gap_ranks_higher(self):
        goal = GOALS["stat_data_analyst"]
        levels = lv(py_basics=80, desc_stats=60, sql=60, infer_stats=0, py_stats=0, dataviz=45)
        out = E.build_recommendations(goal, COURSES, levels, {}, COMPS)
        ids = [r["course_id"] for r in out["recommendations"]]
        self.assertEqual(ids[0], "PY201")  # closes py_stats + infer_stats gaps

    def test_hard_prerequisite_not_overridden_by_score(self):
        goal = GOALS["stat_data_analyst"]
        out = E.build_recommendations(goal, COURSES, demo_levels("demo_ravi"), {}, COMPS)
        recs = {r["course_id"]: r for r in out["recommendations"]}
        self.assertEqual(recs["PY201"]["status"], "locked")
        ready_ranks = [r["rank"] for r in out["recommendations"] if r["status"] == "ready"]
        self.assertLess(max(ready_ranks), recs["PY201"]["rank"])
        # ...even though PY201 has the highest raw score.
        self.assertEqual(max(out["recommendations"], key=lambda r: r["score"]["total"])["course_id"], "PY201")

    def test_every_recommendation_is_explained(self):
        for name in DEMO:
            for goal in GOALS.values():
                out = E.build_recommendations(goal, COURSES, demo_levels(name), {}, COMPS)
                for r in out["recommendations"]:
                    self.assertTrue(r["reasons"], r["course_id"])


class PlanTests(unittest.TestCase):
    def test_strong_python_learner_skips_basic_python(self):
        goal = GOALS["stat_data_analyst"]
        rm = E.build_roadmap(goal, COURSES, demo_levels("demo_asha"), {}, COMPS)
        self.assertNotIn("PY101", rm["course_ids"])
        skipped = {s["course_id"]: s for s in rm["analysis"]["skipped"]}
        self.assertIn("PY101", skipped)
        self.assertEqual(skipped["PY101"]["kind"], "prereq_met")
        self.assertEqual(E.build_recommendations(goal, COURSES, demo_levels("demo_asha"), {}, COMPS)
                         ["recommendations"][0]["course_id"], "PY201")

    def test_beginner_routed_through_foundations(self):
        goal = GOALS["stat_data_analyst"]
        rm = E.build_roadmap(goal, COURSES, demo_levels("demo_ravi"), {}, COMPS)
        self.assertIn("PY101", rm["course_ids"])
        self.assertIn(("PY101", "PY201"), rm["dependency_edges"])
        self.assertIn(("STAT101", "PY201"), rm["dependency_edges"])
        order = E.topological_order(rm["nodes"], rm["edges"])
        self.assertLess(order.index("course:PY101"), order.index("course:PY201"))
        self.assertLess(order.index("course:STAT101"), order.index("course:PY201"))

    def test_same_goal_different_learners_differ(self):
        goal = GOALS["applied_analysis"]
        a = E.build_roadmap(goal, COURSES, demo_levels("demo_asha"), {}, COMPS)
        r = E.build_roadmap(goal, COURSES, demo_levels("demo_ravi"), {}, COMPS)
        self.assertNotEqual(set(a["course_ids"]), set(r["course_ids"]))
        self.assertNotEqual(a["dependency_edges"], r["dependency_edges"])

    def test_completed_courses_excluded_from_recommendations(self):
        goal = GOALS["stat_data_analyst"]
        prog = {"STAT101": {"status": "completed"}}
        out = E.build_recommendations(goal, COURSES, demo_levels("demo_ravi"), prog, COMPS)
        self.assertNotIn("STAT101", [r["course_id"] for r in out["recommendations"]])
        rev = E.build_recommendations(goal, COURSES, demo_levels("demo_ravi"), prog, COMPS,
                                      include_revision=True)
        self.assertIn("STAT101", [r["course_id"] for r in rev["recommendations"]])

    def test_unavailable_course_used_only_when_nothing_else_covers(self):
        goal = GOALS["dataviz_specialist"]
        rm = E.build_roadmap(goal, COURSES, {}, {}, COMPS)
        node = next(n for n in rm["nodes"] if n.get("course_id") == "IGOT-MOCK-DISSEM")
        self.assertEqual(node["state"], "unavailable")
        self.assertNotIn("quiz:IGOT-MOCK-DISSEM", {n["id"] for n in rm["nodes"]})
        ms = next(n for n in rm["nodes"] if n["id"] == "milestone:dissem")
        self.assertEqual(ms["state"], "unavailable")
        # Never picked for gaps an available course closes.
        rm2 = E.build_roadmap(GOALS["stat_data_analyst"], COURSES, {}, {}, COMPS)
        self.assertNotIn("IGOT-MOCK-DISSEM", rm2["course_ids"])


class CycleTests(unittest.TestCase):
    def test_cycle_detected_with_clear_error(self):
        a = {"id": "A", "title": "A", "difficulty": "beginner", "availability": "available",
             "develops": {"sql": 60}, "prerequisites": [{"competency": "dataviz", "min_level": 50}]}
        b = {"id": "B", "title": "B", "difficulty": "beginner", "availability": "available",
             "develops": {"dataviz": 60}, "prerequisites": [{"competency": "sql", "min_level": 50}]}
        goal = {"id": "g", "title": "G", "requirements": [{"competency": "sql", "target": 60, "weight": 1}]}
        with self.assertRaises(E.PrerequisiteCycleError) as ctx:
            E.build_roadmap(goal, [a, b], {}, {}, COMPS)
        self.assertIn("A", str(ctx.exception))
        self.assertIn("B", str(ctx.exception))


class RoadmapGraphTests(unittest.TestCase):
    def _all(self):
        for name in DEMO:
            for goal in GOALS.values():
                yield name, goal, E.build_roadmap(goal, COURSES, demo_levels(name), {}, COMPS)

    def test_no_duplicate_nodes_or_edges(self):
        for _n, _g, rm in self._all():
            ids = [n["id"] for n in rm["nodes"]]
            self.assertEqual(len(ids), len(set(ids)))
            eids = [e["id"] for e in rm["edges"]]
            self.assertEqual(len(eids), len(set(eids)))
            course_nodes = [n["course_id"] for n in rm["nodes"] if n["type"] == "course"]
            self.assertEqual(len(course_nodes), len(set(course_nodes)))

    def test_structure_start_goal_and_dag(self):
        for _n, _g, rm in self._all():
            types = [n["type"] for n in rm["nodes"]]
            self.assertEqual(types.count("start"), 1)
            self.assertEqual(types.count("goal"), 1)
            order = E.topological_order(rm["nodes"], rm["edges"])
            self.assertEqual(len(order), len(rm["nodes"]))
            self.assertEqual(order[0], "start")

    def test_layout_no_overlap(self):
        for _n, _g, rm in self._all():
            by_layer = {}
            for n in rm["nodes"]:
                by_layer.setdefault(n["layer"], []).append(n)
            for nodes in by_layer.values():
                nodes.sort(key=lambda n: n["y"])
                for a, b in zip(nodes, nodes[1:]):
                    ha = E.NODE_SIZE[a["type"]][1] / 2
                    hb = E.NODE_SIZE[b["type"]][1] / 2
                    self.assertGreaterEqual(b["y"] - a["y"], ha + hb)
            for n in rm["nodes"]:
                self.assertGreaterEqual(n["x"], 0)
                self.assertGreaterEqual(n["y"], 0)
                self.assertLessEqual(n["x"], rm["size"]["width"])
                self.assertLessEqual(n["y"], rm["size"]["height"])

    def test_edges_flow_left_to_right(self):
        for _n, _g, rm in self._all():
            layer = {n["id"]: n["layer"] for n in rm["nodes"]}
            for e in rm["edges"]:
                self.assertLess(layer[e["source"]], layer[e["target"]])

    def test_states(self):
        goal = GOALS["stat_data_analyst"]
        rm = E.build_roadmap(goal, COURSES, demo_levels("demo_ravi"), {}, COMPS)
        state = {n["id"]: n for n in rm["nodes"]}
        self.assertEqual(state["course:PY201"]["state"], "locked")
        self.assertEqual(state["course:PY101"]["state"], "available")
        self.assertEqual(sum(1 for n in rm["nodes"] if n.get("recommended")), 1)
        self.assertEqual(rm["summary"]["next_action"]["verb"], "Start")

    def test_completed_history_preserved_on_recalculation(self):
        goal = GOALS["stat_data_analyst"]
        levels = demo_levels("demo_ravi")
        first = E.build_roadmap(goal, COURSES, levels, {}, COMPS)
        # Ravi completes PY101 and is validated at 65 in Python basics.
        levels = dict(levels, py_basics={"level": 65, "basis": "assessment"})
        prog = {"PY101": {"status": "completed", "quiz_passed": True}}
        second = E.build_roadmap(goal, COURSES, levels, prog, COMPS,
                                 preserved_courses=first["course_ids"],
                                 preserved_edges=first["dependency_edges"])
        node = next(n for n in second["nodes"] if n["id"] == "course:PY101")
        self.assertEqual(node["state"], "completed")
        self.assertIn("quiz:PY101->course:PY201", {e["id"] for e in second["edges"]})
        self.assertNotIn("PY101", [r["course_id"] for r in second["analysis"]["recommendations"]])

    def test_goal_met_marks_goal_completed(self):
        goal = GOALS["survey_sampling"]
        levels = lv(sampling=70, survey_dq=65, desc_stats=60)
        rm = E.build_roadmap(goal, COURSES, levels, {}, COMPS)
        g = next(n for n in rm["nodes"] if n["id"] == "goal")
        self.assertEqual(g["state"], "completed")
        self.assertEqual(rm["summary"]["readiness"], 100)


class RulesTests(unittest.TestCase):
    def test_resume_inferred_does_not_count_until_confirmed(self):
        ev = [{"competency": "sql", "source": "resume_inferred", "level": 45, "confirmed": 0}]
        out = R.effective_levels(ev)
        self.assertEqual(out["sql"]["level"], 0)
        self.assertEqual(out["sql"]["basis"], "none")
        self.assertEqual(out["sql"]["suggested"], 45)

    def test_assessment_overrides_self_report(self):
        ev = [{"competency": "sql", "source": "self_reported", "level": 90},
              {"competency": "sql", "source": "assessment", "level": 60}]
        out = R.effective_levels(ev)
        self.assertEqual(out["sql"]["level"], 60)
        self.assertEqual(out["sql"]["basis"], "assessment")
        self.assertIn("higher than the validated", out["sql"]["explanation"])

    def test_latest_self_report_wins(self):
        ev = [{"competency": "sql", "source": "self_reported", "level": 20},
              {"competency": "sql", "source": "self_reported", "level": 50}]
        self.assertEqual(R.effective_levels(ev)["sql"]["level"], 50)

    def _course(self, cid):
        return next(c for c in RAW["courses"] if c["id"] == cid)

    def test_grading_and_evidence_scaling(self):
        course = self._course("STAT101")
        qs = course["quiz"]["questions"]
        all_right = {q["id"]: q["answer"] for q in qs}
        res = R.grade_quiz(qs, all_right, 0.7)
        self.assertTrue(res["passed"])
        self.assertEqual(res["percent"], 100)
        ev = {e["competency"]: e["level"] for e in R.assessment_evidence(course, res)}
        self.assertEqual(ev, course["develops"])  # full credit

        # One desc_stats question wrong: 2/3 = 0.667 accuracy -> 65 * 0.667/0.8 = 54
        answers = dict(all_right, q1=(qs[0]["answer"] + 1) % 4)
        res = R.grade_quiz(qs, answers, 0.7)
        self.assertTrue(res["passed"])
        ev = {e["competency"]: e["level"] for e in R.assessment_evidence(course, res)}
        self.assertEqual(ev["desc_stats"], round(65 * (2 / 3) / 0.8))

    def test_failed_quiz_gives_no_evidence_and_remediation(self):
        course = self._course("SQL101")
        qs = course["quiz"]["questions"]
        wrong = {q["id"]: (q["answer"] + 1) % len(q["options"]) for q in qs[:3]}
        wrong.update({q["id"]: q["answer"] for q in qs[3:]})
        res = R.grade_quiz(qs, wrong, 0.7)
        self.assertFalse(res["passed"])
        self.assertEqual(R.assessment_evidence(course, res), [])
        plan = R.remediation_plan(res, course["lessons"], COMPS)
        self.assertEqual([p["lesson_id"] for p in plan], ["sql101-1", "sql101-2"])
        self.assertEqual(len(plan[0]["missed"]), 2)

    def test_unanswered_counts_as_wrong(self):
        qs = self._course("PY101")["quiz"]["questions"]
        res = R.grade_quiz(qs, {}, 0.7)
        self.assertEqual(res["correct"], 0)
        self.assertFalse(res["passed"])

    def test_lab_checked_against_dataset(self):
        lab = self._course("LAB301")["lab"]
        exp = R.lab_expected(lab)
        good = {k: str(round(v, 2)) for k, v in exp.items()}
        text = "Region A spends clearly more per capita than Region B; the gap is statistically significant."
        self.assertTrue(R.check_lab(lab, good, text)["passed"])
        bad = dict(good, welch_t="1.0")
        self.assertFalse(R.check_lab(lab, bad, text)["passed"])
        self.assertFalse(R.check_lab(lab, good, "too short")["passed"])
        self.assertFalse(R.check_lab(lab, dict(good, weighted_mean="abc"), text)["passed"])


if __name__ == "__main__":
    unittest.main()
