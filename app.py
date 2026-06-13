import os
import requests
import streamlit as st

# Works locally (via .env) and on Streamlit Cloud (via secrets.toml)
API_URL = st.secrets.get("API_URL", os.getenv("API_URL", "http://localhost:8000"))

st.set_page_config(page_title="AI Chat", page_icon="💬", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { min-width: 260px; max-width: 260px; }
    .universal-info {
        background: linear-gradient(135deg, #f0f4ff, #e8f0fe);
        border-left: 4px solid #4f80ff;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 0.875rem;
        margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def api_get(path: str):
    try:
        r = requests.get(f"{API_URL}{path}", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the backend. Make sure `uvicorn main:app` is running.")
        return None
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def api_post(path: str, payload: dict):
    try:
        r = requests.post(f"{API_URL}{path}", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the backend.")
        return None
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


def api_delete(path: str):
    try:
        r = requests.delete(f"{API_URL}{path}", timeout=10)
        r.raise_for_status()
        return True
    except Exception as exc:
        st.error(f"Delete error: {exc}")
        return False


# ── session state defaults ──────────────────────────────────────────────────────

if "selected_thread_id" not in st.session_state:
    st.session_state.selected_thread_id = 1
if "new_thread_name" not in st.session_state:
    st.session_state.new_thread_name = ""


# ── sidebar ─────────────────────────────────────────────────────────────────────

threads = api_get("/threads") or []

with st.sidebar:
    st.title("💬 Threads")

    for t in threads:
        is_universal = t["id"] == 1
        icon = "🌐" if is_universal else "💬"
        label = f"{icon}  {t['name']}"
        selected = st.session_state.selected_thread_id == t["id"]

        col_btn, col_del = st.columns([5, 1])
        with col_btn:
            if st.button(
                label,
                key=f"sel_{t['id']}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state.selected_thread_id = t["id"]
                st.rerun()
        with col_del:
            if not is_universal:
                if st.button("✕", key=f"del_{t['id']}", help="Delete thread"):
                    if api_delete(f"/threads/{t['id']}"):
                        if st.session_state.selected_thread_id == t["id"]:
                            st.session_state.selected_thread_id = 1
                        st.rerun()

    st.divider()

    new_name = st.text_input("New thread name", key="new_thread_input", placeholder="e.g. Work, Ideas…")
    if st.button("＋ Create Thread", use_container_width=True):
        if new_name.strip():
            created = api_post("/threads", {"name": new_name.strip()})
            if created:
                st.session_state.selected_thread_id = created["id"]
                st.rerun()
        else:
            st.warning("Enter a thread name.")

    st.divider()
    st.caption(
        "🌐 **Universal Memory** (Thread 1) is automatically injected as background context "
        "into every other thread, so the AI always remembers it."
    )


# ── main chat area ──────────────────────────────────────────────────────────────

current_id = st.session_state.selected_thread_id
current_thread = next((t for t in threads if t["id"] == current_id), None)

if not threads:
    st.info("Could not load threads. Is the backend running?")
elif not current_thread:
    st.info("Select or create a thread in the sidebar.")
else:
    is_universal = current_id == 1

    if is_universal:
        st.header("🌐 Universal Memory Thread")
        st.markdown(
            '<div class="universal-info">'
            "Everything you discuss here is automatically remembered and injected as context "
            "into <strong>all other threads</strong>. Use it to store your name, preferences, "
            "ongoing projects, or any info you want the AI to always know."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.header(f"💬 {current_thread['name']}")
        st.caption("The AI has access to Universal Memory (Thread 1) as background context in this thread.")

    # Load and display message history
    messages = api_get(f"/threads/{current_id}/messages") or []

    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Type a message…"):
        # Show user bubble immediately (optimistic)
        with st.chat_message("user"):
            st.markdown(prompt)

        # Stream/wait for AI response
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                result = api_post(f"/threads/{current_id}/messages", {"content": prompt})
            if result:
                st.markdown(result["content"])

        st.rerun()
