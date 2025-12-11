import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from google import genai

# --- Configuration ---

SHEET_NAME = "Gemini Logs" 
MODEL_MAPPING = {
    "gemini-3-pro-preview": "gemini-3-pro-preview"
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
        s_account_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(
            s_account_info, scopes=scopes
        )
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
        
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        return None

sheet = get_sheet_connection()

# --- Helper Functions ---

def save_to_google_sheets(user_id, model_name, prompt, response, is_clarification):
    """
    Appends a new row to the Google Sheet.
    Includes a boolean flag for clarification requests.
    """
    if sheet is None:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Convert boolean to string for easier reading in Sheets
    clarification_log = "TRUE" if is_clarification else "FALSE"
    
    row_data = [user_id, timestamp, model_name, prompt, response, clarification_log]
    
    try:
        sheet.append_row(row_data)
        
        # Update history
        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []
            
        st.session_state["chat_history"].append({
            "user_id": user_id,
            "timestamp": timestamp,
            "prompt": prompt,
            "response": response,
            "is_clarification": is_clarification
        })
        
    except Exception as e:
        st.error(f"Failed to write to Sheet: {e}")

def get_ai_response(model_selection, user_prompt): 
    try:
        api_key = st.secrets["api_keys"]["google"]
    except KeyError:
        return "Error: Gemini API key not found in secrets."

    try:
        if model_selection in MODEL_MAPPING:
            client = genai.Client(api_key=api_key)
            model_id = MODEL_MAPPING[model_selection]

            response = client.models.generate_content(
                model=model_id,
                contents=user_prompt
            )
            return response.text
        else:
            return "Error: Selected model not configured."

    except Exception as e:
        return f"Error calling API: {str(e)}"

def trigger_clarification():
    """
    Callback function:
    1. Updates prompt text.
    2. Sets a flag to AUTO-RUN generation on the immediate rerun.
    """
    if st.session_state.get("last_response"):
        explanation_request = (
            "I dont understand this - please could you explain it in more detail - "
            "the user is an english speaker and is trying to understand afrikaans "
            "so help them understand."
        )
        
        # Combine the request with the previous output
        new_prompt_text = f"{explanation_request}\n\n---\n\n{st.session_state['last_response']}"
        
        # Update text box
        st.session_state["prompt_input"] = new_prompt_text
        
        # --- KEY CHANGE: Set flags for auto-execution ---
        st.session_state["auto_execute"] = True
        st.session_state["is_clarification_flag"] = True

# --- Streamlit Interface ---

# 1. Initialize Session State Variables
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

if "prompt_input" not in st.session_state:
    st.session_state["prompt_input"] = ""

if "last_response" not in st.session_state:
    st.session_state["last_response"] = None

# New state variables for auto-execution
if "auto_execute" not in st.session_state:
    st.session_state["auto_execute"] = False

if "is_clarification_flag" not in st.session_state:
    st.session_state["is_clarification_flag"] = False

st.title("🤖 Gemini + Google Sheets Logger")
st.markdown("---")

### Configuration Area
col1, col2 = st.columns([1, 2])

with col1:
    user_id_input = st.text_input(
        "👤 User ID", 
        placeholder="e.g., student_123",
        help="This ID will be saved to the Google Sheet."
    )
    
    selected_label = st.selectbox(
        "Select AI Model",
        options=list(MODEL_MAPPING.keys())
    )

### User Input Area
user_prompt = st.text_area(
    "💬 Enter your prompt:", 
    height=150,
    placeholder="Ask Gemini anything...",
    key="prompt_input" 
)

# 2. Define the Generate Button
# We just capture the click state here
generate_clicked = st.button("🚀 Generate Response", type="primary")

# 3. Logic Control Flow
# We run the logic if the button was clicked OR if auto_execute is True
if generate_clicked or st.session_state["auto_execute"]:
    
    if not user_id_input.strip():
        st.error("⚠️ Please enter a User ID.")
        st.session_state["auto_execute"] = False # Reset flag if error
    elif not user_prompt.strip():
        st.warning("⚠️ Please enter a prompt.")
        st.session_state["auto_execute"] = False # Reset flag if error
    else:
        with st.spinner(f"Asking {selected_label}..."):
            # Determine if this run is a clarification based on our state flag
            is_clarification_run = st.session_state["is_clarification_flag"]

            # 1. Get AI Response
            ai_reply = get_ai_response(selected_label, user_prompt)
            
            # 2. Store response for next time
            st.session_state["last_response"] = ai_reply
            
            # 3. Display
            st.markdown("### ✨ Response")
            st.markdown(ai_reply)
            
            # 4. Save to Google Sheets (Passing the clarification flag)
            save_to_google_sheets(
                user_id_input, 
                selected_label, 
                user_prompt, 
                ai_reply, 
                is_clarification=is_clarification_run
            )
            st.success(f"✅ Logged to Google Sheet: {SHEET_NAME} | Clarification: {is_clarification_run}")

            # 5. RESET FLAGS
            # Important: Turn off auto-execute so it doesn't loop forever
            st.session_state["auto_execute"] = False
            st.session_state["is_clarification_flag"] = False

# --- The "I Don't Understand" Button Logic ---

if st.session_state["last_response"]:
    st.markdown("---")
    st.write("Need clarification?")
    
    # Callback updates prompt text AND sets 'auto_execute' to True
    st.button("I don't understand this", on_click=trigger_clarification)

st.markdown("---")

### View History
with st.expander("View Current Session History"):
    history = st.session_state["chat_history"]
    
    if not history:
        st.info("No interactions in this session.")
    else:
        for i, entry in enumerate(reversed(history)):
            tag = " [CLARIFICATION]" if entry.get('is_clarification') else ""
            st.markdown(f"**{len(history) - i}. User:** `{entry['user_id']}`{tag} | **Time:** `{entry['timestamp']}`")
            st.markdown(f"**Prompt:** *{entry['prompt'][:80]}...*")
            st.caption("---")