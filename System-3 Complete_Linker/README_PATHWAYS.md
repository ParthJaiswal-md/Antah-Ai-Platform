# AntahAI Learning Pathways (Round 2)

Competency-based recommendations and interactive learning roadmaps, added to
System 3. It uses the same Flask app, login and SQLite file. Round-1 features
(the role intake, iGOT-dataset recommender and video quizzes) are unchanged
and still in the nav as **Role recommender (Round 1)**.

> **Demonstration data.** Course titles, lessons, competency mappings, goal
> requirements and prerequisites are illustrative prototype content. They are
> not official iGOT courses and not official MoSPI job-role frameworks.

## Run

```bash
cd "System-3 Complete_Linker"
pip install flask python-dotenv          # (pypdf optional, for PDF resumes)
python app.py                            # http://127.0.0.1:8080
```

The pathways pages do not need System 1 or System 2 to be running. The full
launcher (`run_antahai.py`) still works as before.

Log in as a demo learner (password `demo1234`):

| user | profile |
|---|---|
| `demo_asha` | Strong, assessment-validated Python; weaker statistics |
| `demo_ravi` | New to Python and statistics |

For the same goal the engine gives them different journeys. Asha skips
Python Fundamentals. Ravi is routed through Python Fundamentals and
Statistics & Sampling before Python for Statistical Computing. See
**Compare demo learners**. Demo accounts can reset both learners from that page.

## Tests

```bash
python -m unittest discover -s tests -p "test_pathways*.py"   # 47 tests (pytest also works)
python smoke_e2e.py                                           # Round-1 regression
```

The tests cover ranking, gap maths, prerequisite ordering, cycle detection,
roadmap generation and layout, evidence rules, completion updates,
multi-roadmap sync, auth/CSRF/ownership, and the full HTTP journey.

## Architecture

```
pathways/
  data/catalogue.json   competencies, 7 courses (+lessons, quizzes, 1 lab), 4 goals,
                        1 mock-iGOT listing, 2 demo learners (all data, no logic)
  catalogue.py          loader, validation, connector adapters (Local + MockIGOT)
  engine.py             PURE: gaps, scoring, plan selection, prerequisite closure,
                        cycle detection, roadmap graph + server-side layout
  rules.py              PURE: evidence aggregation, quiz grading, remediation,
                        assessment/lab evidence, lab checker
  store.py              normalised pw_* tables, idempotent seeding, persistence
  service.py            orchestration; every change -> refresh_all_roadmaps()
  resume.py             resume suggestions (keyword; optional Groq, validated)
  web.py                Flask blueprint: pages + /api/pathways/* JSON
static/js/roadmap.js    dependency-free SVG/HTML graph renderer (pan, zoom, pinch,
                        fit, reset, minimap, keyboard, drawer)
```

### Recommendation engine

1. **Gaps**: for each goal requirement, `gap = max(0, target − current)`. Missing
   evidence counts as 0 and is flagged `no_evidence`.
2. **Plan**: a greedy weighted set-cover over the gaps. Available courses are
   used first. An unavailable (mock iGOT) listing is used only if nothing else
   closes the gap, and it is shown as unavailable.
3. **Prerequisites** are competency thresholds such as `py_basics ≥ 50`, not
   course IDs. If an unmet threshold exists, a provider course is added as a
   foundation step. If the learner already meets it, nothing is added, and
   "Why not these courses?" explains why.
4. **Score** (`ANTAHAI_SCORE_WEIGHTS` can override these; they are normalised):
   gap coverage 50%, goal relevance 25%, prerequisite readiness 15%, level fit 10%.
   These are starting weights, not calibrated claims.
5. **Hard rules before score**: completed courses are excluded unless revision is
   requested. A locked course (unmet prerequisite) always ranks after startable
   courses, whatever its score.
6. **Cycles** in the prerequisite graph raise `PrerequisiteCycleError` (HTTP 409)
   instead of producing an invalid graph.

### Evidence rules (0–100 scale)

| source | counts? | confidence |
|---|---|---|
| assessment (quiz ≥70% or lab) | yes, and it overrides self-report | 0.9 |
| self_reported | yes, until assessed | 0.5 |
| resume_inferred | **no**, only after the learner confirms it (then stored as self-report) | 0.3 |

When a quiz is passed, each competency is credited at
`course_level × min(1, accuracy ÷ 0.8)`, using only that competency's questions.
Reading lessons or opening a course only updates progress. A failed attempt
gives targeted revision (the lessons behind the missed questions) and changes
no competency level. The lab's numeric answers are computed from its dataset
and never hard-coded.

### Roadmaps

- One roadmap per goal per learner, stored as nodes and edges with positions.
- All roadmaps share one set of enrollments and evidence. A completion
  recalculates **every** saved roadmap, and the version number increments.
- Recalculation keeps completed courses and the prerequisite edges that led
  out of them, so learning history stays visible.
- Node types: start, course, assessment, lab, skill milestone, goal.
- Node states: completed, in progress, available, locked (with the unmet
  prerequisite), unavailable, and a "recommended next" highlight.

### iGOT integration

`MockIGOTConnector` is clearly labelled and always reports
`availability="unavailable"` with an unverified duration. To connect the real
iGOT catalogue, implement `CatalogueConnector.listings()` returning the same
dict shape. The engine does not change.

### Organisations

`pw_organizations` is seeded with department **names only** from Round-1
`Dataset-2_Required_Competency.csv`. No competency requirements are inferred
from it. `store.import_organizations([(ministry, department), ...], source=...)`
imports an official master list (for example, parsed from the organisation
PDF) when one is available.

## Known limitations

- The roadmap uses a custom SVG renderer instead of React Flow. The app has no
  React or build step, and this keeps the demo working offline.
- The AI resume pass runs only if `GROQ_API_KEY` and `langchain_groq` are
  present. Otherwise the deterministic keyword method is used. Recommendation
  explanations are deterministic templates, not LLM text.
- The organisation PDF was not available in this session. The importer
  function is ready, but no PDF parser was written for a format not yet seen.
- CSRF protection covers the pathways routes. Round-1 routes are unchanged.
