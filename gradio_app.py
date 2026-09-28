"""Human Nature Reader — Gradio UI (testing). Uses the same backend as Streamlit: rag_core.py"""
import gradio as gr

import rag_core as rc

THEME = gr.themes.Base(primary_hue="teal", neutral_hue="stone", font=[gr.themes.GoogleFont("Instrument Sans"), "sans-serif"],
                       font_mono=["ui-monospace", "monospace"]).set(body_background_fill="#FAF7F2",
                                                                   block_background_fill="#FFFDF9",
                                                                   block_border_width="1px", block_shadow="none")
CSS = ".gradio-container h1,.gradio-container h2,.gradio-container h3{font-family:'Newsreader',Georgia,serif;font-weight:600}"


def fresh():
    return {"index": None, "guides": {}, "vocab": {}, "quizzes": 0, "reflections": [], "quiz": None, "asked": {}, "explored": []}


def _err(e: Exception) -> str:
    if isinstance(e, rc.AppError):
        return f"**{e.title}**\n\n{e.message}"
    return "**Something went wrong**\n\nPlease try again."


def load_book(file, st):
    if file is None:
        return st, "Upload a PDF to begin.", gr.update(choices=[])
    try:
        with open(file, "rb") as f:
            idx = rc.build_index(f.read(), file.split("/")[-1])
    except Exception as e:  # noqa: BLE001
        return st, _err(e), gr.update(choices=[])
    st = fresh() | {"index": idx}
    laws = [l["title"] for l in idx.laws]
    info = f"### ✓ Book Ready\n**{idx.title}**\n\n" + (f"{len(laws)} chapters detected\n\n" if laws else "") + f"{idx.n_sections} searchable sections"
    return st, info, gr.update(choices=laws, value=laws[0] if laws else None)


def guide_md(g: dict, topic: str) -> str:
    out = [f"## {topic}", "### 💡 Core Idea", g["core_idea"]]
    s = g["story"]
    out += ["### 📜 The Story", s["summary"], f"**Why did Greene include it?** {s['why_included']}", f"**What does it demonstrate?** {s['demonstrates']}"]
    m = g["message"]
    out += ["### 💡 What Greene Is Trying to Say", "**What the book says**"] + [f"- {b}" for b in m["book_says"]]
    out += ["**Interpretation** *(a reading, not a quotation)*"] + [f"- {b}" for b in m["interpretation"]]
    out += [f"> **One-Line Takeaway:** {m['takeaway']}"]
    out += ["### 🔤 Words Worth Learning", "| Word | Simple meaning | Urdu | Synonyms |", "|---|---|---|---|"]
    out += [f"| {v['word']} | {v.get('meaning','')} | {v.get('urdu','')} | {', '.join(map(str, v.get('synonyms') or []))} |" for v in g["vocabulary"]]
    out += ["### ⭐ Remember This"]
    for q in g["quotes"]:
        out += [f"> “{q['quote']}”  \n> *(page {q.get('page','?')})*", f"**Meaning:** {q.get('meaning','')}  \n**Why it matters:** {q.get('why_it_matters','')}"]
    out += ["### 🌱 See It in Real Life"] + [f"- {x}" for x in g["real_life"]]
    out += ["### 🪞 Think About It"] + [f"- {q}" for q in g["reflection_questions"]]
    out += ["### 📚 Sources", "Pages: " + ", ".join(str(s["page"]) for s in g["sources"])]
    return "\n\n".join(out)


def read_law(topic, st):
    if not st["index"]:
        return st, "Upload a book first.", gr.update()
    topic = (topic or "").strip()
    if not topic:
        return st, "Choose a law or type an idea.", gr.update()
    try:
        if topic not in st["guides"]:
            st["guides"][topic] = rc.study_guide(st["index"], topic)
    except Exception as e:  # noqa: BLE001
        return st, _err(e), gr.update()
    if topic in [l["title"] for l in st["index"].laws] and topic not in st["explored"]:
        st["explored"].append(topic)
    g = st["guides"][topic]
    words = [v["word"] for v in g["vocabulary"]]
    return st, guide_md(g, topic), gr.update(choices=words, value=[])


def save_words(words, topic, st):
    g = st["guides"].get((topic or "").strip())
    for v in (g["vocabulary"] if g else []):
        if v["word"] in (words or []):
            st["vocab"][v["word"].lower()] = v
    return st, vocab_md(st)


def vocab_md(st):
    if not st["vocab"]:
        return "You haven't saved any words yet. When you discover a useful word, save it here."
    return "\n\n".join(f"**{v['word']}** — {v.get('meaning','')}  \nاردو: {v.get('urdu','')}" for v in st["vocab"].values())


def remove_words(words, st):
    for w in words or []:
        st["vocab"].pop(w.lower(), None)
    return st, vocab_md(st), gr.update(choices=[v["word"] for v in st["vocab"].values()], value=[])


def ask(question, st):
    if not st["index"] or not question.strip():
        return "Upload a book and type a question."
    try:
        r = rc.ask_book(st["index"], question)
    except Exception as e:  # noqa: BLE001
        return _err(e)
    return r["answer"] + "\n\n**📚 Sources:** " + ", ".join(f"Page {s['page']}" for s in r["sources"])


def new_question(topic, st):
    topic = (topic or "").strip()
    if not st["index"] or topic not in st["guides"]:
        return st, "Open a law on the Read tab first — then the quiz unlocks.", ""
    asked = st["asked"].setdefault(topic, [])
    try:
        q = rc.make_quiz_question(st["index"], topic, rc.QUIZ_TYPES[st["quizzes"] % len(rc.QUIZ_TYPES)], asked)
    except Exception as e:  # noqa: BLE001
        return st, _err(e), ""
    asked.append(q["question"])
    st["quiz"] = q | {"topic": topic}
    return st, f"**{q['type']}** — {q['question']}\n\n*Hint: {q['hint']}*", ""


def check_answer(answer, st):
    q = st["quiz"]
    if not q or not answer.strip():
        return st, "Get a question and type your answer."
    try:
        r = rc.grade_quiz_answer(st["index"], q["topic"], q, answer)
    except Exception as e:  # noqa: BLE001
        return st, _err(e)
    st["quizzes"] += 1
    md = ["**✓ What you understood**"] + [f"- {x}" for x in r["understood"]] + ["**△ What you missed**"] + [f"- {x}" for x in r["missed"]]
    md += [f"**💡 Correct understanding**\n\n{r['correct_understanding']}", f"**Remember:** {r['remember']}"]
    return st, "\n\n".join(md)


def progress(st):
    n = len(st["index"].laws) if st["index"] else 0
    if not (st["explored"] or st["vocab"] or st["quizzes"] or st["reflections"]):
        return "Start reading your first chapter to see your progress."
    return (f"**Laws explored** {len(st['explored'])}{f' / {n}' if n else ''}\n\n**Vocabulary saved** {len(st['vocab'])}\n\n"
            f"**Quizzes completed** {st['quizzes']}\n\n**Reflections saved** {len(st['reflections'])}")


def save_reflection(text, topic, st):
    if text.strip():
        st["reflections"].append({"topic": topic, "text": text.strip()})
    return st, ""


with gr.Blocks(theme=THEME, css=CSS, title="Human Nature Reader") as demo:
    state = gr.State(fresh())
    gr.Markdown("# 📖 Human Nature Reader\nUnderstand • Learn • Reflect • Remember")
    with gr.Tab("Home"):
        pdf = gr.File(label="📚 Drop your PDF here", file_types=[".pdf"], type="filepath")
        status = gr.Markdown("Upload your book or document to begin.")
    with gr.Tab("Read"):
        law = gr.Dropdown(label="Law", choices=[], allow_custom_value=True, info="Choose a law, or type any idea from the book.")
        go_btn = gr.Button("Open reading page", variant="primary")
        page = gr.Markdown()
        words = gr.CheckboxGroup(label="Words from this page", choices=[])
        save_btn = gr.Button("＋ Save to Vocabulary")
        refl = gr.Textbox(label="Your reflection", lines=3)
        refl_btn = gr.Button("Save Reflection")
    with gr.Tab("Ask"):
        q = gr.Textbox(label="Ask about the book")
        a = gr.Markdown()
        gr.Button("Ask", variant="primary").click(ask, [q, state], a)
    with gr.Tab("Vocabulary"):
        vocab = gr.Markdown(vocab_md(fresh()))
        rm = gr.CheckboxGroup(label="Remove words", choices=[])
        rm_btn = gr.Button("Remove selected")
    with gr.Tab("Quiz"):
        qbtn = gr.Button("New question", variant="primary")
        qtxt = gr.Markdown("Open a law on the Read tab first — then the quiz unlocks.")
        ans = gr.Textbox(label="Your answer", lines=3)
        chk = gr.Button("Check my answer")
        fb = gr.Markdown()
    with gr.Tab("Progress"):
        prog = gr.Markdown("Start reading your first chapter to see your progress.")
        gr.Button("Refresh").click(progress, state, prog)

    pdf.change(load_book, [pdf, state], [state, status, law])
    go_btn.click(read_law, [law, state], [state, page, words])
    save_btn.click(save_words, [words, law, state], [state, vocab]).then(
        lambda st: gr.update(choices=[v["word"] for v in st["vocab"].values()]), state, rm)
    refl_btn.click(save_reflection, [refl, law, state], [state, refl])
    rm_btn.click(remove_words, [rm, state], [state, vocab, rm])
    qbtn.click(new_question, [law, state], [state, qtxt, ans])
    chk.click(check_answer, [ans, state], [state, fb])

if __name__ == "__main__":
    demo.launch()
