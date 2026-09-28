"""
AntahAI Learning Pathways - catalogue loading, validation and connectors.

Course metadata lives in ``data/catalogue.json`` (and, later, in external
sources) - never in the recommendation logic. Adding a course means adding
its metadata, competency mappings and prerequisites to a connector's output;
``engine.py`` does not change.

Connectors (adapter pattern):
  LocalCatalogueConnector  curated local courses with real content (available)
  MockIGOTConnector        CLEARLY LABELLED MOCK of a future iGOT Karmayogi
                           integration. It returns static listings marked
                           ``source="igot_mock"`` and ``availability="unavailable"``.
                           No live iGOT API is contacted or claimed.

A real iGOT connector only has to implement ``CatalogueConnector.listings()``
returning the same dict shape and set ``live=True`` once verified.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "catalogue.json"

VALID_DIFFICULTY = {"beginner", "intermediate", "advanced"}
VALID_AVAILABILITY = {"available", "unavailable"}


class CatalogueError(ValueError):
    pass


def load_raw(path: Path | None = None) -> dict:
    with open(path or DATA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


class CatalogueConnector:
    name = "base"
    label = ""
    live = False

    def listings(self) -> list[dict]:  # pragma: no cover - interface
        raise NotImplementedError


class LocalCatalogueConnector(CatalogueConnector):
    name = "local"
    label = "AntahAI curated catalogue (demonstration content)"
    live = True

    def __init__(self, raw: dict):
        self._raw = raw

    def listings(self) -> list[dict]:
        return [dict(c) for c in self._raw.get("courses", [])]


class MockIGOTConnector(CatalogueConnector):
    name = "igot_mock"
    label = "iGOT Karmayogi connector - MOCK (no live connection)"
    live = False

    def __init__(self, raw: dict):
        self._raw = raw

    def listings(self) -> list[dict]:
        out = []
        for c in self._raw.get("external_listings", []):
            c = dict(c)
            # Never claim availability for something we have not verified.
            c["source"] = "igot_mock"
            c["availability"] = "unavailable"
            c["duration_verified"] = False
            out.append(c)
        return out


def connectors(raw: dict) -> list[CatalogueConnector]:
    return [LocalCatalogueConnector(raw), MockIGOTConnector(raw)]


def validate(raw: dict) -> None:
    """Fail loudly on inconsistent metadata instead of generating bad roadmaps."""
    comps = {c["id"] for c in raw.get("competencies", [])}
    errors: list[str] = []
    seen: set[str] = set()
    all_courses = raw.get("courses", []) + raw.get("external_listings", [])
    for c in all_courses:
        cid = c.get("id")
        if not cid or cid in seen:
            errors.append(f"duplicate or missing course id: {cid!r}")
        seen.add(cid)
        if c.get("difficulty") not in VALID_DIFFICULTY:
            errors.append(f"{cid}: bad difficulty {c.get('difficulty')!r}")
        if c.get("availability", "available") not in VALID_AVAILABILITY:
            errors.append(f"{cid}: bad availability")
        for comp, lvl in (c.get("develops") or {}).items():
            if comp not in comps:
                errors.append(f"{cid}: develops unknown competency {comp}")
            if not 0 < int(lvl) <= 100:
                errors.append(f"{cid}: develops level out of range for {comp}")
        for pre in c.get("prerequisites", []):
            if pre.get("competency") not in comps:
                errors.append(f"{cid}: prerequisite on unknown competency {pre.get('competency')}")
            if not 0 < int(pre.get("min_level", 0)) <= 100:
                errors.append(f"{cid}: prerequisite level out of range")
        for r in c.get("resources", []):
            if not str(r.get("url", "")).startswith("https://") or not r.get("title"):
                errors.append(f"{cid}: external resource needs a title and an https:// url")
        lessons = {l["id"] for l in c.get("lessons", [])}
        quiz = c.get("quiz")
        if c.get("availability", "available") == "available" and c in raw.get("courses", []):
            if not lessons:
                errors.append(f"{cid}: available course has no lessons")
            if not quiz or not quiz.get("questions"):
                errors.append(f"{cid}: available course has no assessment")
        if quiz:
            qids = set()
            quizzed = set()
            for q in quiz["questions"]:
                if q["id"] in qids:
                    errors.append(f"{cid}: duplicate question id {q['id']}")
                qids.add(q["id"])
                if q["competency"] not in (c.get("develops") or {}):
                    errors.append(f"{cid}/{q['id']}: question competency not developed by course")
                if q.get("lesson") not in lessons:
                    errors.append(f"{cid}/{q['id']}: question references unknown lesson")
                if not 0 <= int(q["answer"]) < len(q["options"]):
                    errors.append(f"{cid}/{q['id']}: answer index out of range")
                quizzed.add(q["competency"])
            lab_comps = set((c.get("lab") or {}).get("develops", {}))
            missing = set(c.get("develops", {})) - quizzed - lab_comps
            if missing:
                errors.append(f"{cid}: no assessment evidence path for {sorted(missing)}")
    for g in raw.get("goals", []):
        for req in g.get("requirements", []):
            if req["competency"] not in comps:
                errors.append(f"goal {g['id']}: unknown competency {req['competency']}")
            if not 0 < int(req["target"]) <= 100:
                errors.append(f"goal {g['id']}: target out of range")
    if errors:
        raise CatalogueError("Catalogue validation failed:\n  " + "\n  ".join(errors))


def engine_course(c: dict) -> dict:
    """Project full course metadata to the fields the engine needs."""
    return {
        "id": c["id"],
        "title": c["title"],
        "summary": c.get("summary", ""),
        "outcomes": c.get("outcomes", []),
        "difficulty": c.get("difficulty", "beginner"),
        "duration_minutes": c.get("duration_minutes"),
        "duration_verified": bool(c.get("duration_verified")),
        "availability": c.get("availability", "available"),
        "source": c.get("source", "local"),
        "develops": {k: int(v) for k, v in (c.get("develops") or {}).items()},
        "prerequisites": [
            {"competency": p["competency"], "min_level": int(p["min_level"])}
            for p in c.get("prerequisites", [])
        ],
        "has_quiz": bool((c.get("quiz") or {}).get("questions")),
        "has_lab": bool(c.get("lab")),
        "lab_title": (c.get("lab") or {}).get("title", ""),
        "resources": [dict(r) for r in c.get("resources", [])],
    }
