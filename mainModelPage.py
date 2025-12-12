import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from google import genai
from google.genai import types

# --- Configuration ---

SHEET_NAME = "Gemini Logs"
MODEL_MAPPING = {
    "gemini-3-pro-preview": "gemini-3-pro-preview" # Updated to a likely valid model ID for testing
}

# --- Google Sheets Connection ---

@st.cache_resource
def get_sheet_connection():
    """
    Authenticates with Google Sheets using Streamlit secrets
    and opens the specific spreadsheet.
    """
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
        st.error(f"❌ Connection Error: {e}")
        return None

sheet = get_sheet_connection()

# --- Helper Functions ---

def save_to_google_sheets(user_id, model_name, prompt, response, is_clarification):
    """
    Appends a new row to the Google Sheet.
    """
    if sheet is None:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clarification_log = "TRUE" if is_clarification else "FALSE"
    
    row_data = [user_id, timestamp, model_name, prompt, response, clarification_log]
    
    try:
        sheet.append_row(row_data)
    except Exception as e:
        st.error(f"Failed to write to Sheet: {e}")

def get_ai_response(model_selection, chat_history, system_instruction_text): 
    """
    Sends the chat history AND the system instruction to the API.
    """
    try:
        api_key = st.secrets["api_keys"]["google"]
    except KeyError:
        return "Error: Gemini API key not found in secrets."

    try:
        if model_selection in MODEL_MAPPING:
            client = genai.Client(api_key=api_key)
            model_id = MODEL_MAPPING[model_selection]

            # 1. Convert Streamlit history to Gemini API format
            api_contents = []
            for msg in chat_history:
                role = "user" if msg["role"] == "user" else "model"
                api_contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=msg["content"])]
                    )
                )

            # 2. Configure the model with the System Instruction
            config = types.GenerateContentConfig(
                temperature=0.7,
                system_instruction=system_instruction_text 
            )

            # 3. Generate content
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
    """
    Sets a flag to auto-submit a clarification request on the next rerun.
    """
    st.session_state["auto_execute_clarification"] = True

def clear_chat_history():
    """
    Clears the message history from session state.
    """
    st.session_state["messages"] = []
    st.session_state["auto_execute_clarification"] = False

# --- Streamlit Interface ---

st.set_page_config(page_title="Gemini Chat", layout="wide")

# 1. Initialize Session State
if "messages" not in st.session_state:
    st.session_state["messages"] = [] 

if "auto_execute_clarification" not in st.session_state:
    st.session_state["auto_execute_clarification"] = False

# --- NEW: Top Image Area (Side by Side) ---
# Using placeholders here. Replace URLs with your actual image links or local file paths.
img_col1, img_col2, img_col3 = st.columns(3)

with img_col1:
    st.image("https://placehold.co/400x75/orange/white?text=UFS+Logo", use_container_width=True)

with img_col2:
    st.image("https://placehold.co/400x75/blue/white?text=Afrikaans+Department", use_container_width=True)

with img_col3:
    st.image("https://placehold.co/400x75/blue/white?text=ICDF", use_container_width=True)

st.title("Afrikaans Assistant - Demo")
st.markdown("---")

# 2. Configuration Sidebar / Area
with st.container():
    col1, col2 = st.columns([1, 2])
    with col1:
        # --- NEW: User ID with Submit Button ---
        sub_col1, sub_col2 = st.columns([3, 1])
        with sub_col1:
            user_id_input = st.text_input("👤 User ID", placeholder="student_123")
        with sub_col2:
            # Using some vertical spacing to align button with input box
            st.write("") 
            st.write("")
            if st.button("Submit"):
                if user_id_input:
                    st.toast(f"✅ ID Set: {user_id_input}")
                else:
                    st.toast("⚠️ Please type an ID")

        selected_label = st.selectbox("Select AI Model", options=list(MODEL_MAPPING.keys()))
        #selected_label = "gemini-3-pro-preview"

        # --- NEW: Clear Chat Button ---
        st.write("") # Spacer
        if st.button("🗑️ Clear Chat History", type="primary"):
            clear_chat_history()
            st.rerun() # Force a reload to reflect the empty chat immediately
    
    with col2:
        # System Message Input
        default_system_msg = (
            "You are a helpful Afrikaans language tutor. "
            "Explain answers in simple English first, then provide the Afrikaans translation. "
            "Always reference the STOMPI rule when correcting sentence structure."
        )
        system_instruction_input = st.text_area(
            "🛠️ System Instruction (Persona)", 
            value=default_system_msg,
            height=150,
            help="This tells the AI how to behave (e.g., 'You are a strict teacher')."
        )

        #system_instruction_input = "You are a helpful Afrikaans language tutor. " + "Explain answers in simple English first, then provide the Afrikaans translation. " + "Always reference the STOMPI rule when correcting sentence structure."

# 3. Display Chat History
for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Handle Input (User types logic OR Clarification logic)
prompt = st.chat_input("Ask Gemini anything...")
clarification_triggered = st.session_state["auto_execute_clarification"]

# Determine if we have input to process
final_prompt = None
is_clarification = False

if clarification_triggered:
    # Logic to fetch the last AI response to ask about it
    if st.session_state["messages"] and st.session_state["messages"][-1]["role"] == "assistant":
        # The specific question for clarification
        explanation_request = "I don't understand the previous explanation. Please break it down further."
        
        final_prompt = explanation_request
        is_clarification = True
        st.session_state["auto_execute_clarification"] = False # Reset flag
    else:
        st.session_state["auto_execute_clarification"] = False

elif prompt:
    final_prompt = prompt
    is_clarification = False

# 5. Process the Prompt
if final_prompt:
    if not user_id_input.strip():
        st.error("⚠️ Please enter a User ID first.")
    else:
        # A. Display User Message
        with st.chat_message("user"):
            st.markdown(final_prompt)
        
        # B. Add to local state history
        st.session_state["messages"].append({"role": "user", "content": final_prompt})

        # C. Generate Response (Passing System Instruction)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                ai_reply = get_ai_response(
                    selected_label, 
                    st.session_state["messages"], 
                    system_instruction_input  # <--- Passing the UI variable
                )
                st.markdown(ai_reply)
        
        # D. Add Assistant response to local state history
        st.session_state["messages"].append({"role": "assistant", "content": ai_reply})

        # E. Log to Google Sheets
        save_to_google_sheets(
            user_id_input, 
            selected_label, 
            final_prompt, 
            ai_reply, 
            is_clarification=is_clarification
        )

# 6. Clarification Button Logic
if st.session_state["messages"] and st.session_state["messages"][-1]["role"] == "assistant":
    st.button("🤔 I don't understand this", on_click=trigger_clarification)