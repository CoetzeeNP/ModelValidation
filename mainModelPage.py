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


# st.markdown("""
# <style>
#     div[data-testid="stChatMessageContent"] { background: transparent !important; padding: 0 !important; }
#     div[data-testid="stChatMessage"] { background: transparent !important; }
#     div[data-testid="stChatMessageAvatar"] { display: none !important; }
#     .chat-card { border-radius: 15px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); width: 100%; }
#     .chat-content { width: 100%; overflow-wrap: anywhere; word-break: break-word; }
#     .student-card { background-color: #e3f2fd; border: 1px solid #bbdefb; color: #0d47a1; }
#     .tutor-card { background-color: #ffebee; border: 1px solid #ffcdd2; color: #b71c1c; }
# </style>
# """, unsafe_allow_html=True)
#
# def safe_markdown_to_html(text: str) -> str:
#     text = (text or "").replace("\r\n", "\n")
#     escaped = html.escape(text)
#     code_blocks = []
#     def _codeblock_repl(m):
#         code_blocks.append(m.group(1))
#         return f"@@CODEBLOCK_{len(code_blocks) - 1}@@"
#     escaped = re.sub(r"```(.*?)```", _codeblock_repl, escaped, flags=re.DOTALL)
#     escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
#     escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
#     escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
#     lines = escaped.split("\n")
#     out = []
#     in_ul = False
#     for line in lines:
#         m_header = re.match(r"^\s*###\s+(.*)$", line)
#         m_list = re.match(r"^\s*([*\-])\s+(.*)$", line)
#         if m_header:
#             if in_ul: out.append("</ul>"); in_ul = False
#             out.append(f"<h3>{m_header.group(1)}</h3>")
#         elif m_list:
#             if not in_ul: out.append("<ul>"); in_ul = True
#             out.append(f"<li>{m_list.group(2)}</li>")
#         else:
#             if in_ul: out.append("</ul>"); in_ul = False
#             if line.strip() == "": out.append("<br>")
#             else: out.append(line + "<br>")
#     if in_ul: out.append("</ul>")
#     html_out = "".join(out)
#     for i, code in enumerate(code_blocks):
#         html_out = html_out.replace(f"@@CODEBLOCK_{i}@@", f"<pre><code>{code}</code></pre>")
#     return html_out

def render_chat_card(who_label: str, css_class: str, text: str):
    #safe_body_html = safe_markdown_to_html(text)
    st.markdown(f'<div class="chat-card {css_class}"><div class="chat-content"><b>{who_label}:</b><br></div></div>', unsafe_allow_html=True)

# --- Updated Firebase Connection ---
# --- Updated Firebase Connection ---
@st.cache_resource
def get_firebase_connection():
    try:
        if not firebase_admin._apps:
            cred_info = dict(st.secrets["firebase_service_account"])
            cred_info["private_key"] = cred_info["private_key"].replace("\\n", "\n")

            # Ensure the URL is clean
            db_url = st.secrets["firebase_db_url"].strip()

            cred = credentials.Certificate(cred_info)
            firebase_admin.initialize_app(cred, {
                'databaseURL': db_url
            })

        # Return the root reference
        return db.reference("/")
    except Exception as e:
        st.error(f"Firebase Init Error: {e}")
        return None


db_ref = get_firebase_connection()


# --- Updated Logging Function with Debugging ---
def save_to_firebase(user_id, model_name, prompt_, full_response, interaction_type):
    if db_ref:
        try:
            # We sanitize the user_id (Firebase keys can't contain '.', '#', '$', '[', or ']')
            clean_user_id = str(user_id).replace(".", "_")

            # Use a timestamp-based key to keep entries in order
            timestamp_key = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Store data at: /logs/user_id/timestamp_key
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
        api_contents = [types.Content(role="user" if m["role"]=="user" else "model", parts=[types.Part.from_text(text=m["content"])]) for m in chat_history]
        response = client.models.generate_content(model=MODEL_MAPPING[model_selection], contents=api_contents, config=types.GenerateContentConfig(temperature=0.7, system_instruction=system_instruction_text))
        return response.text
    except Exception as e: return f"Error: {str(e)}"


if "messages" not in st.session_state: st.session_state["messages"] = []
if "feedback_pending" not in st.session_state: st.session_state["feedback_pending"] = False
if "authenticated" not in st.session_state: st.session_state["authenticated"] = False
if "current_user" not in st.session_state: st.session_state["current_user"] = None


def handle_feedback(understood: bool):
    interaction = "UNDERSTOOD_FEEDBACK" if understood else "CLARIFICATION_REQUESTED"
    last_user_prompt = st.session_state["messages"][-2]["content"] # The prompt before the AI reply
    last_ai_reply = st.session_state["messages"][-1]["content"]

    save_to_firebase(st.session_state["current_user"], selected_label, last_ai_reply, interaction, "FEEDBACK_EVENT")
    
    if not understood:
        clarification_prompt = f"I don't understand the previous explanation: '{last_ai_reply}'. Please break it down further."
        st.session_state["messages"].append({"role": "user", "content": clarification_prompt})
        
        ai_reply = get_ai_response(selected_label, st.session_state["messages"], system_instruction_input)

        save_to_firebase(st.session_state["current_user"], selected_label, clarification_prompt, ai_reply, "CLARIFICATION_RESPONSE")
        
        st.session_state["messages"].append({"role": "assistant", "content": ai_reply})
        st.session_state["feedback_pending"] = True
    else:
        st.session_state["feedback_pending"] = False

with st.sidebar:
    st.header("Afrikaans Assistant Menu")
    st.write(f"**Logged in as:** {st.session_state['current_user']}")
    if not st.session_state["authenticated"]:
        u_id = st.text_input("Enter Student ID", type="password")
        # Placing login button in a column to keep it consistent
        if st.button("Login", use_container_width=True):
            if u_id in AUTHORIZED_STUDENT_IDS:
                st.session_state["authenticated"] = True
                st.session_state["current_user"] = u_id
                st.success("Welcome!")
                st.rerun()
            else:
                st.error("Invalid Student ID")
    else:
        # Create two columns for the buttons
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()

        with col2:
            # Your new MS Form button
            st.link_button("Feedback", "https://forms.office.com/your-link", use_container_width=True)

    if st.session_state["authenticated"]:
        st.markdown("---")
        selected_label = st.selectbox("AI Model", list(MODEL_MAPPING.keys()))
        system_instruction_input = st.text_area("System Message", "You are an Afrikaans tutor. Use STOMPI rules.")

# --- Main App ---
if not st.session_state["authenticated"]:
    st.warning("Please login with an authorized Student ID in the sidebar.")
    # Create the container and add filler text
    with st.container():
        st.markdown("### You need to be signed in to get access to the Afrikaans Assistant!")
        # Optional: Add a visual placeholder
        st.info("Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut "
                "labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco"
                " laboris nisi ut aliquip ex ea commodo consequat.\n\n "
                ""
                "Additional dashboard features will appear here once you are verified.")
else:
    st.info("You are welcome to start chatting with the Assistant using the text box below!")
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
                save_to_firebase(
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

    st.markdown("""
        <style>
        /* Target the 'I understand!' button by its label */
        div[data-testid="stColumn"]:nth-of-type(1) button {
            background-color: #28a745;
            color: white;
            border: none;
        }
        div[data-testid="stColumn"]:nth-of-type(1) button:hover {
            background-color: #218838;
            border: none;
            color: white;
        }

        /* Target the 'I need more help!' button */
        div[data-testid="stColumn"]:nth-of-type(2) button {
            background-color: #dc3545;
            color: white;
            border: none;
        }
        div[data-testid="stColumn"]:nth-of-type(2) button:hover {
            background-color: #c82333;
            border: none;
            color: white;
        }
        </style>
        """, unsafe_allow_html=True)

    # Feedback Buttons
    if st.session_state["feedback_pending"]:
        st.info("Please indicate if you understood the generated response above:")
        c1, c2 = st.columns(2)
        with c1: st.button("I understand!", on_click=handle_feedback, args=(True,), use_container_width=True)
        with c2: st.button("I need more help!", on_click=handle_feedback, args=(False,), use_container_width=True)
