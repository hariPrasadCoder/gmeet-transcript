import os
import json
import base64
import uuid
import csv
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# ----------------------------
# Config and setup
# ----------------------------
load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8501/")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
]

if not CLIENT_ID or not CLIENT_SECRET:
    st.error("Missing GOOGLE_OAUTH_CLIENT_ID or GOOGLE_OAUTH_CLIENT_SECRET in .env")
    st.stop()

if not GEMINI_API_KEY:
    st.error("Missing GEMINI_API_KEY in .env")
    st.stop()

# Configure Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# Session keys
CREDS_KEY = "google_creds"
USER_INFO_KEY = "user_info"
STATE_KEY = "oauth_state"
ACTION_ITEMS_KEY = "action_items"

# ----------------------------
# Helpers
# ----------------------------

def client_config() -> Dict[str, Any]:
    return {
        "web": {
            "client_id": CLIENT_ID,
            "project_id": "meet-transcripts-streamlit",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": CLIENT_SECRET,
            "redirect_uris": [REDIRECT_URI],
            "javascript_origins": [REDIRECT_URI.rstrip("/")],
        }
    }


def create_flow(state: str) -> Flow:
    return Flow.from_client_config(client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI)


def decode_id_token_sub_name(id_token: Optional[str]) -> Dict[str, str]:
    if not id_token:
        return {"sub": "unknown", "name": "User"}
    try:
        payload = id_token.split(".")[1] + "=="
        data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return {"sub": data.get("sub", "unknown"), "name": data.get("name", "User")}
    except Exception:
        return {"sub": "unknown", "name": "User"}


def ensure_creds() -> Optional[Credentials]:
    creds_dict = st.session_state.get(CREDS_KEY)
    if not creds_dict:
        return None
    creds = Credentials.from_authorized_user_info(creds_dict, SCOPES)
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            st.session_state[CREDS_KEY] = json.loads(creds.to_json())
        except Exception as e:
            st.warning(f"Token refresh failed: {e}")
            return None
    return creds


def meet_service(creds: Credentials):
    return build("meet", "v2", credentials=creds, cache_discovery=False)


def list_conference_records_by_code(svc, meeting_code: str) -> List[Dict[str, Any]]:
    resp = svc.conferenceRecords().list(
        filter=f'space.meeting_code = "{meeting_code}"', pageSize=10
    ).execute()
    return resp.get("conferenceRecords", [])


def list_conference_records_by_time(svc, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    resp = svc.conferenceRecords().list(
        filter=f'start_time>="{start_iso}" AND start_time<="{end_iso}"', pageSize=25
    ).execute()
    return resp.get("conferenceRecords", [])


def list_transcripts_for_record(svc, cr_name: str) -> List[Dict[str, Any]]:
    t = svc.conferenceRecords().transcripts().list(parent=cr_name).execute()
    return t.get("transcripts", [])


def fetch_entries_for_transcript(svc, transcript_name: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    req = svc.conferenceRecords().transcripts().entries().list(parent=transcript_name, pageSize=100)
    while True:
        page = req.execute()
        entries.extend(page.get("transcriptEntries", []))
        token = page.get("nextPageToken")
        if not token:
            break
        req = svc.conferenceRecords().transcripts().entries().list(parent=transcript_name, pageToken=token, pageSize=100)
    return entries


def normalize_entry(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "startTime": e.get("startTime"),
        "endTime": e.get("endTime"),
        "speaker": e.get("speaker", {}).get("displayName")
                    or e.get("speaker", {}).get("obfuscatedExternalUserId")
                    or "Speaker",
        "text": e.get("text", ""),
    }


def as_text(entries: List[Dict[str, Any]]) -> str:
    lines = []
    for e in entries:
        lines.append(f"[{e.get('startTime','')}] {e.get('speaker','Speaker')}: {e.get('text','')}")
    return "\n".join(lines)


# ----------------------------
# Action Item Extraction
# ----------------------------

def extract_action_items(transcript_text: str) -> List[Dict[str, Any]]:
    """Extract action items from transcript using Gemini API"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
Analyze the following meeting transcript and extract all action items, tasks, and follow-up items mentioned.

For each action item, identify:
1. The task description
2. The person responsible (if mentioned)
3. Any deadline or timeline mentioned
4. Priority level (High/Medium/Low)

Return the results in JSON format with this structure:
{{
  "action_items": [
    {{
      "id": "unique_id",
      "task": "description of the task",
      "assignee": "person responsible (or 'Unassigned' if not mentioned)",
      "deadline": "deadline if mentioned (or 'No deadline')",
      "priority": "High/Medium/Low",
      "context": "relevant context from the meeting"
    }}
  ]
}}

Transcript:
{transcript_text}

Please be thorough and extract all actionable items, even if they seem minor. Include tasks that were delegated, follow-ups that were mentioned, or decisions that require action.
"""
        
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Try to extract JSON from the response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        elif "{" in response_text and "}" in response_text:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_text = response_text[json_start:json_end]
        else:
            # Fallback: create a single action item with the raw response
            return [{
                "id": str(uuid.uuid4()),
                "task": "Review meeting transcript for action items",
                "assignee": "Unassigned",
                "deadline": "No deadline",
                "priority": "Medium",
                "context": response_text[:200] + "..." if len(response_text) > 200 else response_text
            }]
        
        result = json.loads(json_text)
        action_items = result.get("action_items", [])
        
        # Add unique IDs if not present
        for item in action_items:
            if "id" not in item:
                item["id"] = str(uuid.uuid4())
        
        return action_items
        
    except Exception as e:
        st.error(f"Error extracting action items: {str(e)}")
        return []


# ----------------------------
# CSV Storage Functions
# ----------------------------

CSV_FILE_PATH = "action_items.csv"

def save_action_items_to_csv(action_items: Dict[str, List[Dict[str, Any]]]):
    """Save action items to CSV file"""
    try:
        # Flatten the action items for CSV storage
        csv_data = []
        for status, items in action_items.items():
            for item in items:
                csv_data.append({
                    'id': item['id'],
                    'task': item['task'],
                    'assignee': item['assignee'],
                    'deadline': item['deadline'],
                    'priority': item['priority'],
                    'context': item['context'],
                    'status': status,
                    'created_date': datetime.now().isoformat()
                })
        
        # Write to CSV
        if csv_data:
            df = pd.DataFrame(csv_data)
            df.to_csv(CSV_FILE_PATH, index=False)
            return True
        return False
    except Exception as e:
        st.error(f"Error saving to CSV: {str(e)}")
        return False

def load_action_items_from_csv() -> Dict[str, List[Dict[str, Any]]]:
    """Load action items from CSV file"""
    try:
        if not os.path.exists(CSV_FILE_PATH):
            return {"todo": [], "in_progress": [], "done": []}
        
        df = pd.read_csv(CSV_FILE_PATH)
        action_items = {"todo": [], "in_progress": [], "done": []}
        
        for _, row in df.iterrows():
            item = {
                'id': row['id'],
                'task': row['task'],
                'assignee': row['assignee'],
                'deadline': row['deadline'],
                'priority': row['priority'],
                'context': row['context']
            }
            status = row['status']
            if status in action_items:
                action_items[status].append(item)
        
        return action_items
    except Exception as e:
        st.warning(f"Error loading from CSV: {str(e)}")
        return {"todo": [], "in_progress": [], "done": []}

def initialize_action_items() -> Dict[str, List[Dict[str, Any]]]:
    """Initialize the action items structure"""
    if ACTION_ITEMS_KEY not in st.session_state:
        # Try to load from CSV first
        action_items = load_action_items_from_csv()
        st.session_state[ACTION_ITEMS_KEY] = action_items
    return st.session_state[ACTION_ITEMS_KEY]


def move_action_item(item_id: str, from_status: str, to_status: str):
    """Move an action item between statuses"""
    action_items = st.session_state[ACTION_ITEMS_KEY]
    
    # Find and remove the item from the source status
    item_to_move = None
    for i, item in enumerate(action_items[from_status]):
        if item["id"] == item_id:
            item_to_move = action_items[from_status].pop(i)
            break
    
    # Add to the target status
    if item_to_move:
        action_items[to_status].append(item_to_move)
        st.session_state[ACTION_ITEMS_KEY] = action_items
        # Save to CSV
        save_action_items_to_csv(action_items)
        st.rerun()


def delete_action_item(item_id: str, status: str):
    """Delete an action item"""
    action_items = st.session_state[ACTION_ITEMS_KEY]
    
    for i, item in enumerate(action_items[status]):
        if item["id"] == item_id:
            action_items[status].pop(i)
            break
    
    st.session_state[ACTION_ITEMS_KEY] = action_items
    # Save to CSV
    save_action_items_to_csv(action_items)
    st.rerun()


def add_action_item(task: str, assignee: str = "Unassigned", priority: str = "Medium"):
    """Add a new action item"""
    action_items = st.session_state[ACTION_ITEMS_KEY]
    
    new_item = {
        "id": str(uuid.uuid4()),
        "task": task,
        "assignee": assignee,
        "deadline": "No deadline",
        "priority": priority,
        "context": "Manually added"
    }
    
    action_items["todo"].append(new_item)
    st.session_state[ACTION_ITEMS_KEY] = action_items
    # Save to CSV
    save_action_items_to_csv(action_items)
    st.rerun()

# ----------------------------
# UI - Auth
# ----------------------------
st.set_page_config(page_title="Meet Transcripts", page_icon="📝", layout="wide")

# Header with better visual hierarchy
st.markdown("""
<div style="text-align: center; padding: 1rem 0;">
    <h1 style="margin: 0; color: #1f77b4;">📝 Google Meet Transcripts</h1>
    <p style="margin: 0.5rem 0; color: #666; font-size: 1.1rem;">Extract insights and action items from your meeting transcripts</p>
</div>
""", unsafe_allow_html=True)

# Compact authentication section
connected = False
creds = ensure_creds()
if creds:
    info = decode_id_token_sub_name(creds.id_token)
    st.success(f"✅ Connected as **{info.get('name','User')}**")
    connected = True
else:
    # If we have an auth code from Google, finish the flow
    params = st.query_params
    code = params.get("code", [None]) if isinstance(params.get("code"), list) else params.get("code")
    state = params.get("state", [None]) if isinstance(params.get("state"), list) else params.get("state")

    if code:
        flow = create_flow(state or "init")
        try:
            flow.fetch_token(code=code)
            creds = flow.credentials
            st.session_state[CREDS_KEY] = json.loads(creds.to_json())
            info = decode_id_token_sub_name(creds.id_token)
            st.success(f"✅ Connected as **{info.get('name','User')}**")
            connected = True
        except Exception as e:
            st.error(f"OAuth error: {e}")

    if not connected:
        # Build the authorization URL
        if STATE_KEY not in st.session_state:
            st.session_state[STATE_KEY] = "st-" + base64.urlsafe_b64encode(os.urandom(12)).decode("utf-8").strip("=")
        flow = create_flow(st.session_state[STATE_KEY])
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("### 🔐 Authentication Required")
            st.markdown("Connect your Google account to access meeting transcripts")
            st.link_button("🔗 Connect Google Account", auth_url, help="Grant read-only access to Meet artifacts")
            st.caption("No meeting bot required • Read-only access • Secure OAuth")

# Stop here if not connected
creds = ensure_creds()
if not creds:
    st.info("Connect your Google account to continue.")
    st.stop()

svc = meet_service(creds)

# ----------------------------
# UI - Meeting Search
# ----------------------------
st.markdown("---")
st.markdown("### 🔍 Find Your Meeting")

# Unified search interface
search_method = st.radio(
    "Search by:", 
    ["Meeting Code", "Time Range"], 
    horizontal=True,
    help="Choose how you want to find your meeting"
)

if search_method == "Meeting Code":
    col1, col2 = st.columns([3, 1])
    with col1:
        code = st.text_input("Enter meeting code", placeholder="abc-mnop-xyz", label_visibility="collapsed")
    with col2:
        search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)
    
    if search_clicked:
        if not code:
            st.warning("Please enter a meeting code")
        else:
            with st.spinner("Searching for meeting..."):
                records = list_conference_records_by_code(svc, code)
            if not records:
                st.warning("No conference records found for this code.")
            else:
                st.success(f"✅ Found {len(records)} record(s)")
                st.session_state["_records"] = records

else:  # Time Range
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📅 Start Time**")
        default_end = datetime.now(timezone.utc)
        default_start = default_end - timedelta(days=7)
        start_date = st.date_input("Date", default_start.date(), label_visibility="collapsed")
        start_time = st.time_input("Time (UTC)", default_start.time().replace(microsecond=0), label_visibility="collapsed")
    with col2:
        st.markdown("**📅 End Time**")
        end_date = st.date_input("Date", default_end.date(), label_visibility="collapsed", key="end_date")
        end_time = st.time_input("Time (UTC)", default_end.time().replace(microsecond=0), label_visibility="collapsed", key="end_time")

    start_iso = datetime.combine(start_date, start_time, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = datetime.combine(end_date, end_time, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        search_clicked = st.button("🔍 Search Time Range", type="primary", use_container_width=True)
    
    if search_clicked:
        with st.spinner("Searching for meetings..."):
            records = list_conference_records_by_time(svc, start_iso, end_iso)
        if not records:
            st.warning("No conference records found in this time range.")
        else:
            st.success(f"✅ Found {len(records)} record(s)")
            st.session_state["_records"] = records

records = st.session_state.get("_records", [])

# ----------------------------
# UI - Results and transcripts
# ----------------------------
if records:
    st.markdown("---")
    st.markdown("### 📋 Meeting Records")
    
    options = []
    for r in records:
        name = r.get("name")
        # The space field contains a space ID string, not a dictionary
        space_id = r.get("space", "")
        summary = space_id.split("/")[-1] if space_id else ""
        start = r.get("startTime", "").replace("T", " ").replace("Z", " UTC")
        end = r.get("endTime", "").replace("T", " ").replace("Z", " UTC")
        options.append((f"{summary} - {start} to {end}", name))

    labels = [o[0] for o in options]
    selected = st.selectbox("Select a meeting", labels, index=0)
    cr_name = dict(options)[selected]

    with st.spinner("Loading transcripts..."):
        transcripts = list_transcripts_for_record(svc, cr_name)

    if not transcripts:
        st.info("ℹ️ No transcripts found. The host may not have enabled transcription for this meeting.")
    else:
        # Sort by createTime if available
        transcripts_sorted = sorted(transcripts, key=lambda t: t.get("createTime", ""))
        t_labels = [f"{i+1}. {t.get('name')}" for i, t in enumerate(transcripts_sorted)]
        t_selected = st.selectbox("Select a transcript", t_labels, index=len(t_labels)-1)
        t_name = transcripts_sorted[t_labels.index(t_selected)]["name"]

        with st.spinner("Loading transcript content..."):
            raw_entries = fetch_entries_for_transcript(svc, t_name)
        entries = [normalize_entry(e) for e in raw_entries]

        if not entries:
            st.warning("⚠️ Transcript has no entries.")
        else:
            # Transcript Summary Section
            st.markdown("---")
            st.markdown("### 📊 Transcript Summary")
            
            # Calculate stats
            total_chars = sum(len(e["text"]) for e in entries)
            unique_speakers = sorted(set(e["speaker"] for e in entries))
            duration_minutes = len(entries) * 0.5  # Rough estimate
            
            # Display summary in columns
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📝 Entries", len(entries))
            with col2:
                st.metric("👥 Speakers", len(unique_speakers))
            with col3:
                st.metric("📄 Characters", f"{total_chars:,}")
            with col4:
                st.metric("⏱️ Est. Duration", f"{duration_minutes:.0f} min")
            
            # Speakers list
            st.markdown(f"**Speakers:** {', '.join(unique_speakers)}")
            
            # Quick actions
            col1, col2, col3 = st.columns(3)
            with col1:
                txt = as_text(entries)
                st.download_button(
                    "📥 Download Transcript",
                    data=txt.encode("utf-8"),
                    file_name="meet_transcript.txt",
                    mime="text/plain",
                    use_container_width=True
                )
            with col2:
                if st.button("👁️ View Full Transcript", use_container_width=True):
                    st.session_state["show_transcript"] = not st.session_state.get("show_transcript", False)
            with col3:
                if st.button("🎯 Extract Action Items", use_container_width=True, type="primary"):
                    st.session_state["extract_action_items"] = True
            
            # Show transcript if requested
            if st.session_state.get("show_transcript", False):
                st.markdown("---")
                st.markdown("### 📄 Full Transcript")
                st.dataframe(entries, use_container_width=True)

            # Action Items Section
            st.markdown("---")
            st.markdown("### 🎯 Action Items")
            
            # Initialize action items
            action_items = initialize_action_items()
            
            # Handle action item extraction
            if st.session_state.get("extract_action_items", False):
                with st.spinner("🤖 Analyzing transcript with Gemini AI..."):
                    extracted_items = extract_action_items(txt)
                    if extracted_items:
                        # Add extracted items to todo column
                        for item in extracted_items:
                            action_items["todo"].append(item)
                        st.session_state[ACTION_ITEMS_KEY] = action_items
                        # Save to CSV
                        save_action_items_to_csv(action_items)
                        st.success(f"✅ Extracted {len(extracted_items)} action items!")
                    else:
                        st.warning("⚠️ No action items found in the transcript.")
                st.session_state["extract_action_items"] = False
                st.rerun()
            
            # Manual add action item
            with st.expander("➕ Add Manual Action Item", expanded=False):
                with st.form("add_action_item"):
                    col1, col2 = st.columns(2)
                    with col1:
                        task = st.text_input("Task description", placeholder="Enter task description...")
                        assignee = st.text_input("Assignee", value="Unassigned", placeholder="Who is responsible?")
                    with col2:
                        priority = st.selectbox("Priority", ["Low", "Medium", "High"])
                        deadline = st.text_input("Deadline", placeholder="e.g., Next week, Dec 15")
                    if st.form_submit_button("Add Action Item", use_container_width=True):
                        if task:
                            new_item = {
                                "id": str(uuid.uuid4()),
                                "task": task,
                                "assignee": assignee,
                                "deadline": deadline or "No deadline",
                                "priority": priority,
                                "context": "Manually added"
                            }
                            action_items["todo"].append(new_item)
                            st.session_state[ACTION_ITEMS_KEY] = action_items
                            save_action_items_to_csv(action_items)
                            st.success("✅ Action item added!")
                            st.rerun()
            
            # Kanban Board
            st.markdown("#### 📋 Kanban Board")
            
            # Show summary stats
            total_items = sum(len(items) for items in action_items.values())
            if total_items > 0:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("🔴 To Do", len(action_items["todo"]))
                with col2:
                    st.metric("🟡 In Progress", len(action_items["in_progress"]))
                with col3:
                    st.metric("🟢 Done", len(action_items["done"]))
                with col4:
                    st.metric("📊 Total", total_items)
            
            # Create three columns for the kanban board
            col1, col2, col3 = st.columns(3)
            
            def render_action_item_card(item, status, show_context=True):
                """Render a compact action item card"""
                priority_colors = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}
                priority_icon = priority_colors.get(item['priority'], "⚪")
                
                with st.container():
                    # Card styling
                    st.markdown(f"""
                    <div style="
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 12px;
                        margin: 8px 0;
                        background-color: #fafafa;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    ">
                        <div style="font-weight: bold; margin-bottom: 8px;">{item['task']}</div>
                        <div style="font-size: 0.9em; color: #666; margin-bottom: 4px;">
                            👤 {item['assignee']} • {priority_icon} {item['priority']}
                        </div>
                        <div style="font-size: 0.9em; color: #666;">
                            📅 {item['deadline']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Context expander
                    if show_context and item['context'] != 'Manually added':
                        with st.expander("📝 Context", expanded=False):
                            st.markdown(item['context'])
                    
                    # Action buttons
                    if status == "todo":
                        col_move, col_del = st.columns(2)
                        with col_move:
                            if st.button("→ In Progress", key=f"move_todo_{item['id']}", use_container_width=True):
                                move_action_item(item['id'], 'todo', 'in_progress')
                        with col_del:
                            if st.button("🗑️", key=f"del_todo_{item['id']}", use_container_width=True):
                                delete_action_item(item['id'], 'todo')
                    elif status == "in_progress":
                        col_left, col_right, col_del = st.columns(3)
                        with col_left:
                            if st.button("←", key=f"move_back_{item['id']}", use_container_width=True):
                                move_action_item(item['id'], 'in_progress', 'todo')
                        with col_right:
                            if st.button("→", key=f"move_done_{item['id']}", use_container_width=True):
                                move_action_item(item['id'], 'in_progress', 'done')
                        with col_del:
                            if st.button("🗑️", key=f"del_progress_{item['id']}", use_container_width=True):
                                delete_action_item(item['id'], 'in_progress')
                    elif status == "done":
                        col_move, col_del = st.columns(2)
                        with col_move:
                            if st.button("←", key=f"move_back_done_{item['id']}", use_container_width=True):
                                move_action_item(item['id'], 'done', 'in_progress')
                        with col_del:
                            if st.button("🗑️", key=f"del_done_{item['id']}", use_container_width=True):
                                delete_action_item(item['id'], 'done')
            
            with col1:
                st.markdown("#### 🔴 To Do")
                todo_items = action_items["todo"]
                if not todo_items:
                    st.info("No items in To Do")
                else:
                    for item in todo_items:
                        render_action_item_card(item, "todo")
            
            with col2:
                st.markdown("#### 🟡 In Progress")
                in_progress_items = action_items["in_progress"]
                if not in_progress_items:
                    st.info("No items in Progress")
                else:
                    for item in in_progress_items:
                        render_action_item_card(item, "in_progress")
            
            with col3:
                st.markdown("#### 🟢 Done")
                done_items = action_items["done"]
                if not done_items:
                    st.info("No completed items")
                else:
                    for item in done_items:
                        render_action_item_card(item, "done")
            
            # Export and Management Section
            if any(action_items.values()):
                st.markdown("---")
                st.markdown("#### 📤 Export & Management")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    # Quick CSV Export
                    csv_data = []
                    for status, items in action_items.items():
                        for item in items:
                            csv_data.append({
                                'id': item['id'],
                                'task': item['task'],
                                'assignee': item['assignee'],
                                'deadline': item['deadline'],
                                'priority': item['priority'],
                                'context': item['context'],
                                'status': status,
                                'created_date': datetime.now().isoformat()
                            })
                    
                    if csv_data:
                        df = pd.DataFrame(csv_data)
                        csv_string = df.to_csv(index=False)
                        st.download_button(
                            "📊 Export CSV",
                            data=csv_string,
                            file_name=f"action_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            use_container_width=True,
                            help="Download all action items as CSV"
                        )
                
                with col2:
                    # JSON Export
                    export_data = {
                        "meeting_info": {
                            "transcript_name": t_name,
                            "extraction_date": datetime.now().isoformat(),
                            "total_items": sum(len(items) for items in action_items.values())
                        },
                        "action_items": action_items
                    }
                    st.download_button(
                        "📄 Export JSON",
                        data=json.dumps(export_data, indent=2),
                        file_name=f"action_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        use_container_width=True,
                        help="Download complete data as JSON"
                    )
                
                with col3:
                    # Clear all action items
                    if st.button("🗑️ Clear All", use_container_width=True, type="secondary"):
                        st.session_state[ACTION_ITEMS_KEY] = {"todo": [], "in_progress": [], "done": []}
                        save_action_items_to_csv(st.session_state[ACTION_ITEMS_KEY])
                        st.success("✅ All action items cleared!")
                        st.rerun()
                
                # Import section
                st.markdown("#### 📁 Import Action Items")
                uploaded_file = st.file_uploader(
                    "Upload CSV file to import action items", 
                    type=['csv'], 
                    help="Upload a CSV file with columns: task, assignee, deadline, priority, context, status"
                )
                if uploaded_file is not None:
                    try:
                        df = pd.read_csv(uploaded_file)
                        imported_items = {"todo": [], "in_progress": [], "done": []}
                        
                        for _, row in df.iterrows():
                            item = {
                                'id': str(uuid.uuid4()),  # Generate new ID to avoid conflicts
                                'task': row['task'],
                                'assignee': row['assignee'],
                                'deadline': row['deadline'],
                                'priority': row['priority'],
                                'context': row['context']
                            }
                            status = row['status']
                            if status in imported_items:
                                imported_items[status].append(item)
                        
                        # Merge with existing items
                        for status in imported_items:
                            st.session_state[ACTION_ITEMS_KEY][status].extend(imported_items[status])
                        
                        save_action_items_to_csv(st.session_state[ACTION_ITEMS_KEY])
                        st.success(f"✅ Imported {sum(len(items) for items in imported_items.values())} action items!")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error importing CSV: {str(e)}")
else:
    # Empty state with better visual design
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align: center; padding: 2rem; color: #666;">
            <h3 style="color: #999; margin-bottom: 1rem;">🔍 Ready to Analyze Your Meeting?</h3>
            <p style="font-size: 1.1rem; margin-bottom: 0;">Search for a meeting above to view transcripts and extract action items</p>
        </div>
        """, unsafe_allow_html=True)

# ----------------------------
# Footer
# ----------------------------
st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 1rem; color: #666; font-size: 0.9rem;">
    <p style="margin: 0;">ℹ️ Transcripts are available only if the host enabled transcription and your account has permission to view the artifact.</p>
    <p style="margin: 0.5rem 0 0 0;">🔒 This app uses read-only Meet scopes • No meeting bot required • Secure OAuth authentication</p>
</div>
""", unsafe_allow_html=True)
