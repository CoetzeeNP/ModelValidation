import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
from google import genai
from google.genai import types
import html
import re

SHEET_NAME = "Gemini Logs"
MODEL_MAPPING = {
    "gemini-3-pro-preview": "gemini-3-pro-preview"
}

AUTHORIZED_STUDENT_IDS = ["12345", "67890", "24680", "13579", "99999", ""]

header_container = st.container()
with header_container:
    st.image("combined_logo.jpg", width="stretch")

st.title("Generative Afrikaans Assistant")

st.set_page_config(layout="wide")

# --- Firebase Connection ---
@st.cache_resource
def get_firebase_connection():
    try:
        if not firebase_admin._apps:
            if "firebase_service_account" not in st.secrets:
                st.error("Firebase credentials missing in secrets!")
                return None

            cred_info = dict(st.secrets["firebase_service_account"])
            cred_info["private_key"] = cred_info["private_key"].replace("\\n", "\n")
            db_url = st.secrets["firebase_db_url"].strip()

            cred = credentials.Certificate(cred_info)
            firebase_admin.initialize_app(cred, {'databaseURL': db_url})
        return db.reference("/")
    except Exception as e:
        st.error(f"Firebase Init Error: {e}")
        return None


db_ref = get_firebase_connection()


# --- Logging Function ---
def save_to_firebase(user_id, model_name, prompt_, full_response, interaction_type):
    if db_ref:
        try:
            clean_user_id = str(user_id).replace(".", "_")
            timestamp_key = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

            db_ref.child("logs").child(clean_user_id).child(timestamp_key).set({
                "model_name": model_name,
                "prompt": prompt_,
                "response": full_response,
                "interaction_type": interaction_type,
                "full_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            return True
        except Exception as e:
            st.error(f"Firebase Logging error: {e}")
            return False


# --- AI Response Function ---
def get_ai_response(model_selection, chat_history, system_instruction_text):
    try:
        client = genai.Client(api_key=st.secrets["api_keys"]["google"])
        api_contents = []
        for m in chat_history:
            role = "user" if m["role"] == "user" else "model"
            api_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))

        response = client.models.generate_content(
            model=MODEL_MAPPING.get(model_selection, "gemini-2.0-flash"),
            contents=api_contents,
            config=types.GenerateContentConfig(
                temperature=0.7,
                system_instruction=system_instruction_text
            )
        )
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"


# --- Session State Management ---
if "messages" not in st.session_state: st.session_state["messages"] = []
if "feedback_pending" not in st.session_state: st.session_state["feedback_pending"] = False
if "authenticated" not in st.session_state: st.session_state["authenticated"] = False
if "current_user" not in st.session_state: st.session_state["current_user"] = None


# --- Feedback Handler ---
def handle_feedback(understood: bool):
    interaction = "UNDERSTOOD_FEEDBACK" if understood else "CLARIFICATION_REQUESTED"
    last_ai_reply = st.session_state["messages"][-1]["content"]

    save_to_firebase(st.session_state["current_user"], selected_label, "Feedback Button", last_ai_reply, interaction)

    if not understood:
        clarification_prompt = f"I don't understand the previous explanation. Please break it down further."
        st.session_state["messages"].append({"role": "user", "content": clarification_prompt})

        with st.spinner("Besig om verder te verduidelik..."):
            ai_reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
            st.session_state["messages"].append({"role": "assistant", "content": ai_reply})
            save_to_firebase(st.session_state["current_user"], selected_label, clarification_prompt, ai_reply,
                             "CLARIFICATION_RESPONSE")

        st.session_state["feedback_pending"] = True
    else:
        st.session_state["feedback_pending"] = False

# --- Sidebar ---
with st.sidebar:
    st.header("Menu")
    if not st.session_state["authenticated"]:
        u_id = st.text_input("Enter Student ID", type="password")
        if st.button("Login", use_container_width=True):
            if u_id in AUTHORIZED_STUDENT_IDS:
                st.session_state["authenticated"] = True
                st.session_state["current_user"] = u_id if u_id != "" else "Guest"
                st.rerun()
            else:
                st.error("Invalid Student ID")
    else:
        st.write(f"**User:** {st.session_state['current_user']}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()
        with col2:
            st.link_button("Feedback", "https://forms.office.com/your-link", use_container_width=True)

        st.markdown("---")
        selected_label = st.selectbox("AI Model", list(MODEL_MAPPING.keys()))
        system_instruction_input = st.text_area("System Message",
                                                "You are an Afrikaans tutor. Use STOMPI rules to explain sentence structure.")

# --- Main Chat Area ---
if not st.session_state["authenticated"]:
    st.warning("Please login with an authorized Student ID in the sidebar.")
else:
    # Visual aid for STOMPI (Instructional Diagram)
    with st.expander("Help met STOMPI (Sentence Structure Guide)"):
        st.write("Onthou die volgorde:")

    # 1. Display Chat History
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 2. Input Logic
    input_placeholder = "Waiting for feedback..." if st.session_state["feedback_pending"] else "Vra 'n vraag..."
    prompt = st.chat_input(input_placeholder, disabled=st.session_state["feedback_pending"])

    if prompt:
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Besig om te dink..."):
                reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
                st.markdown(reply)

        save_to_firebase(st.session_state["current_user"], selected_label, prompt, reply, "INITIAL_QUERY")
        st.session_state["messages"].append({"role": "assistant", "content": reply})
        st.session_state["feedback_pending"] = True
        st.rerun()

    # 3. Feedback UI
    if st.session_state["feedback_pending"]:
        st.info("Het jy die verduideliking verstaan? (Did you understand?)")
        c1, c2 = st.columns(2)
        with c1:
            st.button("✅ Ek verstaan!", on_click=handle_feedback, args=(True,), use_container_width=True)
        with c2:
            st.button("❌ Ek het hulp nodig", on_click=handle_feedback, args=(False,), use_container_width=True)