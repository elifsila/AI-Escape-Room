"""AI Escape Room — Version 2 (reliable: Python decides, LLM narrates).

Run:  streamlit run v2/app.py
"""
import json
import os

import streamlit as st
from dotenv import load_dotenv

from engine import apply_action
from narrator import narrate
from parser import parse
from state import load_config, new_state, public_view

load_dotenv()
OFFLINE = os.getenv("OFFLINE_MODE", "0") == "1"
CONFIG = load_config()

st.set_page_config(page_title="AI Escape Room · V2", page_icon="🔐")


@st.cache_resource
def get_llm():
    if OFFLINE:
        return None
    if not os.getenv("GEMINI_API_KEY"):
        st.error("GEMINI_API_KEY is missing. Copy .env.example to .env and add your key "
                 "(or set OFFLINE_MODE=1 to play without an LLM).")
        st.stop()
    from llm import GeminiLLM
    return GeminiLLM()


def reset_game():
    st.session_state.state = new_state(CONFIG)
    st.session_state.messages = []
    st.session_state.last_action = None


def play_turn(user_text):
    llm = get_llm()
    action = parse(user_text, CONFIG, llm)                          # 1. understand
    result = apply_action(st.session_state.state, action, CONFIG, user_text)  # 2. validate + update
    text, used_llm = narrate(user_text, result, st.session_state.state, CONFIG, llm)  # 3. describe
    st.session_state.last_action = {"parsed": action, "event": result.event, "ok": result.ok,
                                    "facts": result.facts, "narrated_by_llm": used_llm}
    return text


if "state" not in st.session_state:
    reset_game()
state = st.session_state.state

# ---------- sidebar: the structured state ----------
with st.sidebar:
    st.header(f"🔐 {CONFIG['title']}")
    st.caption("Version 2 — Python game engine + LLM narrator" + (" · OFFLINE" if OFFLINE else ""))

    st.subheader("🎒 Inventory")
    if state["inventory"]:
        for i in state["inventory"]:
            st.markdown(f"- {CONFIG['items'][i]['name']}")
    else:
        st.caption("empty")

    total = len(CONFIG["puzzles"])
    st.subheader(f"🧩 Puzzles {len(state['solved'])}/{total}")
    st.progress(len(state["solved"]) / total)
    for pid, p in CONFIG["puzzles"].items():
        st.markdown(("✅ " if pid in state["solved"] else "⬜ ") + p["description"])

    st.markdown("**Commands:** examine · take · use X on Y · open · enter code · inventory · hint")
    if st.button("🔄 Restart game", use_container_width=True):
        reset_game()
        st.rerun()

    with st.expander("🛠 Debug: game state"):
        st.caption("Shown for the demo/report. The LLM can't see or change this.")
        st.json(public_view(state))
        if st.session_state.last_action:
            st.markdown("**Last turn**")
            st.json(st.session_state.last_action)

# ---------- main ----------
st.title("AI Escape Room")
st.markdown(CONFIG["intro"])

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if st.session_state.pop("celebrate", False):
    st.balloons()
if state["escaped"]:
    st.success(f"🎉 You escaped in {state['turn']} turns using {state['hints_used']} hint(s)! "
               "Press **Restart game** to play again.")
elif prompt := st.chat_input("What do you do?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("..."):
            reply = play_turn(prompt)
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.celebrate = state["escaped"]
    st.rerun()  # refresh the sidebar with the new state
