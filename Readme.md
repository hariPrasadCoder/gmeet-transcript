# 📝 Google Meet Transcript Analyzer

A powerful Streamlit application that extracts and analyzes Google Meet transcripts, automatically identifying action items using AI, and providing a comprehensive task management system.

## ✨ Features

- **🔐 Secure Authentication**: OAuth 2.0 integration with Google Meet API
- **🔍 Smart Search**: Find meetings by code or time range
- **📄 Transcript Management**: View, download, and analyze meeting transcripts
- **🤖 AI-Powered Action Item Extraction**: Uses Google's Gemini AI to automatically identify tasks, assignees, deadlines, and priorities
- **📋 Kanban Board**: Interactive task management with drag-and-drop functionality
- **📊 Export Options**: Download transcripts and action items as TXT, CSV, or JSON
- **📁 Import/Export**: Bulk import action items from CSV files
- **👥 Speaker Analysis**: Track participants and speaking patterns
- **📈 Meeting Analytics**: Duration, character count, and participant insights

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Google Cloud Platform account
- Google Meet API access

### 1. Google Cloud Setup

1. **Create a Google Cloud Project**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one

2. **Enable Google Meet API**
   - Navigate to "APIs & Services" > "Library"
   - Search for "Google Meet API" and enable it

3. **Configure OAuth 2.0**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth 2.0 Client ID"
   - Choose "Web application" as the application type
   - Add authorized redirect URI: `http://localhost:8501/`
   - Note down your Client ID and Client Secret

### 2. Environment Configuration

1. **Copy the environment template**:
   ```bash
   cp env.sample .env
   ```

2. **Fill in your credentials** in `.env`:
   ```env
   GOOGLE_OAUTH_CLIENT_ID=your_client_id_here
   GOOGLE_OAUTH_CLIENT_SECRET=your_client_secret_here
   GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8501/
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

   **Note**: Get your Gemini API key from [Google AI Studio](https://aistudio.google.com/app/api-keys)

### 3. Installation & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
streamlit run app.py
```

### 4. First Use

1. **Connect Google Account**: Click "Connect Google Account" and complete the OAuth consent flow
2. **Search for Meetings**: Use either:
   - **Meeting Code**: Enter the meeting code (e.g., `abc-mnop-xyz`)
   - **Time Range**: Select start and end dates/times
3. **Select Transcript**: Choose from available transcripts
4. **Extract Action Items**: Click "Extract Action Items" to use AI analysis
5. **Manage Tasks**: Use the Kanban board to organize and track progress

## 📋 Usage Guide

### Finding Meetings

**By Meeting Code**:
- Enter the meeting code exactly as it appears in the Google Meet URL
- Format: `abc-mnop-xyz` (letters and numbers separated by hyphens)

**By Time Range**:
- Select start and end dates/times in UTC
- Defaults to the last 7 days
- Shows up to 25 most recent meetings

### Managing Action Items

**Automatic Extraction**:
- Click "Extract Action Items" to analyze the transcript with AI
- AI identifies tasks, assignees, deadlines, and priorities
- Items are automatically added to the "To Do" column

**Manual Management**:
- Add custom action items using the "Add Manual Action Item" form
- Move items between columns: To Do → In Progress → Done
- Edit priorities and assignees
- Delete items when no longer needed

**Kanban Board**:
- **🔴 To Do**: New tasks awaiting action
- **🟡 In Progress**: Tasks currently being worked on
- **🟢 Done**: Completed tasks

### Export Options

**Transcript Export**:
- Download as plain text (.txt) file
- Includes timestamps, speakers, and full conversation

**Action Items Export**:
- **CSV**: Spreadsheet format for data analysis
- **JSON**: Complete data structure with metadata
- **Import**: Upload CSV files to bulk import action items

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth Client ID | Yes |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth Client Secret | Yes |
| `GOOGLE_OAUTH_REDIRECT_URI` | OAuth redirect URI | Yes |
| `GEMINI_API_KEY` | Google Gemini API key | Yes |

### API Scopes

The application requests the following Google API scopes:
- `https://www.googleapis.com/auth/meetings.space.readonly` - Read meeting data
- `openid` - OpenID Connect
- `https://www.googleapis.com/auth/userinfo.profile` - User profile information

## 📁 Project Structure

```
gmeet-transcript/
├── app.py                 # Main Streamlit application
├── requirements.txt       # Python dependencies
├── env.sample            # Environment variables template
├── action_items.csv      # Persistent action items storage
├── README.md             # This file
└── venv/                 # Virtual environment (if used)
```

## 🛠️ Dependencies

- **streamlit**: Web application framework
- **google-auth**: Google authentication
- **google-auth-oauthlib**: OAuth 2.0 flow
- **google-api-python-client**: Google APIs client
- **google-generativeai**: Gemini AI integration
- **pandas**: Data manipulation
- **python-dotenv**: Environment variable management

## 🔒 Security & Privacy

- **Read-Only Access**: Application only reads meeting data, never modifies
- **No Meeting Bot Required**: Uses standard Google Meet API
- **Secure OAuth**: Industry-standard authentication flow
- **Local Storage**: Action items stored locally in CSV format
- **No Data Sharing**: All data remains on your local machine

## 🚨 Troubleshooting

### Common Issues

**"Missing credentials" error**:
- Ensure `.env` file exists and contains all required variables
- Verify Google Cloud OAuth configuration
- Check that redirect URI matches exactly

**"No transcripts found"**:
- Meeting host must enable transcription
- Your account needs permission to view meeting artifacts
- Transcription may take time to process after meeting ends

**"OAuth error"**:
- Clear browser cache and cookies
- Ensure redirect URI is exactly `http://localhost:8501/`
- Check that Google Cloud project has Meet API enabled

**"No action items extracted"**:
- Verify Gemini API key is valid
- Check internet connection
- Try with a shorter transcript segment

### Getting Help

1. Check the [Google Meet API documentation](https://developers.google.com/meet/api)
2. Verify your Google Cloud project configuration
3. Ensure all environment variables are set correctly
4. Check that transcription was enabled for your meetings

## 📝 License

This project is open source. Please ensure you comply with Google's API terms of service when using this application.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

---

**Note**: This application requires Google Meet API access and transcription to be enabled by meeting hosts. Transcripts are only available for meetings where transcription was explicitly enabled.