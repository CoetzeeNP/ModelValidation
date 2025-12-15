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

# --- Page Config (Must be first) ---
st.set_page_config(page_title="Afrikaans Tutor", layout="wide")

# --- CUSTOM CSS FOR READABILITY & COLORS ---
st.markdown("""
<style>
    /* Remove Streamlit's default chat bubble background around your custom cards */
    div[data-testid="stChatMessageContent"] {
      background: transparent !important;
      padding: 0 !important;
      border-radius: 0 !important;
    }
    div[data-testid="stChatMessage"] {
      background: transparent !important;
    }

    /* OPTIONAL: hide avatars completely */
    div[data-testid="stChatMessageAvatar"] {
      display: none !important;
    }

    /* SHARED CARD STYLES (no avatar layout) */
    .chat-card {
        border-radius: 15px;
        padding: 15px;
        margin-bottom: 15px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        width: 100%;
    }

    /* CONTENT STYLE */
    .chat-content {
        width: 100%;
        overflow-wrap: anywhere;
        word-break: break-word;
    }

    /* STUDENT SPECIFIC COLORS (Soft Blue) */
    .student-card {
        background-color: #e3f2fd;
        border: 1px solid #bbdefb;
        color: #0d47a1;
    }

    /* TUTOR SPECIFIC COLORS (Soft Red) */
    .tutor-card {
        background-color: #ffebee;
        border: 1px solid #ffcdd2;
        color: #b71c1c;
    }

    /* Make lists/code look good inside the cards */
    .chat-card ul { margin: 0.25rem 0 0.25rem 1.25rem; padding-left: 1rem; }
    .chat-card li { margin: 0.15rem 0; }
    
    /* Code block styling */
    .chat-card pre {
        padding: 10px;
        border-radius: 10px;
        overflow-x: auto;
        white-space: pre-wrap;
        margin: 0.5rem 0;
        background: rgba(255, 255, 255, 0.5);
    }
    .chat-card code {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }

    /* NEW: H3 Header Styles */
    .chat-card h3 {
        margin-top: 10px;
        margin-bottom: 5px;
        font-size: 1.1em;
        font-weight: 700;
        line-height: 1.4;
    }

    .stChatInput {
        padding-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# --- Updated Safe markdown-to-HTML Parser ---
def safe_markdown_to_html(text: str) -> str:
    """
    Converts a safe subset of Markdown to HTML.
    Supports:
      - ### Headers
      - **bold**
      - *italics*
      - bullet lists (* item / - item)
      - inline code `code`
      - fenced code blocks
    """
    text = (text or "").replace("\r\n", "\n")
    escaped = html.escape(text)

    # 1. Extract fenced code blocks (preserve them before other regexes run)
    code_blocks = []
    def _codeblock_repl(m):
        code_blocks.append(m.group(1))
        return f"@@CODEBLOCK_{len(code_blocks) - 1}@@"
    
    escaped = re.sub(r"```(.*?)```", _codeblock_repl, escaped, flags=re.DOTALL)

    # 2. Inline code `code`
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)

    # 3. Bold **text**
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)

    # 4. Italics *text* (looks for single asterisks not surrounded by spaces)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)

    # 5. Process Lines (Lists and Headers)
    lines = escaped.split("\n")
    out = []
    in_ul = False

    for line in lines:
        stripped_line = line.strip()

        # Check for Headers (###)
        m_header = re.match(r"^\s*###\s+(.*)$", line)

        # Check for sub Headers (####)
        m_nheader = re.match(r"^\s*####\s+(.*)$", line)
        
        # Check for Lists (* or -)
        m_list = re.match(r"^\s*([*\-])\s+(.*)$", line)

        if m_header:
            # If we were in a list, close it first
            if in_ul:
                out.append("</ul>")
                in_ul = False
            # Append Header
            out.append(f"<h3>{m_header.group(1)}</h3>")

        if m_nheader:
            # If we were in a list, close it first
            if in_ul:
                out.append("</ul>")
                in_ul = False
            # Append Header
            out.append(f"<h3>{m_nheader.group(1)}</h3>")
            
        elif m_list:
            # Open list if not already open
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{m_list.group(2)}</li>")
            
        else:
            # Regular line
            if in_ul:
                out.append("</ul>")
                in_ul = False
            
            if stripped_line == "":
                out.append("<br>")
            else:
                out.append(line + "<br>")

    if in_ul:
        out.append("</ul>")

    html_out = "".join(out)

    # 6. Restore fenced code blocks
    for i, code in enumerate(code_blocks):
        code_html = code # Newlines are preserved in pre
        html_out = html_out.replace(
            f"@@CODEBLOCK_{i}@@",
            f"<pre><code>{code_html}</code></pre>"
        )

    return html_out

# --- Renderer (keeps text INSIDE the card) ---
def render_chat_card(who_label: str, css_class: str, text: str):
    safe_body_html = safe_markdown_to_html(text)
    safe_label = html.escape(who_label)

    st.markdown(
        f"""
        <div class="chat-card {css_class}">
            <div class="chat-content">
                <b>{safe_label}:</b><br>
                {safe_body_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# --- Google Sheets Connection ---
@st.cache_resource
def get_sheet_connection():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    try:
        if "gcp_service_account" in st.secrets:
            s_account_info = st.secrets["gcp_service_account"]
            creds = Credentials.from_service_account_info(
                s_account_info, scopes=scopes
            )
            client = gspread.authorize(creds)
            sheet = client.open(SHEET_NAME).sheet1
            return sheet
        else:
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

sheet = get_sheet_connection()

# --- Helper Functions ---
def save_to_google_sheets(user_id, model_name, prompt, response, interaction_type):
    if sheet is None:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row_data = [user_id, timestamp, model_name, prompt, response, interaction_type]

    try:
        sheet.append_row(row_data)
    except Exception as e:
        st.error(f"Failed to write to Sheet: {e}")

def get_ai_response(model_selection, chat_history, system_instruction_text):
    try:
        api_key = st.secrets["api_keys"]["google"]
    except KeyError:
        return "Error: Gemini API key not found in secrets."

    try:
        if model_selection in MODEL_MAPPING:
            client = genai.Client(api_key=api_key)
            model_id = MODEL_MAPPING[model_selection]

            api_contents = []
            for msg in chat_history:
                role = "user" if msg["role"] == "user" else "model"
                api_contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=msg["content"])]
                    )
                )

            config = types.GenerateContentConfig(
                temperature=0.7,
                system_instruction=system_instruction_text
            )

            response = client.models.generate_content(
                model=model_id,
                contents=api_contents,
                config=config
            )
            return response.text
        else:
            return "Error: Selected model not configured."

    except Exception as e:
        return f"Error calling API: {str(e)}"

def trigger_clarification():
    st.session_state["auto_execute_clarification"] = True

def clear_chat_history():
    st.session_state["messages"] = []
    st.session_state["auto_execute_clarification"] = False
    st.session_state["feedback_submitted"] = False

# --- Initialization ---
if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "auto_execute_clarification" not in st.session_state:
    st.session_state["auto_execute_clarification"] = False

if "feedback_submitted" not in st.session_state:
    st.session_state["feedback_submitted"] = False

# --- Top Image Area ---
img_col1, img_col2, img_col3 = st.columns(3)
with img_col1:
    st.image("https://placehold.co/400x75/blue/white?text=UFS Logo", width="stretch")
with img_col2:
    st.image("https://placehold.co/400x75/blue/white?text=Humanities", width="stretch")
with img_col3:
    st.image("https://placehold.co/400x75/blue/white?text=ICDF", width="stretch")

st.title("Afrikaans Assistant - Demo")
st.markdown("---")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("Settings")

    st.caption("Student Identity")
    user_id_input = st.text_input("Student ID", placeholder="Enter ID here...")
    if st.button("Set ID"):
        if user_id_input:
            st.toast(f"ID Set Student: {user_id_input}")
        else:
            st.toast("Please type an ID")

    st.markdown("---")

    st.caption("AI Configuration")
    selected_label = st.selectbox("Select AI Model", options=list(MODEL_MAPPING.keys()))

    default_system_msg = (
        "You are a helpful Afrikaans language tutor. "
        "Explain answers in simple English first, then provide the Afrikaans translation. "
        "Always reference the STOMPI rule when correcting sentence structure."
    )
    system_instruction_input = st.text_area(
        "System Message",
        value=default_system_msg,
        height=150
    )

    st.markdown("---")

    if st.button("Clear Chat History", type="primary"):
        clear_chat_history()
        st.rerun()

# --- Main Chat Interface ---

# Display chat history (no avatars)
for message in st.session_state["messages"]:
    if message["role"] == "user":
        with st.chat_message("user"):
            render_chat_card("Student", "student-card", message["content"])
    else:
        with st.chat_message("assistant"):
            render_chat_card("Tutor", "tutor-card", message["content"])

prompt = st.chat_input("Type your question here...")
clarification_triggered = st.session_state["auto_execute_clarification"]

final_prompt = None
interaction_type = "STANDARD"

if clarification_triggered:
    if st.session_state["messages"] and st.session_state["messages"][-1]["role"] == "assistant":
        previous_response_text = st.session_state["messages"][-1]["content"]
        final_prompt = (
            "I don't understand the following explanation: "
            f"'{previous_response_text}'. "
            "Please break it down further."
        )
        interaction_type = "CLARIFICATION_REQUEST"
        st.session_state["auto_execute_clarification"] = False
    else:
        st.session_state["auto_execute_clarification"] = False

elif prompt:
    final_prompt = prompt
    interaction_type = "STANDARD"

# Process prompt
if final_prompt:
    if not user_id_input.strip():
        st.error("Please enter a User ID in the sidebar first.")
    else:
        # Show user message immediately
        with st.chat_message("user"):
            render_chat_card("Student", "student-card", final_prompt)

        st.session_state["messages"].append({"role": "user", "content": final_prompt})
        st.session_state["feedback_submitted"] = False

        # Generate & display AI response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                ai_reply = get_ai_response(
                    selected_label,
                    st.session_state["messages"],
                    system_instruction_input
                )
                render_chat_card("Tutor", "tutor-card", ai_reply)

        st.session_state["messages"].append({"role": "assistant", "content": ai_reply})

        # Log data
        save_to_google_sheets(
            user_id_input,
            selected_label,
            final_prompt,
            ai_reply,
            interaction_type
        )

# Feedback buttons
if st.session_state["messages"] and \
   st.session_state["messages"][-1]["role"] == "assistant" and \
   not st.session_state["feedback_submitted"]:

    st.markdown("---")
    st.write("Does this explanation help?")

    col_understand, col_clarify = st.columns(2)

    with col_understand:
        if st.button("I Understand", type="primary", use_container_width=True):
            if user_id_input:
                last_ai_msg = st.session_state["messages"][-1]["content"]
                save_to_google_sheets(
                    user_id_input,
                    selected_label,
                    "User clicked 'I Understand'",
                    last_ai_msg[0:50] + "...",
                    "UNDERSTOOD"
                )
                st.toast("Feedback recorded.")
                st.session_state["feedback_submitted"] = True
                st.rerun()
            else:
                st.error("Please enter a User ID in the sidebar.")

    with col_clarify:
        st.button("I don't understand", on_click=trigger_clarification, use_container_width=True)