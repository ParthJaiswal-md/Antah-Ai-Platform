"""Service-level tests (real SQLite in a temp dir): persistence, evidence rules,
completion updates and multi-roadmap synchronisation."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="pw_service_")
os.environ["ANTAHAI_DB"] = os.path.join(_TMP, "pw.db")

import db  # noqa: E402

DB_FILE = os.environ["ANTAHAI_DB"]
db.DB_PATH = DB_FILE

from pathways import catalogue as cat  # noqa: E402
from pathways import rules as R  # noqa: E402
from pathways import service as S  # noqa: E402
from pathways import store  # noqa: E402

RAW = cat.load_raw()


def correct_answers(course_id):
    course = next(c for c in RAW["courses"] if c["id"] == course_id)
    return {q["id"]: q["answer"] for q in course["quiz"]["questions"]}


def wrong_answers(course_id):
    course = next(c for c in RAW["courses"] if c["id"] == course_id)
    return {q["id"]: (q["answer"] + 1) % len(q["options"]) for q in course["quiz"]["questions"]}


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.DB_PATH = DB_FILE
        store.migrate()
        store.seed_catalogue()
        store.seed_catalogue()  # idempotent

    def setUp(self):
        self.uid = db.create_user(f"u{self.id().split('.')[-1]}", "x")

    def test_seed_is_idempotent_and_normalised(self):
        courses = store.engine_courses()
        self.assertEqual(len(courses), 8)  # 7 local + 1 mock listing
        detail = store.course_detail("STAT101")
        self.assertEqual(len(detail["lessons"]), 3)
        self.assertEqual(len(detail["questions"]), 6)
        self.assertIsNotNone(store.course_detail("LAB301")["lab"])

    def test_lesson_progress_never_changes_competency(self):
        before = S.levels(self.uid)
        S.mark_lesson(self.uid, "PY101", "py101-1")
        S.mark_lesson(self.uid, "PY101", "py101-2")
        self.assertEqual(S.levels(self.uid), before)
        prog = S.progress(self.uid)["PY101"]
        self.assertEqual(prog["status"], "in_progress")
        self.assertGreater(prog["percent"], 0)

    def test_locked_course_cannot_be_started(self):
        with self.assertRaises(S.ValidationError):
            S.start_course(self.uid, "PY201")
        with self.assertRaises(S.ValidationError):
            S.submit_quiz(self.uid, "PY201", correct_answers("PY201"))

    def test_unavailable_course_cannot_be_started(self):
        with self.assertRaises(S.ValidationError):
            S.start_course(self.uid, "IGOT-MOCK-DISSEM")

    def test_failed_quiz_remediation_then_retry(self):
        out = S.submit_quiz(self.uid, "SQL101", wrong_answers("SQL101"))
        self.assertFalse(out["result"]["passed"])
        self.assertTrue(out["remediation"])
        self.assertEqual(out["competency_changes"], [])
        self.assertEqual(S.progress(self.uid)["SQL101"]["status"], "in_progress")
        out = S.submit_quiz(self.uid, "SQL101", correct_answers("SQL101"))
        self.assertTrue(out["result"]["passed"])
        self.assertTrue(out["course_completed"])
        self.assertEqual(S.levels(self.uid)["sql"]["level"], 65)
        self.assertEqual(S.levels(self.uid)["sql"]["basis"], "assessment")
        self.assertEqual(len(store.attempts(self.uid, "SQL101")), 2)

    def test_completion_syncs_across_roadmaps(self):
        S.update_profile(self.uid, {}, {"desc_stats": 20, "py_basics": 10})
        r1 = S.generate_roadmap(self.uid, "stat_data_analyst")
        r2 = S.generate_roadmap(self.uid, "survey_sampling")
        self.assertNotEqual(r1, r2)
        before = {r["id"]: r for r in store.list_roadmaps(self.uid)}
        out = S.submit_quiz(self.uid, "STAT101", correct_answers("STAT101"))
        self.assertTrue(out["course_completed"])
        self.assertEqual({r["id"] for r in out["roadmaps"]}, {r1, r2})
        for rid in (r1, r2):
            rm = store.get_roadmap(self.uid, rid)
            node = next(n for n in rm["nodes"] if n["id"] == "course:STAT101")
            self.assertEqual(node["state"], "completed")
            self.assertGreater(rm["version"], before[rid]["version"])
            self.assertNotIn("STAT101", [r["course_id"] for r in rm["analysis"]["recommendations"]])
            self.assertGreater(rm["readiness"], before[rid]["readiness"])
        # One enrollment record shared by both roadmaps - no duplicate course work.
        self.assertEqual(list(store.enrollments(self.uid)).count("STAT101"), 1)

    def test_prereq_unlock_after_completion(self):
        S.update_profile(self.uid, {}, {"desc_stats": 20, "py_basics": 10})
        rid = S.generate_roadmap(self.uid, "stat_data_analyst")
        rm = store.get_roadmap(self.uid, rid)
        state = {n["id"]: n["state"] for n in rm["nodes"]}
        self.assertEqual(state["course:PY201"], "locked")
        S.submit_quiz(self.uid, "PY101", correct_answers("PY101"))
        S.submit_quiz(self.uid, "STAT101", correct_answers("STAT101"))
        rm = store.get_roadmap(self.uid, rid)
        state = {n["id"]: n["state"] for n in rm["nodes"]}
        self.assertEqual(state["course:PY201"], "available")
        self.assertEqual(state["course:PY101"], "completed")
        # History kept: the path PY101 -> PY201 remains visible.
        self.assertIn("quiz:PY101->course:PY201", {e["id"] for e in rm["edges"]})

    def test_lab_required_for_completion(self):
        S.update_profile(self.uid, {}, {"py_stats": 60, "infer_stats": 50, "sql": 50})
        out = S.submit_quiz(self.uid, "LAB301", correct_answers("LAB301"))
        self.assertTrue(out["result"]["passed"])
        self.assertFalse(out["course_completed"])
        self.assertTrue(out["needs_lab"])
        self.assertNotIn("applied_analysis", S.levels(self.uid))
        lab = store.course_detail("LAB301")["lab"]
        answers = {k: str(v) for k, v in R.lab_expected(lab).items()}
        res = S.submit_lab(self.uid, "LAB301", answers,
                           "Region A consumption is higher than Region B and the difference is significant.")
        self.assertTrue(res["result"]["passed"])
        self.assertTrue(res["course_completed"])
        self.assertEqual(S.levels(self.uid)["applied_analysis"]["level"], 75)

    def test_resume_suggestions_need_confirmation(self):
        S.store_resume_suggestions(self.uid, [{"competency": "sql", "level": 45, "note": "x", "method": "keyword"}])
        self.assertEqual(S.levels(self.uid)["sql"]["level"], 0)
        sugg = S.profile_view(self.uid)["suggestions"]
        self.assertEqual(len(sugg), 1)
        S.confirm_suggestion(self.uid, sugg[0]["id"], 35, accept=True)
        lv = S.levels(self.uid)["sql"]
        self.assertEqual((lv["level"], lv["basis"]), (35, "self_reported"))
        self.assertEqual(S.profile_view(self.uid)["suggestions"], [])

    def test_validation_of_profile_input(self):
        with self.assertRaises(S.ValidationError):
            S.update_profile(self.uid, {}, {"sql": 150})
        with self.assertRaises(S.ValidationError):
            S.update_profile(self.uid, {}, {"unknown": 10})
        with self.assertRaises(S.ValidationError):
            S.update_profile(self.uid, {"experience_years": "abc"}, {})

    def test_demo_learners_seeded_once_and_resettable(self):
        users = {}

        def create(u, p):
            users[u] = db.create_user(u + self.id()[-6:], p)
            return users[u]

        ids = S.seed_demo_learners(RAW, create, lambda u: None)
        self.assertEqual(len(ids), 2)
        n = len(store.evidence(ids[0]))
        S.seed_demo_learners(RAW, create, lambda u: {"id": users[u]})
        self.assertEqual(len(store.evidence(ids[0])), n)


if __name__ == "__main__":
    unittest.main()
