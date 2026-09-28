"""End-to-end HTTP flow through the Flask app (test client, temp DB).

profile -> goal -> recommendations -> roadmap -> learn -> quiz (fail) ->
remediation -> retry (pass) -> competency update -> recalculated roadmaps ->
shared completion in a second roadmap -> persistence across login ->
two demo learners with different journeys.
"""

import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="pw_flow_")
os.environ["ANTAHAI_DB"] = os.path.join(_TMP, "flow.db")
os.environ["ANTAHAI_SECRET"] = "flow-test"

import db  # noqa: E402

DB_FILE = os.environ["ANTAHAI_DB"]
db.DB_PATH = DB_FILE

from app import app  # noqa: E402
from pathways import catalogue as cat  # noqa: E402

RAW = cat.load_raw()


def answers(course_id, correct=True):
    course = next(c for c in RAW["courses"] if c["id"] == course_id)
    out = {}
    for q in course["quiz"]["questions"]:
        a = q["answer"] if correct else (q["answer"] + 1) % len(q["options"])
        out[f"q_{q['id']}"] = str(a)
    return out


class FlowTests(unittest.TestCase):
    def setUp(self):
        db.DB_PATH = DB_FILE
        app.config["TESTING"] = True
        self.c = app.test_client()

    def login(self, user, pwd="demo1234"):
        r = self.c.post("/login", json={"username": user, "password": pwd})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.get_json()["redirect"], "/dashboard")
        page = self.c.get("/dashboard")
        self.assertEqual(page.status_code, 200)
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)

    def api(self, method, url, body=None):
        return self.c.open(url, method=method, json=body, headers={"X-CSRF-Token": self.token})

    def test_auth_and_csrf_protection(self):
        self.assertEqual(self.c.get("/dashboard").status_code, 302)
        self.assertEqual(self.c.get("/api/pathways/roadmaps").status_code, 401)
        self.login("demo_asha")
        r = self.c.post("/api/pathways/roadmaps", json={"goal_id": "stat_data_analyst", "confirmed": True})
        self.assertEqual(r.status_code, 400)  # no CSRF token
        r = self.api("POST", "/api/pathways/roadmaps", {"goal_id": "stat_data_analyst"})
        self.assertEqual(r.status_code, 422)  # requirements not confirmed
        r = self.api("POST", "/api/pathways/roadmaps", {"goal_id": "nope", "confirmed": True})
        self.assertEqual(r.status_code, 404)

    def test_roadmaps_are_private(self):
        self.login("demo_asha")
        rid = self.api("POST", "/api/pathways/roadmaps",
                       {"goal_id": "survey_sampling", "confirmed": True}).get_json()["id"]
        self.c.get("/logout")
        db.create_user("intruder", app.config["PW_HASH"]("intruder", "pw"))
        self.login("intruder", "pw")
        self.assertEqual(self.c.get(f"/roadmaps/{rid}").status_code, 404)
        self.assertEqual(self.api("GET", f"/api/pathways/roadmaps/{rid}").status_code, 404)
        self.assertEqual(self.api("DELETE", f"/api/pathways/roadmaps/{rid}").status_code, 404)

    def test_full_learning_loop(self):
        self.login("demo_ravi")

        # 1-2. Confirm competencies (self-report update is persisted).
        r = self.api("PUT", "/api/pathways/profile", {"basics": {"experience_years": 3}, "levels": {"sampling": 15}})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("My competencies", self.c.get("/competencies").get_data(as_text=True))

        # 3-4. Goal analysis: gaps + small explained recommendation set.
        page = self.c.get("/goals/stat_data_analyst").get_data(as_text=True)
        self.assertIn("Why not these courses?", page)
        a = self.api("GET", "/api/pathways/goals/stat_data_analyst/analysis").get_json()["analysis"]
        self.assertLessEqual(len(a["recommendations"]), 6)
        self.assertTrue(all(r["reasons"] for r in a["recommendations"]))
        self.assertEqual(a["recommendations"][0]["status"], "ready")

        # 5. Generate + save two roadmaps.
        rid = self.api("POST", "/api/pathways/roadmaps", {"goal_id": "stat_data_analyst", "confirmed": True}).get_json()["id"]
        rid2 = self.api("POST", "/api/pathways/roadmaps", {"goal_id": "survey_sampling", "confirmed": True}).get_json()["id"]
        self.assertIn("rmCanvas", self.c.get(f"/roadmaps/{rid}").get_data(as_text=True))
        rm = self.api("GET", f"/api/pathways/roadmaps/{rid}").get_json()["roadmap"]
        nodes = {n["id"]: n for n in rm["nodes"]}
        self.assertEqual(nodes["course:PY201"]["state"], "locked")
        self.assertIn("course:PY101", nodes)

        # 6. Open learning content from a node.
        self.assertEqual(self.api("POST", "/api/pathways/courses/STAT101/start").status_code, 200)
        page = self.c.get(f"/learn/STAT101?roadmap={rid}").get_data(as_text=True)
        self.assertIn("Centre and spread", page)
        r = self.api("POST", "/api/pathways/courses/STAT101/lessons/stat101-1/complete")
        self.assertEqual(r.status_code, 200)
        levels_before = self.api("GET", "/api/pathways/profile").get_json()["view"]["competencies"]
        desc_before = next(c for c in levels_before if c["id"] == "desc_stats")["level"]
        self.assertEqual(desc_before, 25)  # reading a lesson changes nothing

        # 7. Quiz fail -> remediation, no competency change.
        r = self.c.post(f"/learn/STAT101/assessment?roadmap={rid}",
                        data=dict(answers("STAT101", correct=False), csrf_token=self.token))
        self.assertEqual(r.status_code, 302)
        page = self.c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Targeted revision", page)
        self.assertIn("Retry assessment", page)

        # 7-8. Retry and pass -> evidence-based update.
        r = self.c.post(f"/learn/STAT101/assessment?roadmap={rid}",
                        data=dict(answers("STAT101"), csrf_token=self.token))
        page = self.c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Passed: competency evidence recorded", page)
        self.assertIn("Roadmaps recalculated", page)
        view = self.api("GET", "/api/pathways/profile").get_json()["view"]
        desc = next(c for c in view["competencies"] if c["id"] == "desc_stats")
        self.assertEqual((desc["level"], desc["basis"]), (65, "assessment"))

        # 9-10. Both roadmaps recalculated from the shared completion.
        for r_id in (rid, rid2):
            rm = self.api("GET", f"/api/pathways/roadmaps/{r_id}").get_json()["roadmap"]
            n = {x["id"]: x for x in rm["nodes"]}
            self.assertEqual(n["course:STAT101"]["state"], "completed")
        rm = self.api("GET", f"/api/pathways/roadmaps/{rid}").get_json()["roadmap"]
        n = {x["id"]: x for x in rm["nodes"]}
        self.assertEqual(n["course:VIZ201"]["state"], "available")  # desc_stats prereq now met
        self.assertEqual(n["course:PY201"]["state"], "locked")      # still needs Python basics
        pre = {p["competency"]: p["satisfied"] for p in n["course:PY201"]["data"]["prerequisites"]}
        self.assertEqual(pre, {"desc_stats": True, "py_basics": False})

        # 11. Log out, log in again: everything persisted.
        self.c.get("/logout")
        self.login("demo_ravi")
        listing = self.api("GET", "/api/pathways/roadmaps").get_json()["roadmaps"]
        self.assertEqual({r["id"] for r in listing}, {rid, rid2})
        dash = self.c.get("/dashboard").get_data(as_text=True)
        self.assertIn("Statistics and Sampling Fundamentals", dash)

    def test_lab_flow_and_locking(self):
        self.login("demo_asha")
        r = self.c.get("/learn/LAB301/lab")
        self.assertIn("Pass the course assessment first", r.get_data(as_text=True))
        r = self.c.post("/learn/LAB301/assessment", data=dict(answers("LAB301"), csrf_token=self.token))
        self.assertEqual(r.status_code, 422)  # Asha lacks the lab prerequisites

    def test_compare_demo_learners_differ(self):
        self.login("demo_asha")
        self.assertEqual(self.c.get("/compare").status_code, 200)
        d = self.api("GET", "/api/pathways/compare?goal=stat_data_analyst").get_json()
        by = {l["username"]: l["roadmap"] for l in d["learners"]}
        self.assertNotIn("PY101", by["demo_asha"]["course_ids"])
        self.assertIn("PY101", by["demo_ravi"]["course_ids"])
        self.assertNotEqual(by["demo_asha"]["analysis"]["recommendations"][0]["course_id"],
                            by["demo_ravi"]["analysis"]["recommendations"][0]["course_id"])

    def test_resume_extraction_endpoint(self):
        db.create_user("resumeuser", app.config["PW_HASH"]("resumeuser", "pw"))
        self.login("resumeuser", "pw")
        text = ("Statistical Officer. Built pandas pipelines for PLFS survey data over 4 years. "
                "Wrote SQL joins across district tables. Created Tableau dashboards.")
        r = self.api("POST", "/api/pathways/resume", {"text": text})
        self.assertEqual(r.status_code, 200, r.data)
        sugg = {s["competency"]: s for s in r.get_json()["view"]["suggestions"]}
        self.assertTrue({"py_stats", "sql", "dataviz", "survey_dq"} <= set(sugg))
        self.assertTrue(all(s["level"] <= 45 for s in sugg.values()))
        view = r.get_json()["view"]
        self.assertEqual(next(c for c in view["competencies"] if c["id"] == "sql")["level"], 0)
        r = self.api("POST", f"/api/pathways/resume/{sugg['sql']['id']}", {"accept": True, "level": 40})
        sql = next(c for c in r.get_json()["view"]["competencies"] if c["id"] == "sql")
        self.assertEqual((sql["level"], sql["basis"]), (40, "self_reported"))
        r = self.c.post("/api/pathways/resume", data={"file": (__import__("io").BytesIO(b"x"), "cv.exe")},
                        headers={"X-CSRF-Token": self.token}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)


    def test_healthz_and_dashboard_embed_and_resources(self):
        r = self.c.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.login("demo_asha")
        rid = self.api("POST", "/api/pathways/roadmaps", {"goal_id": "dataviz_specialist", "confirmed": True}).get_json()["id"]
        dash = self.c.get("/dashboard").get_data(as_text=True)
        self.assertIn('id="dashCanvas"', dash)
        self.assertIn(f'data-rid="{rid}"', dash)
        rm = self.api("GET", f"/api/pathways/roadmaps/{rid}").get_json()["roadmap"]
        viz = next(n for n in rm["nodes"] if n["id"] == "course:VIZ201")
        self.assertTrue(viz["data"]["resources"][0]["url"].startswith("https://"))
        mock = next(n for n in rm["nodes"] if n["id"] == "course:IGOT-MOCK-DISSEM")
        self.assertEqual(mock["state"], "unavailable")
        self.assertTrue(any("unsdglearn" in r["url"] for r in mock["data"]["resources"]))
        page = self.c.get("/learn/IGOT-MOCK-DISSEM").get_data(as_text=True)
        self.assertIn("Real external alternatives", page)
        self.assertIn("Further study", self.c.get("/learn/VIZ201").get_data(as_text=True))

    def test_migration_is_idempotent(self):
        from pathways import store
        store.migrate(); store.migrate()
        self.assertEqual(store.engine_courses()[0]["resources"] is not None, True)


if __name__ == "__main__":
    unittest.main()
