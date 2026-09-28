"""Human Nature Reader — Streamlit UI (deployment). Backend: rag_core.py"""
import hashlib
import html
import os
import time
import traceback
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

# Streamlit Cloud secrets -> environment (keeps the GROQ_API_KEY name unchanged)
try:
    if "GROQ_API_KEY" in st.secrets and not os.environ.get("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except Exception:
    pass

import rag_core as rc  # noqa: E402

st.set_page_config(page_title="Human Nature Reader", page_icon="📖", layout="wide",
                   initial_sidebar_state="expanded")

esc = html.escape
NAV = ["Home", "Read", "Vocabulary", "Quiz", "Progress", "Settings"]
STEPS = ["Understand", "Story", "Message", "Words", "Quotes", "Reflect", "Explain"]
STEP_LABEL = {"Understand": "💡 Understand", "Story": "📜 Story", "Message": "🧭 Author's message",
              "Words": "🔤 Words", "Quotes": "⭐ Quotes", "Reflect": "🪞 Reflect", "Explain": "🎤 Explain it"}
PLACEHOLDER = "Choose a law…"

# ---------------------------------------------------------------- styling
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Instrument+Sans:wght@400;500;600&family=Noto+Nastaliq+Urdu&display=swap');
:root{--bg:#FAF7F2;--card:#FFFDF9;--ink:#23211E;--muted:#6C675F;--line:#E6E0D5;--accent:#23545B;--accent-soft:#E4EEEC;}
html,body,[class*="css"],.stApp{font-family:'Instrument Sans',system-ui,sans-serif;color:var(--ink);}
.stApp{background:var(--bg);}
#MainMenu,footer,[data-testid="stToolbar"]{visibility:hidden;}
.block-container{max-width:1040px;padding-top:2rem;padding-bottom:4rem;}
h1,h2,h3,.serif{font-family:'Newsreader',Georgia,serif;font-weight:500;letter-spacing:-0.01em;color:var(--ink);}
.brand{font-family:'Newsreader',Georgia,serif;font-size:2.4rem;font-weight:600;line-height:1.1;margin:0;}
.tagline{color:var(--muted);margin:.25rem 0 1.25rem;font-size:1.02rem;}
.kicker{color:var(--muted);font-size:.85rem;margin-bottom:.2rem;}
.law-title{font-family:'Newsreader',Georgia,serif;font-size:2.2rem;font-weight:600;line-height:1.15;margin:.1rem 0 .6rem;}
.sec-title{font-family:'Newsreader',Georgia,serif;font-size:1.35rem;font-weight:600;margin:0 0 .5rem;}
.sub{font-weight:600;margin:.9rem 0 .2rem;}
.lead{font-size:1.06rem;line-height:1.65;max-width:68ch;}
.urdu{font-family:'Noto Nastaliq Urdu',serif;direction:rtl;text-align:right;font-size:1.15rem;line-height:2.1;color:var(--accent);}
.quote{font-family:'Newsreader',Georgia,serif;font-size:1.25rem;line-height:1.5;border-left:3px solid var(--accent);padding:.1rem 0 .1rem 1rem;margin:.2rem 0 .8rem;}
.pill{display:inline-block;background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:.1rem .65rem;font-size:.82rem;margin:0 .3rem .3rem 0;}
.callout{background:var(--accent-soft);border-radius:12px;padding:.85rem 1.1rem;margin-top:.8rem;font-family:'Newsreader',Georgia,serif;font-size:1.15rem;}
.muted{color:var(--muted);}
.bigword{font-family:'Newsreader',Georgia,serif;font-size:1.5rem;font-weight:600;}
div[data-testid="stVerticalBlockBorderWrapper"]{background:var(--card);border:1px solid var(--line)!important;border-radius:16px!important;box-shadow:none;transition:border-color .15s ease;}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{border-color:#C9C1B2!important;}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px!important;}
.stButton>button,.stDownloadButton>button{border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:.35rem 1.1rem;font-weight:500;}
.stButton>button:hover{border-color:var(--accent);color:var(--accent);}
.stButton>button[kind="primary"]{background:var(--accent);border-color:var(--accent);color:#fff;}
.stButton>button[kind="primary"]:hover{background:#1B444A;color:#fff;}
.stProgress>div>div>div>div{background-color:var(--accent);}
.stProgress>div>div>div{background-color:var(--line);}
div[role="radiogroup"]{gap:.35rem;flex-wrap:wrap;}
div[role="radiogroup"]>label{background:transparent;border:1px solid transparent;border-radius:999px;padding:.25rem .85rem;cursor:pointer;}
div[role="radiogroup"]>label:hover{border-color:var(--line);}
div[role="radiogroup"]>label:has(input:checked){background:var(--accent-soft);border-color:var(--accent-soft);}
textarea,input{border-radius:12px!important;}
section[data-testid="stSidebar"]{background:#F3EFE7;border-right:1px solid var(--line);}
@media (max-width:820px){.brand{font-size:1.9rem}.law-title{font-size:1.7rem}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------- state + storage layer
# All persistence goes through the functions in this block. To make data survive
# restarts, replace the bodies with reads/writes to SQLite, Supabase, etc.
def init_state():
    s = st.session_state
    defaults = dict(index=None, book_sig=None, just_indexed=False, nav="Home", step="Understand",
                    topic_choice=PLACEHOLDER, topic_custom="", guides={}, visited={}, explored=[],
                    vocab={}, reflections=[], speaking=[], quizzes=[], quiz=None, qid=0, asked={},
                    review_key=None, review_reveal=False, timer_start=None, explain_result={},
                    dev=False, k=6)
    for key, val in defaults.items():
        s.setdefault(key, val)


def save_word(entry: dict, topic: str):
    st.session_state.vocab[entry["word"].strip().lower()] = {
        "word": entry["word"].strip(), "meaning": entry.get("meaning", ""), "urdu": entry.get("urdu", ""),
        "synonyms": entry.get("synonyms", []), "topic": topic, "reviews": 0,
        "saved_at": datetime.now().isoformat(timespec="seconds")}


def remove_word(key: str):
    st.session_state.vocab.pop(key, None)
    if st.session_state.review_key == key:
        st.session_state.review_key = None


def add_reflection(topic: str, questions: list, text: str):
    st.session_state.reflections.append({"topic": topic, "questions": questions, "text": text,
                                         "at": datetime.now().isoformat(timespec="seconds")})


def add_speaking(topic: str, scores: dict, seconds: int):
    st.session_state.speaking.append({"topic": topic, "scores": scores, "seconds": seconds,
                                      "at": datetime.now().isoformat(timespec="seconds")})


def add_quiz(topic: str, qtype: str):
    st.session_state.quizzes.append({"topic": topic, "type": qtype,
                                     "at": datetime.now().isoformat(timespec="seconds")})


def mark_visited(topic: str, step: str):
    st.session_state.visited.setdefault(topic, set()).add(step)


def mark_explored(idx, topic: str):
    if topic in [l["title"] for l in idx.laws] and topic not in st.session_state.explored:
        st.session_state.explored.append(topic)


init_state()


# --------------------------------------------------------------- helpers
def go(page: str, step: str | None = None, review: bool = False):
    st.session_state.nav = page
    if step:
        st.session_state.step = step
    if review and st.session_state.vocab:
        st.session_state.review_key = next(iter(st.session_state.vocab))
        st.session_state.review_reveal = False


def uid(*parts) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:10]


def show_error(err: Exception):
    if isinstance(err, rc.AppError):
        title, msg, detail = err.title, err.message, err.detail
    else:
        title, msg, detail = "Something went wrong", "That didn't work. Please try again in a moment.", traceback.format_exc()
    st.error(f"**{title}**\n\n{msg}")
    if detail:
        with st.expander("Developer details"):
            st.code(detail)


def safe(fn, *args, spinner="Working on it…", **kwargs):
    """Run a backend call; show a friendly error instead of a traceback."""
    try:
        with st.spinner(spinner):
            return fn(*args, **kwargs)
    except Exception as err:  # noqa: BLE001
        show_error(err)
        return None


def section(icon: str, title: str):
    st.markdown(f"<div class='sec-title'>{icon} {esc(title)}</div>", unsafe_allow_html=True)


def sub(text: str):
    st.markdown(f"<div class='sub'>{esc(text)}</div>", unsafe_allow_html=True)


def lead(text: str):
    st.markdown(f"<div class='lead'>{esc(text)}</div>", unsafe_allow_html=True)


def empty_state(title: str, body: str, button: str | None = None, on_click=None, args=()):
    with st.container(border=True):
        st.markdown(f"<div class='sec-title'>{esc(title)}</div><div class='muted'>{esc(body)}</div>",
                    unsafe_allow_html=True)
        if button:
            st.button(button, on_click=on_click, args=args, key=f"empty_{uid(title)}")


def index_book(file):
    sig = (file.name, file.size)
    if st.session_state.book_sig == sig:
        return
    idx = safe(rc.build_index, file.getvalue(), file.name, spinner="Getting your book ready…")
    if idx is None:
        return
    for key in ("guides", "visited", "asked", "explain_result"):
        st.session_state[key] = {}
    st.session_state.explored, st.session_state.quiz = [], None
    st.session_state.index, st.session_state.book_sig = idx, sig
    st.session_state.just_indexed = True
    st.session_state.topic_choice, st.session_state.topic_custom = PLACEHOLDER, ""
    st.rerun()


def upload_box(key: str):
    st.markdown("<div class='muted' style='margin:.4rem 0'>Drop a PDF below, or browse your files.</div>",
                unsafe_allow_html=True)
    up = st.file_uploader("Upload your book", type=["pdf"], key=key, label_visibility="collapsed")
    if up is not None:
        index_book(up)


def require_book():
    idx = st.session_state.index
    if idx is None:
        empty_state("Add your book first", "Upload a PDF on the Home page to begin.", "Go to Home", go, ("Home",))
        st.stop()
    return idx


def current_topic(idx):
    custom = st.session_state.topic_custom.strip()
    if custom:
        return custom
    choice = st.session_state.topic_choice
    return None if choice == PLACEHOLDER else choice


def law_label(idx, topic):
    for l in idx.laws:
        if l["title"] == topic:
            return f"LAW {l['number']}"
    return "TOPIC"


def progress_of(topic):
    return len(st.session_state.visited.get(topic, set())) / len(STEPS)


# --------------------------------------------------------------- sidebar
def sidebar():
    idx = st.session_state.index
    with st.sidebar:
        st.markdown("<div class='serif' style='font-size:1.3rem'>📖 Human Nature Reader</div>", unsafe_allow_html=True)
        st.write("")
        if idx:
            st.markdown(f"**✓ Book ready**  \n{esc(idx.title)}", unsafe_allow_html=True)
            if idx.laws:
                st.caption(f"{len(idx.laws)} chapters detected · {idx.n_sections} searchable sections")
            else:
                st.caption(f"{idx.n_sections} searchable sections")
            with st.expander("Change book"):
                upload_box("side_upload")
        else:
            st.caption("No book yet. Upload one on the Home page.")
        st.write("")
        if not rc.ai_ready():
            st.warning("**Something is missing**  \nThe AI connection hasn't been configured yet. "
                       "If you're the app owner, check the API settings.")
        if st.session_state.dev:
            with st.expander("Developer details"):
                st.write({"llm": rc.GROQ_MODEL, "embeddings": rc.EMBED_MODEL_NAME, "chunks": idx.n_sections if idx else 0,
                          "pages": idx.n_pages if idx else 0, "k": st.session_state.k})


# ------------------------------------------------------------------ home
MODES = [
    ("📖", "Understand", "Explain laws and concepts in simple English.", ("Read", "Understand")),
    ("🔤", "Vocabulary", "Learn difficult words, meanings, synonyms and Urdu translations.", ("Read", "Words")),
    ("📜", "Story", "Understand the historical stories and examples.", ("Read", "Story")),
    ("💡", "Author's Message", "Understand what Greene is trying to communicate.", ("Read", "Message")),
    ("⭐", "Important Quotes", "Discover short, central quotations and understand them.", ("Read", "Quotes")),
    ("🎤", "Explain It", "Practice explaining what you learned in your own words.", ("Read", "Explain")),
    ("🧠", "Quiz", "Test your understanding.", ("Quiz", None)),
    ("🔄", "Revise", "Review previous concepts and vocabulary.", ("Vocabulary", "review")),
]


def page_home():
    idx = st.session_state.index
    if idx is None:
        with st.container(border=True):
            st.markdown("<div class='sec-title'>📚 Start Your Reading Journey</div>"
                        "<div class='muted'>Upload your book or document to begin.</div>", unsafe_allow_html=True)
            upload_box("main_upload")
            st.caption("Your document stays available for the current learning session.")
        return

    if st.session_state.just_indexed:
        with st.container(border=True):
            st.markdown("<div class='sec-title'>✓ Book Ready</div>", unsafe_allow_html=True)
            st.markdown(f"**{esc(idx.title)}**")
            parts = []
            if idx.laws:
                parts.append(f"{len(idx.laws)} chapters detected")
            parts.append(f"{idx.n_sections} searchable sections")
            st.markdown("<br>".join(esc(p) for p in parts), unsafe_allow_html=True)

            def _start():
                st.session_state.just_indexed = False
            st.button("Start Reading →", type="primary", on_click=_start)
        return

    n_laws = len(idx.laws)
    done = len([t for t in st.session_state.explored])
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("<div class='kicker'>Currently reading</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='law-title' style='font-size:1.9rem'>{esc(idx.title)}</div>", unsafe_allow_html=True)
        if idx.author:
            st.markdown(f"<span class='muted'>{esc(idx.author)}</span>", unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            if done and n_laws:
                st.markdown("**Your Progress**")
                st.markdown(f"{done} / {n_laws} Laws explored")
                st.progress(done / n_laws)
                label = "Continue Reading →"
            else:
                st.markdown("**Your Progress**")
                st.caption("Nothing explored yet.")
                label = "Start Your Reading Journey →"
            st.button(label, type="primary", on_click=go, args=("Read", "Understand"), key="continue")

    st.write("")
    st.markdown("<div class='sec-title'>How would you like to learn today?</div>", unsafe_allow_html=True)
    cols = st.columns(4, gap="medium")
    for i, (icon, title, desc, (page, step)) in enumerate(MODES):
        with cols[i % 4]:
            with st.container(border=True):
                st.markdown(f"<div style='font-size:1.5rem'>{icon}</div><div class='sub' style='margin-top:.3rem'>{esc(title)}</div>"
                            f"<div class='muted' style='min-height:3.2rem;font-size:.92rem'>{esc(desc)}</div>",
                            unsafe_allow_html=True)
                if step == "review":
                    st.button("Open", key=f"mode_{i}", on_click=go, args=(page, None, True))
                else:
                    st.button("Open", key=f"mode_{i}", on_click=go, args=(page, step))


# ------------------------------------------------------------------ read
def topic_picker(idx):
    if idx.laws:
        options = [PLACEHOLDER] + [l["title"] for l in idx.laws]
        st.selectbox("Law", options, key="topic_choice")
    with st.expander("Explore another idea from the book" if idx.laws else "What would you like to explore?",
                     expanded=not idx.laws):
        st.text_input("Type a chapter, law or idea", key="topic_custom", placeholder="e.g. envy, or The Law of Aggression")


def render_sources(guide_or_sources, hits=None):
    sources = guide_or_sources
    if not sources:
        return
    st.markdown("<div class='sub'>📚 Sources</div><div class='muted' style='font-size:.9rem'>Pages this explanation is based on</div>",
                unsafe_allow_html=True)
    for s in sources:
        with st.expander(f"Page {s['page']}"):
            st.markdown(f"<div class='muted' style='font-size:.92rem'>{esc(s['snippet'])}…</div>", unsafe_allow_html=True)
    if st.session_state.dev:
        with st.expander("Developer / Debug Details"):
            st.write([{"page": s["page"], "similarity": round(s["score"], 3)} for s in sources])


def page_read():
    idx = require_book()
    topic_picker(idx)
    topic = current_topic(idx)
    if not topic:
        empty_state("Pick where to begin", "Choose a law above, or type an idea you're curious about.")
        return

    guides = st.session_state.guides
    if topic not in guides:
        g = safe(rc.study_guide, idx, topic, st.session_state.k, spinner="Preparing your reading page…")
        if g is None:
            return
        guides[topic] = g
    guide = guides[topic]
    mark_explored(idx, topic)

    st.markdown(f"<div class='kicker'>{esc(law_label(idx, topic))}</div>"
                f"<div class='law-title'>{esc(topic.upper() if idx.laws else topic)}</div>", unsafe_allow_html=True)
    prog_slot = st.empty()
    st.radio("Step", STEPS, key="step", horizontal=True, format_func=STEP_LABEL.get, label_visibility="collapsed")
    step = st.session_state.step
    mark_visited(topic, step)
    prog_slot.progress(progress_of(topic), text=f"Progress · {len(st.session_state.visited[topic])} of {len(STEPS)} steps")
    st.write("")

    {"Understand": step_understand, "Story": step_story, "Message": step_message, "Words": step_words,
     "Quotes": step_quotes, "Reflect": step_reflect, "Explain": step_explain}[step](idx, topic, guide)

    st.write("")
    render_sources(guide["sources"])


def step_understand(idx, topic, g):
    with st.container(border=True):
        section("💡", "Core Idea")
        lead(g["core_idea"] or "No explanation came back. Try another law.")
    if g["real_life"]:
        with st.container(border=True):
            section("🌱", "See It in Real Life")
            for ex in g["real_life"][:2]:
                st.markdown(f"- {ex}")


def step_story(idx, topic, g):
    s = g["story"]
    with st.container(border=True):
        section("📜", "The Story")
        lead(s["summary"] or "No story was found in the excerpts for this topic.")
        if s["why_included"]:
            sub("Why did Greene include it?")
            st.write(s["why_included"])
        if s["demonstrates"]:
            sub("What does it demonstrate?")
            st.write(s["demonstrates"])


def step_message(idx, topic, g):
    m = g["message"]
    with st.container(border=True):
        section("💡", "What Greene Is Trying to Say")
        sub("What the book says")
        for b in m["book_says"]:
            st.markdown(f"- {b}")
        sub("Interpretation")
        st.caption("This is a reading of the text, not a quotation.")
        for b in m["interpretation"]:
            st.markdown(f"- {b}")
        if m["takeaway"]:
            st.markdown(f"<div class='muted' style='margin-top:.9rem;font-size:.9rem'>One-Line Takeaway</div>"
                        f"<div class='callout'>{esc(m['takeaway'])}</div>", unsafe_allow_html=True)


def step_words(idx, topic, g):
    section("🔤", "Words Worth Learning")
    if not g["vocabulary"]:
        st.caption("No useful words were found for this topic.")
    cols = st.columns(2, gap="medium")
    for i, v in enumerate(g["vocabulary"]):
        key = v["word"].strip().lower()
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f"<div class='bigword'>{esc(v['word'])}</div>"
                            f"<div>{esc(v.get('meaning', ''))}</div>"
                            f"<div class='urdu'>{esc(v.get('urdu', ''))}</div>", unsafe_allow_html=True)
                syn = v.get("synonyms") or []
                if syn:
                    st.markdown("".join(f"<span class='pill'>{esc(str(x))}</span>" for x in syn), unsafe_allow_html=True)
                if key in st.session_state.vocab:
                    st.button("✓ Saved", disabled=True, key=f"w_{uid(topic, key)}")
                else:
                    st.button("＋ Save to Vocabulary", key=f"w_{uid(topic, key)}", on_click=save_word, args=(v, topic))


def step_quotes(idx, topic, g):
    section("⭐", "Remember This")
    if not g["quotes"]:
        st.caption("No short, clear quotations were found in the excerpts for this topic.")
    for i, q in enumerate(g["quotes"]):
        with st.container(border=True):
            page = q.get("page")
            st.markdown(f"<div class='quote'>“{esc(q['quote'])}”</div>", unsafe_allow_html=True)
            if q.get("meaning"):
                st.markdown(f"**Meaning:** {q['meaning']}")
            if q.get("why_it_matters"):
                st.markdown(f"**Why it matters:** {q['why_it_matters']}")
            vocab = [v for v in (q.get("vocabulary") or []) if isinstance(v, dict) and v.get("word")]
            if vocab:
                st.markdown("**Vocabulary:** " + "; ".join(f"*{v['word']}* — {v.get('meaning', '')}" for v in vocab))
            if page:
                st.caption(f"Page {page}")


def step_reflect(idx, topic, g):
    qs = g["reflection_questions"][:3]
    with st.container(border=True):
        section("🪞", "Think About It")
        for q in qs:
            st.markdown(f"> {q}")
        text = st.text_area("Your reflection", key=f"refl_{uid(topic)}", height=140,
                            placeholder="Write a few sentences. Simple English is fine.")
        n = len([r for r in st.session_state.reflections if r["topic"] == topic])

        def _save():
            body = st.session_state.get(f"refl_{uid(topic)}", "").strip()
            if body:
                add_reflection(topic, qs, body)
                st.session_state[f"refl_{uid(topic)}"] = ""
                st.session_state["_flash"] = "Reflection saved."
        st.button("Save Reflection", on_click=_save, disabled=not text.strip(), type="primary")
        if st.session_state.pop("_flash", None):
            st.success("Reflection saved.")
        if n:
            st.caption(f"{n} saved for this topic.")


def countdown(remaining: int):
    components.html(
        f"""<div style="font-family:'Instrument Sans',sans-serif;font-size:2rem;color:#23545B"><span id="t">{remaining}</span>
        <span style="font-size:1rem;color:#6C675F">seconds left</span></div>
        <script>let s={remaining};const e=document.getElementById('t');
        const i=setInterval(()=>{{s--;e.textContent=Math.max(s,0);if(s<=0)clearInterval(i)}},1000)</script>""",
        height=60)


def step_explain(idx, topic, g):
    with st.container(border=True):
        section("🎤", "Explain It Yourself")
        st.markdown("> Explain this law to someone who has never read the book.")
        start = st.session_state.timer_start
        if start is None:
            st.caption("60-second practice")
            if st.button("Start", type="primary"):
                st.session_state.timer_start = time.time()
                st.rerun()
        else:
            elapsed = int(time.time() - start)
            countdown(max(0, 60 - elapsed))
        text = st.text_area("Your explanation", key=f"exp_{uid(topic)}", height=160,
                            placeholder="Type, or use your device's voice typing.")
        if st.button("Get feedback", disabled=not text.strip()):
            secs = int(time.time() - start) if start else None
            res = safe(rc.evaluate_explanation, idx, topic, text, secs, spinner="Reading your explanation…")
            if res:
                st.session_state.explain_result[topic] = res
                add_speaking(topic, res["scores"], secs or 0)
                st.session_state.timer_start = None
        res = st.session_state.explain_result.get(topic)
        if res:
            st.divider()
            cols = st.columns(5)
            for c, (name, val) in zip(cols, res["scores"].items()):
                c.metric(name, f"{val}/5")
            if res["strengths"]:
                st.markdown(f"**✓ What worked:** {res['strengths']}")
            if res["improve"]:
                st.markdown(f"**△ To improve:** {res['improve']}")
            if res["better_sentence"]:
                st.markdown(f"**💡 Try this sentence:** {res['better_sentence']}")


# ------------------------------------------------------------ vocabulary
def page_vocab():
    vocab = st.session_state.vocab
    st.markdown("<div class='law-title'>🔤 My Vocabulary</div>", unsafe_allow_html=True)
    if not vocab:
        empty_state("You haven't saved any words yet.",
                    "When you discover a useful word, save it here.", "Find words to learn", go, ("Read", "Words"))
        return

    key = st.session_state.review_key
    if key and key in vocab:
        w = vocab[key]
        with st.container(border=True):
            section("🔄", "Review")
            st.markdown(f"<div class='bigword'>{esc(w['word'])}</div>", unsafe_allow_html=True)
            if st.session_state.review_reveal:
                st.write(w["meaning"])
                st.markdown(f"<div class='urdu'>{esc(w['urdu'])}</div>", unsafe_allow_html=True)

                def _next():
                    vocab[key]["reviews"] += 1
                    keys = list(vocab)
                    st.session_state.review_key = keys[(keys.index(key) + 1) % len(keys)]
                    st.session_state.review_reveal = False

                def _done():
                    vocab[key]["reviews"] += 1
                    st.session_state.review_key = None
                c1, c2, _ = st.columns([1, 1, 3])
                c1.button("Next word", type="primary", on_click=_next)
                c2.button("Done", on_click=_done)
            else:
                st.caption("Try to remember the meaning first.")
                st.button("Show meaning", type="primary", on_click=lambda: st.session_state.update(review_reveal=True))
        st.write("")
    else:
        st.button("Start review", type="primary", on_click=go, args=("Vocabulary", None, True))

    q = st.text_input("Search", placeholder="Search vocabulary…", label_visibility="collapsed").strip().lower()
    items = [(k, v) for k, v in vocab.items()
             if not q or q in k or q in v["meaning"].lower() or q in v["urdu"]]
    if not items:
        st.caption("No saved words match your search.")
    cols = st.columns(3, gap="medium")
    for i, (k, v) in enumerate(items):
        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(f"<div class='bigword'>{esc(v['word'])}</div><div>{esc(v['meaning'])}</div>"
                            f"<div class='urdu'>اردو: {esc(v['urdu'])}</div>", unsafe_allow_html=True)
                a, b = st.columns(2)

                def _review(k=k):
                    st.session_state.review_key, st.session_state.review_reveal = k, False
                a.button("Review", key=f"rv_{uid(k)}", on_click=_review)
                b.button("Remove", key=f"rm_{uid(k)}", on_click=remove_word, args=(k,))


# ------------------------------------------------------------------ quiz
def page_quiz():
    idx = require_book()
    st.markdown("<div class='law-title'>🧠 Test Yourself</div>", unsafe_allow_html=True)
    explored = st.session_state.explored + [t for t in st.session_state.guides if t not in st.session_state.explored]
    if not explored:
        empty_state("Finish a chapter to unlock your first quiz.",
                    "Open a law on the Read page, then come back to test yourself.", "Start reading", go, ("Read", "Understand"))
        return
    topic = st.selectbox("Topic", explored, key="quiz_topic")
    quiz, qid = st.session_state.quiz, st.session_state.qid

    def _new():
        asked = st.session_state.asked.setdefault(topic, [])
        qtype = rc.QUIZ_TYPES[len(st.session_state.quizzes) % len(rc.QUIZ_TYPES)]
        q = safe(rc.make_quiz_question, idx, topic, qtype, asked, st.session_state.k, spinner="Writing a question…")
        if q:
            asked.append(q["question"])
            q["topic"], q["result"] = topic, None
            st.session_state.quiz, st.session_state.qid = q, st.session_state.qid + 1

    if not quiz or quiz["topic"] != topic:
        st.button("Start a question", type="primary", on_click=_new)
        return

    with st.container(border=True):
        st.markdown(f"<span class='pill'>{esc(quiz['type'])}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='lead'>{esc(quiz['question'])}</div>", unsafe_allow_html=True)
        if quiz["hint"] and not quiz["result"]:
            with st.expander("Need a hint?"):
                st.write(quiz["hint"])
        ans = st.text_area("Your answer", key=f"qa_{qid}", height=120, disabled=bool(quiz["result"]))
        if not quiz["result"]:
            if st.button("Check my answer", type="primary", disabled=not ans.strip()):
                r = safe(rc.grade_quiz_answer, idx, topic, quiz, ans, st.session_state.k, spinner="Checking…")
                if r:
                    quiz["result"] = r
                    add_quiz(topic, quiz["type"])
                    st.rerun()
        else:
            r = quiz["result"]
            st.divider()
            if r["understood"]:
                st.markdown("**✓ What you understood**")
                for x in r["understood"]:
                    st.markdown(f"- {x}")
            if r["missed"]:
                st.markdown("**△ What you missed**")
                for x in r["missed"]:
                    st.markdown(f"- {x}")
            if r["correct_understanding"]:
                st.markdown(f"**💡 Correct understanding**\n\n{r['correct_understanding']}")
            if r["remember"]:
                st.markdown(f"<div class='callout'><b>Remember:</b> {esc(r['remember'])}</div>", unsafe_allow_html=True)
            st.write("")
            st.button("Next question", type="primary", on_click=_new)


# -------------------------------------------------------------- progress
def page_progress():
    idx = st.session_state.index
    s = st.session_state
    st.markdown("<div class='law-title'>📊 My Progress</div>", unsafe_allow_html=True)
    stats = [len(s.explored), len(s.vocab), len(s.quizzes), len(s.reflections), len(s.speaking)]
    if not any(stats):
        empty_state("Start reading your first chapter to see your progress.",
                    "Your numbers appear here as you learn.", "Start reading", go, ("Read", "Understand"))
        return
    total = len(idx.laws) if idx else 0
    if total:
        st.progress(min(1.0, stats[0] / total), text=f"{stats[0]} / {total} Laws explored")
    cols = st.columns(5)
    labels = ["Laws explored", "Vocabulary saved", "Quizzes completed", "Reflections saved", "Speaking practices"]
    for c, label, val in zip(cols, labels, stats):
        c.metric(label, f"{val} / {total}" if label == "Laws explored" and total else val)
    if s.reflections:
        st.write("")
        with st.expander("Your reflections"):
            for r in reversed(s.reflections):
                st.markdown(f"**{r['topic']}** · {r['at'][:10]}")
                st.write(r["text"])
                st.divider()


# -------------------------------------------------------------- settings
def page_settings():
    st.markdown("<div class='law-title'>Settings</div>", unsafe_allow_html=True)
    with st.container(border=True):
        st.toggle("Show developer details", key="dev", help="Adds similarity scores and model information.")
        st.slider("Passages used per explanation", 3, 10, key="k", help="More passages give wider context but slower answers.")
    with st.container(border=True):
        st.markdown("**Reset my session**")
        st.caption("Clears saved words, reflections, quizzes and progress. Your book stays loaded.")

        def _reset():
            for key in ("guides", "visited", "asked", "explain_result", "vocab"):
                st.session_state[key] = {}
            for key in ("explored", "reflections", "speaking", "quizzes"):
                st.session_state[key] = []
            st.session_state.quiz, st.session_state.review_key = None, None
        st.button("Reset", on_click=_reset)


# ------------------------------------------------------------------ main
sidebar()
st.markdown("<div class='brand'>📖 Human Nature Reader</div>"
            "<div class='tagline'>Understand • Learn • Reflect • Remember</div>", unsafe_allow_html=True)
st.radio("Navigate", NAV, key="nav", horizontal=True, label_visibility="collapsed")
st.write("")
{"Home": page_home, "Read": page_read, "Vocabulary": page_vocab, "Quiz": page_quiz,
 "Progress": page_progress, "Settings": page_settings}[st.session_state.nav]()
