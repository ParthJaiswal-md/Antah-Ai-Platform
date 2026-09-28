"""
AntahAI Learning Pathways - resume competency extraction.

Produces *suggestions only* (evidence source ``resume_inferred``). A resume
mention is never treated as mastery: suggested levels are capped at 45 on the
0-100 scale and do not count toward any calculation until the learner
confirms or corrects them.

Two methods:
  keyword  Always available and deterministic: matches each competency's
           keyword list and quotes the sentence it came from.
  ai       Optional. If GROQ_API_KEY is set and ``langchain_groq`` is
           installed (System 2's stack), the model may only return competency
           IDs from our fixed list plus a supporting quote. Unknown IDs and
           quotes that are not in the resume text are discarded. Levels are
           still assigned by the deterministic rule below, never by the model.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

MAX_TEXT = 40_000
BASE_LEVEL = 30
STRONG_LEVEL = 45
STRONG_HINTS = re.compile(
    r"\b(advanced|expert|proficient|extensive|led|lead|designed|built|developed|\d+\+?\s*years?)\b", re.I)
ALLOWED_EXT = {".txt", ".pdf"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class ResumeError(ValueError):
    pass


def text_from_upload(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise ResumeError("Upload a .txt or .pdf resume.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ResumeError("Resume file is larger than 2 MB.")
    if ext == ".txt":
        return data.decode("utf-8", errors="replace")[:MAX_TEXT]
    try:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            from PyPDF2 import PdfReader  # type: ignore
    except ImportError:
        raise ResumeError("PDF support is not installed on the server; paste the resume text instead.")
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:10])
    except Exception as err:  # noqa: BLE001 - malformed PDFs raise many types
        raise ResumeError(f"Could not read that PDF ({err.__class__.__name__}).")
    if not text.strip():
        raise ResumeError("No text found in the PDF (it may be a scanned image). Paste the text instead.")
    return text[:MAX_TEXT]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def keyword_extract(text: str, competencies: dict[str, dict]) -> list[dict]:
    sentences = _sentences(text)
    found = []
    for cid, comp in competencies.items():
        best = None
        for kw in comp.get("keywords", []):
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])")
            for s in sentences:
                if pattern.search(s.lower()):
                    strong = bool(STRONG_HINTS.search(s))
                    cand = (strong, kw, s)
                    if best is None or (strong and not best[0]):
                        best = cand
        if best:
            strong, kw, sentence = best
            found.append({
                "competency": cid,
                "level": STRONG_LEVEL if strong else BASE_LEVEL,
                "method": "keyword",
                "note": f"Resume mentions “{kw}”: “{sentence[:160]}”",
            })
    return found


def ai_extract(text: str, competencies: dict[str, dict]) -> list[dict]:
    """Optional LLM pass; returns [] whenever it is unavailable or unsure."""
    if not os.environ.get("GROQ_API_KEY"):
        return []
    try:
        from langchain_groq import ChatGroq  # type: ignore
    except ImportError:
        return []
    catalogue = "\n".join(f"- {cid}: {c['name']} - {c['description']}" for cid, c in competencies.items())
    prompt = (
        "You extract competencies from a resume. Use ONLY these competency ids:\n"
        f"{catalogue}\n\nReturn JSON: a list of objects {{\"id\": <id>, \"quote\": <exact short quote "
        "from the resume that supports it>}}. Do not guess proficiency. Return [] if none.\n\n"
        f"RESUME:\n{text[:8000]}"
    )
    try:
        llm = ChatGroq(api_key=os.environ["GROQ_API_KEY"], model_name="openai/gpt-oss-20b",
                       temperature=0, timeout=20)
        raw = llm.invoke(prompt).content
        start, end = raw.find("["), raw.rfind("]")
        items = json.loads(raw[start:end + 1]) if start >= 0 and end > start else []
    except Exception:  # noqa: BLE001 - AI is optional; never fail the request
        logger.warning("AI resume extraction unavailable; using keyword method only", exc_info=True)
        return []
    out = []
    lower = text.lower()
    for item in items if isinstance(items, list) else []:
        cid = str((item or {}).get("id", ""))
        quote = str((item or {}).get("quote", ""))[:200]
        if cid not in competencies or not quote or quote.lower() not in lower:
            continue  # reject hallucinated ids or quotes
        out.append({"competency": cid, "level": STRONG_LEVEL if STRONG_HINTS.search(quote) else BASE_LEVEL,
                    "method": "ai", "note": f"AI-suggested from resume: “{quote}”"})
    return out


def extract(text: str, competencies: dict[str, dict]) -> list[dict]:
    text = (text or "")[:MAX_TEXT]
    if len(text.strip()) < 20:
        raise ResumeError("Resume text is too short to analyse.")
    merged = {s["competency"]: s for s in keyword_extract(text, competencies)}
    for s in ai_extract(text, competencies):
        if s["competency"] not in merged:
            merged[s["competency"]] = s
    return sorted(merged.values(), key=lambda s: s["competency"])
