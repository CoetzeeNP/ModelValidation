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

st.set_page_config(layout="wide", page_title="Generative Afrikaans Assistant")


# --- Firebase Connection ---
@st.cache_resource
def get_firebase_connection():
    try:
        if not firebase_admin._apps:
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


# --- Helper Functions ---
def save_to_firebase(user_id, model_name, prompt_, full_response, interaction_type):
    if db_ref:
        try:
            clean_user_id = str(user_id).replace(".", "_")
            timestamp_key = datetime.now().strftime("%Y%m%d_%H%M%S")
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


def get_ai_response(model_selection, chat_history, system_instruction_text):
    try:
        client = genai.Client(api_key=st.secrets["api_keys"]["google"])
        api_contents = []
        for m in chat_history:
            role = "user" if m["role"] == "user" else "model"
            api_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))

        response = client.models.generate_content(
            model=MODEL_MAPPING[model_selection],
            contents=api_contents,
            config=types.GenerateContentConfig(
                temperature=0.7,
                system_instruction=system_instruction_text
            )
        )
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"


def handle_feedback(understood: bool):
    interaction = "UNDERSTOOD" if understood else "NOT_UNDERSTOOD"
    last_user_prompt = st.session_state["messages"][-2]["content"] if len(st.session_state["messages"]) >= 2 else "N/A"
    last_ai_reply = st.session_state["messages"][-1]["content"]

    save_to_firebase(st.session_state["current_user"], selected_label, last_user_prompt, last_ai_reply, interaction)

    if not understood:
        clarification_prompt = f"I don't understand that. Please explain the Afrikaans grammar or sentence structure again, but simpler."
        st.session_state["messages"].append({"role": "user", "content": clarification_prompt})
        ai_reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
        st.session_state["messages"].append({"role": "assistant", "content": ai_reply})
        save_to_firebase(st.session_state["current_user"], selected_label, clarification_prompt, ai_reply,
                         "CLARIFICATION_REPLY")

    st.session_state["feedback_pending"] = False


# --- Session State Initialization ---
if "messages" not in st.session_state: st.session_state["messages"] = []
if "feedback_pending" not in st.session_state: st.session_state["feedback_pending"] = False
if "authenticated" not in st.session_state: st.session_state["authenticated"] = False
if "current_user" not in st.session_state: st.session_state["current_user"] = None

# --- UI Header ---
header_container = st.container()
with header_container:
    # Use st.columns if you want to center or resize the logo specifically
    st.title("Generative Afrikaans Assistant 🇿🇦")
    st.markdown("Master Afrikaans grammar and sentence structure with AI.")

# --- Sidebar ---
with st.sidebar:
    st.header("Menu")
    if not st.session_state["authenticated"]:
        u_id = st.text_input("Enter Student ID", type="password")
        if st.button("Login", use_container_width=True):
            if u_id in AUTHORIZED_STUDENT_IDS:
                st.session_state["authenticated"] = True
                st.session_state["current_user"] = u_id
                st.rerun()
            else:
                st.error("Invalid ID")
    else:
        st.write(f"**Logged in as:** `{st.session_state['current_user']}`")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Logout"):
                st.session_state.clear()
                st.rerun()
        with col2:
            st.link_button("Feedback Form", "https://forms.office.com/your-link")

        st.markdown("---")
        selected_label = st.selectbox("AI Model", list(MODEL_MAPPING.keys()))
        system_instruction_input = st.text_area("Tutor Instructions",
                                                "You are an Afrikaans tutor. Always emphasize the STOMPI rule. Provide English translations for complex Afrikaans sentences.")

# --- Main Chat Logic ---
if st.session_state["authenticated"]:
    # 1. Display Chat History
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 2. Input and Response
    if prompt := st.chat_input("Ask a question (e.g., 'How do I use STOMPI?')"):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
                st.markdown(response)
                st.session_state["messages"].append({"role": "assistant", "content": response})
                save_to_firebase(st.session_state["current_user"], selected_label, prompt, response, "USER_QUERY")
                st.session_state["feedback_pending"] = True
                st.rerun()

    # 3. Feedback Buttons
    if st.session_state["feedback_pending"] and st.session_state["messages"]:
        if st.session_state["messages"][-1]["role"] == "assistant":
            st.write("---")
            st.caption("Was this explanation helpful?")
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                if st.button("I understand!", use_container_width=True):
                    handle_feedback(True)
                    st.rerun()
            with f_col2:
                if st.button("I need more help!", use_container_width=True):
                    handle_feedback(False)
                    st.rerun()
else:
    st.info("Please login from the sidebar to start the chat.")

# --- Educational Visual Reference ---
with st.expander("Grammar Reference: What is STOMPI?"):
    st.write("STOMPI is the acronym used to remember the word order in an Afrikaans sentence.")