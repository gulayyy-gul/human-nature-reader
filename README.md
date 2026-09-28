# 📖 Human Nature Reader

A reading companion for *The Laws of Human Nature* by Robert Greene.
Read → Understand → Learn → Reflect → Explain → Remember → Review.

## Architecture

```
            rag_core.py
           /           \
 streamlit_app.py   gradio_app.py
   (deployment)        (testing)
```

All retrieval, prompting and error handling lives in `rag_core.py`. The two UIs only call its functions.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # add your GROQ_API_KEY
streamlit run streamlit_app.py
# or
python gradio_app.py
```

## Deploy on Streamlit Cloud

Add `GROQ_API_KEY` under **App settings → Secrets**:

```toml
GROQ_API_KEY = "your_key"
```

## Where your data lives

Saved words, reflections, quiz counts and progress use `st.session_state` and disappear when the session ends.
All writes go through the small "state + storage layer" block near the top of `streamlit_app.py`
(`save_word`, `add_reflection`, `add_quiz`, …). Replace those bodies with SQLite or Supabase calls to persist data.

## Notes

- Page numbers are PDF page numbers, which can differ from the printed page numbers in the book.
- Law detection looks for headings like `THE LAW OF IRRATIONALITY` on their own line. If fewer than three are found, the
  app falls back to a free-text topic box.
- Turn on **Settings → Show developer details** to see similarity scores and model names.
