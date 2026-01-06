import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from google import genai
from google.genai import types
import html
import re

# --- Configuration ---
SHEET_NAME = "Gemini Logs"
MODEL_MAPPING = {
    "gemini-3-pro-preview": "gemini-3-pro-preview"
}

# --- AUTHORIZED STUDENT NUMBERS ---
# Only these IDs will be allowed to use the app
AUTHORIZED_STUDENT_IDS = ["12345", "67890", "24680", "13579", "99999"]

# --- Top Image Area ---

img_col1, img_col2, img_col3 = st.columns(3)

with img_col1:
    st.image("interdisciplinary_centre_for_digital_futures.jpg", width="stretch")
with img_col2:
    st.image("interdisciplinary_centre_for_digital_futures.jpg", width="stretch")
with img_col3:
    st.image("interdisciplinary_centre_for_digital_futures.jpg", width="stretch")


# --- Page Config (Must be first) ---
st.set_page_config(page_title="Afrikaans Tutor", layout="wide")

# --- CUSTOM CSS (Kept from your original) ---
st.markdown("""
<style>
    div[data-testid="stChatMessageContent"] { background: transparent !important; padding: 0 !important; }
    div[data-testid="stChatMessage"] { background: transparent !important; }
    div[data-testid="stChatMessageAvatar"] { display: none !important; }
    .chat-card { border-radius: 15px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); width: 100%; }
    .chat-content { width: 100%; overflow-wrap: anywhere; word-break: break-word; }
    .student-card { background-color: #e3f2fd; border: 1px solid #bbdefb; color: #0d47a1; }
    .tutor-card { background-color: #ffebee; border: 1px solid #ffcdd2; color: #b71c1c; }
</style>
""", unsafe_allow_html=True)

# --- Updated Safe markdown-to-HTML Parser ---
def safe_markdown_to_html(text: str) -> str:
    text = (text or "").replace("\r\n", "\n")
    escaped = html.escape(text)
    code_blocks = []
    def _codeblock_repl(m):
        code_blocks.append(m.group(1))
        return f"@@CODEBLOCK_{len(code_blocks) - 1}@@"
    escaped = re.sub(r"```(.*?)```", _codeblock_repl, escaped, flags=re.DOTALL)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
    lines = escaped.split("\n")
    out = []
    in_ul = False
    for line in lines:
        m_header = re.match(r"^\s*###\s+(.*)$", line)
        m_list = re.match(r"^\s*([*\-])\s+(.*)$", line)
        if m_header:
            if in_ul: out.append("</ul>"); in_ul = False
            out.append(f"<h3>{m_header.group(1)}</h3>")
        elif m_list:
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append(f"<li>{m_list.group(2)}</li>")
        else:
            if in_ul: out.append("</ul>"); in_ul = False
            if line.strip() == "": out.append("<br>")
            else: out.append(line + "<br>")
    if in_ul: out.append("</ul>")
    html_out = "".join(out)
    for i, code in enumerate(code_blocks):
        html_out = html_out.replace(f"@@CODEBLOCK_{i}@@", f"<pre><code>{code}</code></pre>")
    return html_out

def render_chat_card(who_label: str, css_class: str, text: str):
    safe_body_html = safe_markdown_to_html(text)
    st.markdown(f'<div class="chat-card {css_class}"><div class="chat-content"><b>{who_label}:</b><br>{safe_body_html}</div></div>', unsafe_allow_html=True)

# --- Google Sheets Connection ---
@st.cache_resource
def get_sheet_connection():
    try:
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
            return gspread.authorize(creds).open(SHEET_NAME).sheet1
        return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

sheet = get_sheet_connection()

def save_to_google_sheets(user_id, model_name, prompt, full_response, interaction_type):
    if sheet:
        try:
            # Added more specific column mapping
            sheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                user_id, 
                model_name, 
                prompt,          # The student's question
                full_response,   # The complete AI answer
                interaction_type # e.g., "INITIAL_QUERY" or "CLARIFICATION"
            ])
        except Exception as e:
            print(f"Logging error: {e}")

def get_ai_response(model_selection, chat_history, system_instruction_text):
    try:
        client = genai.Client(api_key=st.secrets["api_keys"]["google"])
        api_contents = [types.Content(role="user" if m["role"]=="user" else "model", parts=[types.Part.from_text(text=m["content"])]) for m in chat_history]
        response = client.models.generate_content(model=MODEL_MAPPING[model_selection], contents=api_contents, config=types.GenerateContentConfig(temperature=0.7, system_instruction=system_instruction_text))
        return response.text
    except Exception as e: return f"Error: {str(e)}"

# --- State Management ---
if "messages" not in st.session_state: st.session_state["messages"] = []
if "feedback_pending" not in st.session_state: st.session_state["feedback_pending"] = False
if "authenticated" not in st.session_state: st.session_state["authenticated"] = False
if "current_user" not in st.session_state: st.session_state["current_user"] = None

def handle_feedback(understood: bool):
    interaction = "UNDERSTOOD_FEEDBACK" if understood else "CLARIFICATION_REQUESTED"
    last_user_prompt = st.session_state["messages"][-2]["content"] # The prompt before the AI reply
    last_ai_reply = st.session_state["messages"][-1]["content"]
    
    # Log the fact that they clicked the button
    save_to_google_sheets(st.session_state["current_user"], selected_label, "FEEDBACK_EVENT", interaction, last_ai_reply)
    
    if not understood:
        clarification_prompt = f"I don't understand the previous explanation: '{last_ai_reply}'. Please break it down further."
        st.session_state["messages"].append({"role": "user", "content": clarification_prompt})
        
        ai_reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
        
        # --- LOG THE CLARIFICATION RESPONSE ---
        save_to_google_sheets(st.session_state["current_user"], selected_label, clarification_prompt, ai_reply, "CLARIFICATION_RESPONSE")
        
        st.session_state["messages"].append({"role": "assistant", "content": ai_reply})
        st.session_state["feedback_pending"] = True
    else:
        st.session_state["feedback_pending"] = False
    
    st.rerun()

# --- UI ---
with st.sidebar:
    st.header("Login")
    u_id = st.text_input("Enter Student ID", type="password")
    if st.button("Login"):
        if u_id in AUTHORIZED_STUDENT_IDS:
            st.session_state["authenticated"] = True
            st.session_state["current_user"] = u_id
            st.success("Welcome!")
            st.rerun()
        else:
            st.error("Invalid Student ID")

    if st.session_state["authenticated"]:
        st.markdown("---")
        selected_label = st.selectbox("AI Model", list(MODEL_MAPPING.keys()))
        system_instruction_input = st.text_area("System Message", "You are an Afrikaans tutor. Use STOMPI rules.")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

# --- Main App ---
if not st.session_state["authenticated"]:
    st.warning("Please login with an authorized Student ID in the sidebar.")
    st.container("jsakjdkjashdjkahskdjhakjshdkjahsdjkhaksj"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 "hdkjhaskjdhkjashdjkhasjkhdkjashdkjhaksdh"
                 )
else:
    for msg in st.session_state["messages"]:
        role, card = ("Student", "student-card") if msg["role"] == "user" else ("Tutor", "tutor-card")
        render_chat_card(role, card, msg["content"])

    # Disable input if feedback is needed
    input_placeholder = "Please give feedback on the last answer to continue..." if st.session_state["feedback_pending"] else "Ask your Afrikaans question..."
    prompt = st.chat_input(input_placeholder, disabled=st.session_state["feedback_pending"])

    if prompt:
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)
                
                # --- NEW LOGGING CALL ---
                save_to_google_sheets(
                    st.session_state["current_user"], 
                    selected_label, 
                    prompt, 
                    reply, 
                    "INITIAL_QUERY"
                )
                # ------------------------

                st.session_state["messages"].append({"role": "assistant", "content": reply})
                st.session_state["feedback_pending"] = True
                st.rerun()

    # Feedback Buttons
    if st.session_state["feedback_pending"]:
        st.info("Please tell your tutor if you understood the explanation above:")
        c1, c2 = st.columns(2)
        with c1: st.button("✅ I Understand", on_click=handle_feedback, args=(True,), use_container_width=True)
        with c2: st.button("❓ I don't understand", on_click=handle_feedback, args=(False,), use_container_width=True)
