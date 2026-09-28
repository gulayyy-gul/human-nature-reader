"""
rag_core.py — the single backend shared by streamlit_app.py and gradio_app.py.

No UI code lives here. Both front ends call the same functions:

    index = build_index(pdf_bytes, filename)
    guide = study_guide(index, "The Law of Irrationality")
    reply = ask_book(index, "What is a 'pseudo-event'?")
    q     = make_quiz_question(index, topic, "Recall", asked=[])
    r     = grade_quiz_answer(index, topic, q, "my answer")
    fb    = evaluate_explanation(index, topic, "my explanation", seconds=52)

INTEGRATION NOTE
If you already have working extraction / chunking / embedding / retrieval code,
keep it. Replace the bodies of `extract_pages`, `chunk_pages`, `_embed` and
`retrieve` with yours and keep the return shapes documented below; everything
else (prompts, JSON handling, friendly errors) sits on top of those four.
Environment variable names are unchanged: GROQ_API_KEY (required),
GROQ_MODEL / EMBED_MODEL (optional overrides, defaults below).
"""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

try:  # .env support for local runs; harmless on Streamlit Cloud
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

EMBED_MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
CHUNK_WORDS = 220
CHUNK_OVERLAP = 40
QUIZ_TYPES = ["Recall", "Understanding", "Vocabulary", "Application", "Scenario"]


# --------------------------------------------------------------------------
# Friendly errors
# --------------------------------------------------------------------------
class AppError(Exception):
    """An error the normal user can understand. `detail` is for developers."""

    def __init__(self, title: str, message: str, detail: str = ""):
        super().__init__(f"{title}: {message}")
        self.title, self.message, self.detail = title, message, detail


def _wrap_llm_error(exc: Exception) -> AppError:
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, AppError):
        return exc
    if "RateLimit" in name or "429" in text:
        return AppError("The reader needs a short rest",
                        "Too many requests were sent. Wait a few seconds and try again.", f"{name}: {text}")
    if "Authentication" in name or "401" in text or "invalid_api_key" in text:
        return AppError("Something is missing",
                        "The AI connection could not be verified. If you're the app owner, check the API settings.",
                        f"{name}: {text}")
    if "Connection" in name or "Timeout" in name:
        return AppError("No connection",
                        "The reader could not reach its AI service. Check your internet and try again.",
                        f"{name}: {text}")
    return AppError("Something went wrong",
                    "That didn't work. Please try again in a moment.", f"{name}: {text}")


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class Chunk:
    text: str
    page: int  # PDF page number (1-based; may differ from the printed page number)


@dataclass
class BookIndex:
    title: str
    author: str
    n_pages: int
    chunks: list[Chunk]
    embeddings: np.ndarray
    laws: list[dict] = field(default_factory=list)  # [{"number": 1, "title": "The Law of X", "page": 12}]

    @property
    def n_sections(self) -> int:
        return len(self.chunks)


# --------------------------------------------------------------------------
# Indexing: PDF -> pages -> chunks -> embeddings
# --------------------------------------------------------------------------
def extract_pages(pdf_bytes: bytes) -> tuple[list[str], dict]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [(p.extract_text() or "") for p in reader.pages]
        meta = reader.metadata or {}
    except Exception as exc:
        raise AppError("This file can't be opened",
                       "Please upload a PDF that is not password-protected.", repr(exc)) from exc
    return pages, {"title": getattr(meta, "title", None) or "", "author": getattr(meta, "author", None) or ""}


def chunk_pages(pages: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    step = CHUNK_WORDS - CHUNK_OVERLAP
    for i, text in enumerate(pages, start=1):
        words = text.split()
        if len(words) < 15:
            continue
        for start in range(0, len(words), step):
            piece = " ".join(words[start:start + CHUNK_WORDS])
            if len(piece.split()) >= 15:
                chunks.append(Chunk(piece, i))
            if start + CHUNK_WORDS >= len(words):
                break
    return chunks


@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL_NAME)


def _embed(texts: list[str]) -> np.ndarray:
    vecs = _embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
    return np.asarray(vecs, dtype="float32")


LAW_LINE = re.compile(r"^\s*THE\s+LAW\s+OF\s+([A-Z][A-Z\-\s]{3,40})\s*$")


def detect_laws(pages: list[str]) -> list[dict]:
    """Find headings such as 'THE LAW OF IRRATIONALITY' on their own line."""
    found, seen = [], set()
    for i, text in enumerate(pages, start=1):
        for line in text.splitlines():
            m = LAW_LINE.match(line)
            if not m:
                continue
            name = " ".join(m.group(1).split()).title()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            found.append({"number": len(found) + 1, "title": f"The Law of {name}", "page": i})
    return found if len(found) >= 3 else []


def _clean_title(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", filename, flags=re.I)
    return re.sub(r"[_\-]+", " ", stem).strip().title() or "Your Book"


def build_index(pdf_bytes: bytes, filename: str) -> BookIndex:
    pages, meta = extract_pages(pdf_bytes)
    chunks = chunk_pages(pages)
    if len(chunks) < 3:
        raise AppError("No readable text found",
                       "This PDF looks like scanned images. Try a version where the text can be selected.")
    try:
        emb = _embed([c.text for c in chunks])
    except Exception as exc:
        raise AppError("The book could not be prepared",
                       "Something went wrong while getting the book ready.", repr(exc)) from exc
    return BookIndex(
        title=meta["title"].strip() or _clean_title(filename),
        author=meta["author"].strip(),
        n_pages=len(pages),
        chunks=chunks,
        embeddings=emb,
        laws=detect_laws(pages),
    )


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
def retrieve(index: BookIndex, query: str, k: int = 6) -> list[dict]:
    """Return [{"page": int, "text": str, "score": float}] best-first."""
    q = _embed([query])[0]
    scores = index.embeddings @ q
    top = np.argsort(-scores)[:k]
    return [{"page": index.chunks[i].page, "text": index.chunks[i].text, "score": float(scores[i])} for i in top]


def _retrieve_many(index: BookIndex, queries: list[str], k: int) -> list[dict]:
    merged: dict[str, dict] = {}
    for q in queries:
        for hit in retrieve(index, q, k):
            key = hit["text"][:80]
            if key not in merged or hit["score"] > merged[key]["score"]:
                merged[key] = hit
    return sorted(merged.values(), key=lambda h: -h["score"])[: k + 2]


def _format_context(hits: list[dict]) -> str:
    return "\n\n".join(f"[Page {h['page']}]\n{h['text']}" for h in hits)


def _sources(hits: list[dict]) -> list[dict]:
    """One entry per page, ordered by page, with a short snippet."""
    by_page: dict[int, dict] = {}
    for h in hits:
        cur = by_page.get(h["page"])
        if cur is None or h["score"] > cur["score"]:
            by_page[h["page"]] = {"page": h["page"], "snippet": h["text"][:400], "score": h["score"]}
    return sorted(by_page.values(), key=lambda s: s["page"])


# --------------------------------------------------------------------------
# LLM (Groq)
# --------------------------------------------------------------------------
def _client():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise AppError("Something is missing",
                       "The AI connection hasn't been configured yet. If you're the app owner, check the API settings.",
                       "GROQ_API_KEY is not set (environment variable or Streamlit secret).")
    from groq import Groq

    return Groq(api_key=key)


def ai_ready() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _chat(system: str, user: str, *, json_mode: bool = False, temperature: float = 0.3, max_tokens: int = 2200) -> str:
    client = _client()
    kwargs = dict(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if "gpt-oss" in GROQ_MODEL:  # reasoning models: keep thinking short, leave room for the answer
        kwargs["reasoning_effort"] = "low"
        kwargs["max_tokens"] = max_tokens + 2000
    try:
        return client.chat.completions.create(**kwargs).choices[0].message.content or ""
    except Exception as exc:
        raise _wrap_llm_error(exc) from exc


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AppError("The answer came back garbled", "Please try again.", raw[:500])


TUTOR = (
    "You are a warm, clear reading tutor. The learner's first language is Urdu and they are improving their English. "
    "Write in simple English: short sentences, common words, no jargon. "
    "For claims about the book, use ONLY the excerpts provided. If the excerpts do not cover something, say so briefly. "
    "Keep 'what the book says' separate from 'interpretation', and never present interpretation as a quotation. "
    "Quotations must be copied word-for-word from the excerpts, at most 20 words each, with their page number. "
    "Never reproduce long passages. Urdu must be in Urdu script (Nastaliq-style Arabic letters, no diacritics)."
)


# --------------------------------------------------------------------------
# Study guide
# --------------------------------------------------------------------------
GUIDE_SCHEMA = """Return ONLY a JSON object with exactly these keys:
{
 "core_idea": "3-4 short sentences",
 "story": {"summary": "the main historical example or story, 3-5 sentences",
           "why_included": "why the author used it, 1-2 sentences",
           "demonstrates": "how it shows the central concept, 1-2 sentences"},
 "message": {"book_says": ["2-3 short bullets that the excerpts state"],
             "interpretation": ["1-2 short bullets: your reading, clearly an interpretation"],
             "takeaway": "one memorable sentence"},
 "vocabulary": [{"word": "", "meaning": "simple English, under 10 words", "urdu": "", "synonyms": ["", ""]}],
 "quotes": [{"quote": "", "page": 0, "meaning": "", "why_it_matters": "", "vocabulary": [{"word": "", "meaning": ""}]}],
 "real_life": ["1-2 short everyday examples"],
 "reflection_questions": ["2-3 personal questions"]
}
Give 5-7 useful vocabulary words (skip easy words). Give 2-3 short quotes (only if a good verbatim quote exists)."""


def study_guide(index: BookIndex, topic: str, k: int = 6) -> dict:
    hits = _retrieve_many(index, [topic, f"{topic} story historical example", f"{topic} how to overcome"], k)
    user = f"Topic: {topic}\n\nBook excerpts:\n{_format_context(hits)}\n\n{GUIDE_SCHEMA}"
    data = _parse_json(_chat(TUTOR, user, json_mode=True, temperature=0.25, max_tokens=2600))
    guide = _coerce_guide(data)
    guide["sources"] = _sources(hits)
    return guide


def _coerce_guide(d: dict) -> dict:
    def s(x):
        return x if isinstance(x, str) else ""

    def lst(x):
        return [i for i in x if i] if isinstance(x, list) else []

    story, msg = d.get("story") or {}, d.get("message") or {}
    return {
        "core_idea": s(d.get("core_idea")),
        "story": {"summary": s(story.get("summary")), "why_included": s(story.get("why_included")),
                  "demonstrates": s(story.get("demonstrates"))},
        "message": {"book_says": lst(msg.get("book_says")), "interpretation": lst(msg.get("interpretation")),
                    "takeaway": s(msg.get("takeaway"))},
        "vocabulary": [v for v in lst(d.get("vocabulary")) if isinstance(v, dict) and v.get("word")],
        "quotes": [q for q in lst(d.get("quotes")) if isinstance(q, dict) and q.get("quote")],
        "real_life": lst(d.get("real_life")),
        "reflection_questions": lst(d.get("reflection_questions")),
    }


# --------------------------------------------------------------------------
# Free questions (the classic grounded RAG answer)
# --------------------------------------------------------------------------
def ask_book(index: BookIndex, question: str, k: int = 6) -> dict:
    hits = retrieve(index, question, k)
    user = (f"Question: {question}\n\nBook excerpts:\n{_format_context(hits)}\n\n"
            "Answer in under 150 words using only the excerpts. Mention page numbers like (p. 37).")
    return {"answer": _chat(TUTOR, user, temperature=0.2, max_tokens=600), "sources": _sources(hits), "hits": hits}


# --------------------------------------------------------------------------
# Quiz
# --------------------------------------------------------------------------
QUIZ_HINTS = {
    "Recall": "Ask what the book says about a specific fact or example.",
    "Understanding": "Ask the learner to explain an idea in their own words.",
    "Vocabulary": "Ask the meaning or use of one useful word from the excerpts.",
    "Application": "Ask how the idea applies to a real-life situation.",
    "Scenario": "Describe a short realistic scene and ask what the law would predict or advise.",
}


def make_quiz_question(index: BookIndex, topic: str, qtype: str, asked: list[str] | None = None, k: int = 6) -> dict:
    hits = _retrieve_many(index, [topic], k)
    avoid = "\n".join(f"- {q}" for q in (asked or [])[-6:]) or "none"
    user = (f"Topic: {topic}\nQuestion type: {qtype}. {QUIZ_HINTS.get(qtype, '')}\n"
            f"Questions already asked (do not repeat):\n{avoid}\n\nBook excerpts:\n{_format_context(hits)}\n\n"
            'Return ONLY JSON: {"question": "...", "hint": "one short hint", "key_points": ["2-4 ideas a good answer contains"]}')
    d = _parse_json(_chat(TUTOR, user, json_mode=True, temperature=0.6, max_tokens=500))
    if not isinstance(d.get("question"), str) or not d["question"].strip():
        raise AppError("The question came back empty", "Please try again.")
    return {"type": qtype, "question": d["question"].strip(), "hint": str(d.get("hint") or ""),
            "key_points": [str(p) for p in d.get("key_points", [])][:4]}


def grade_quiz_answer(index: BookIndex, topic: str, quiz: dict, answer: str, k: int = 6) -> dict:
    hits = _retrieve_many(index, [topic, quiz["question"]], k)
    user = (f"Topic: {topic}\nQuestion: {quiz['question']}\nIdeas a good answer contains: {quiz['key_points']}\n"
            f"Learner's answer: {answer}\n\nBook excerpts:\n{_format_context(hits)}\n\n"
            "Be kind and specific. Return ONLY JSON: "
            '{"understood": ["what the learner got right"], "missed": ["what is missing or unclear"], '
            '"correct_understanding": "2-3 sentences", "remember": "one short takeaway"}')
    d = _parse_json(_chat(TUTOR, user, json_mode=True, temperature=0.2, max_tokens=700))
    return {"understood": [str(x) for x in d.get("understood", [])],
            "missed": [str(x) for x in d.get("missed", [])],
            "correct_understanding": str(d.get("correct_understanding", "")),
            "remember": str(d.get("remember", ""))}


# --------------------------------------------------------------------------
# Explain-it feedback
# --------------------------------------------------------------------------
EXPLAIN_DIMENSIONS = ["Understanding", "Clarity", "Vocabulary", "Grammar", "Organization"]


def evaluate_explanation(index: BookIndex, topic: str, text: str, seconds: int | None = None, k: int = 6) -> dict:
    hits = _retrieve_many(index, [topic], k)
    user = (f"Topic: {topic}\nThe learner explained this to a friend who never read the book"
            f"{f' (spoke/typed for about {seconds} seconds)' if seconds else ''}:\n\"\"\"{text}\"\"\"\n\n"
            f"Book excerpts:\n{_format_context(hits)}\n\n"
            "Score each area from 1 to 5 and give concise, encouraging feedback. Return ONLY JSON: "
            '{"scores": {"Understanding": 0, "Clarity": 0, "Vocabulary": 0, "Grammar": 0, "Organization": 0}, '
            '"strengths": "1-2 sentences", "improve": "1-2 sentences", "better_sentence": "one sentence improved from their text"}')
    d = _parse_json(_chat(TUTOR, user, json_mode=True, temperature=0.2, max_tokens=600))
    raw = d.get("scores") or {}
    scores = {}
    for name in EXPLAIN_DIMENSIONS:
        try:
            scores[name] = max(1, min(5, int(raw.get(name, 3))))
        except (TypeError, ValueError):
            scores[name] = 3
    return {"scores": scores, "strengths": str(d.get("strengths", "")), "improve": str(d.get("improve", "")),
            "better_sentence": str(d.get("better_sentence", ""))}
