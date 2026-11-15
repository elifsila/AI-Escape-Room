"""AI Escape Room — Version 1 (prompt-only Game Master).

Run:  streamlit run v1/app.py
"""
import os

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

from prompts import ESCAPE_TOKEN, INTRO, SYSTEM_PROMPT

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

st.set_page_config(page_title="AI Escape Room · V1", page_icon="📚")


@st.cache_resource
def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        st.error("GEMINI_API_KEY is missing. Copy .env.example to .env and add your key.")
        st.stop()
    # 60 s timeout so the UI shows an error instead of spinning forever
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60_000))


def reset_game():
    st.session_state.messages = []  # [{"role": "user"|"assistant", "content": str}]
    st.session_state.escaped = False


def ask_game_master(history):
    """Send the full conversation to Gemini. The model is the only 'memory' of the game."""
    contents = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["content"])],
        )
        for m in history
    ]
    response = get_client().models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.8),
    )
    return response.text or "(The Game Master is silent.)"


if "messages" not in st.session_state:
    reset_game()

# ---------- sidebar ----------
with st.sidebar:
    st.header("📚 The Silent Library")
    st.caption("Version 1 — prompt-only Game Master")
    st.markdown(
        "**How to play**\n"
        "- Describe what you do in plain English\n"
        "- Examine objects, take items, try codes\n"
        "- Goal: open the door and escape"
    )
    if st.button("🔄 Restart game", use_container_width=True):
        reset_game()
        st.rerun()

# ---------- main ----------
st.title("AI Escape Room")
st.markdown(INTRO)

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if st.session_state.pop("celebrate", False):
    st.balloons()
if st.session_state.escaped:
    st.success("🎉 You escaped! Press **Restart game** to play again.")
elif prompt := st.chat_input("What do you do?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("The Game Master is thinking..."):
            try:
                reply = ask_game_master(st.session_state.messages)
            except Exception as e:  # network / quota errors
                reply = f"⚠️ LLM error: {e}"
        # V1 trusts the model to decide when the game is won.
        if ESCAPE_TOKEN in reply:
            st.session_state.escaped = True
            reply = reply.replace(ESCAPE_TOKEN, "").strip()
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    if st.session_state.escaped:
        st.session_state.celebrate = True
        st.rerun()
