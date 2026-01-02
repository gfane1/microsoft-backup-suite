# OneNote Web Exporter

A web-based interface for exploring and exporting OneNote notebooks to Joplin-compatible Markdown format.

## 🎯 Features

- **Browse Notebooks** - View all your OneNote notebooks, sections, and page counts
- **Real-time Progress** - See export progress with live updates via Server-Sent Events
- **Joplin Compatible** - Exports to Markdown with YAML front matter and linked images
- **Selective Export** - Choose which notebooks to export
- **Local Images** - All images are downloaded and linked locally

## 📋 Prerequisites

- Python 3.8 or higher
- Microsoft Azure App Registration (see setup below)
- A Microsoft personal account with OneNote notebooks

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd onenote-web-exporter
pip install -r requirements.txt
```

### 2. Configure Azure App

Create an Azure app registration with these settings:

1. Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → App registrations
2. Click **New registration**
3. Name: `OneNote Web Exporter` (or any name)
4. Account types: **Personal Microsoft accounts only**
5. Redirect URI: **Web** → `http://localhost:8080/auth/callback`
6. After creation, note down the **Application (client) ID**
7. Go to **Certificates & secrets** → **New client secret**
8. Copy the secret **Value** (not the ID!)
9. Go to **API permissions** → **Add permission** → **Microsoft Graph** → **Delegated**:
   - `Notes.Read`
   - `Notes.Read.All`
   - `offline_access`
10. Click **Grant admin consent** (if available)

### 3. Run the Application

```bash
python app.py
```

Then open http://localhost:8080 in your browser.

### 4. Configure & Sign In

1. Go to **Settings** page
2. Enter your **Client ID** and **Client Secret**
3. Set your **Export Directory** (where files will be saved)
4. Click **Save Settings**
5. Click **Sign in with Microsoft**

### 5. Export Your Notebooks

1. Go to **Browse Notebooks** to view your notebooks
2. Go to **Export** page
3. Select notebooks to export
4. Click **Start Export**
5. Watch real-time progress as files are created

## 📁 Export Structure

Exports follow this structure for Joplin compatibility:

```
export_directory/
├── Notebook Name/
│   ├── Section Name/
│   │   ├── Page Title.md
│   │   ├── Page Title_attachments/
│   │   │   ├── image1.png
│   │   │   └── image2.jpg
│   │   └── ...
│   └── ...
└── ...
```

### Markdown Format

Each page is exported as Markdown with YAML front matter:

```markdown
---
title: Page Title
created: 2024-01-15T10:30:00Z
modified: 2024-01-20T14:45:00Z
source: onenote
notebook: My Notebook
section: My Section
---

# Page Title

Page content here...

![Image](Page%20Title_attachments/image1.png)
```

## ⚙️ Configuration

Settings are stored in `settings.json` in the project root:

```json
{
    "client_id": "your-client-id",
    "client_secret": "your-client-secret",
    "export_directory": "C:\\Users\\You\\OneNote-Export"
}
```

**Security Note:** The `settings.json` file is listed in `.gitignore` and should never be committed to source control.

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/settings` | GET | Settings page |
| `/browse` | GET | Browse notebooks |
| `/export` | GET | Export page |
| `/auth/login` | GET | Start OAuth flow |
| `/auth/callback` | GET | OAuth callback |
| `/auth/logout` | POST | Clear session |
| `/api/notebooks` | GET | Get notebooks list |
| `/api/settings` | GET/POST | Get/save settings |
| `/api/export/start` | POST | Start export |
| `/api/export/stream` | GET | SSE progress stream |

## 🛠️ Development

### Project Structure

```
onenote-web-exporter/
├── app.py              # Flask application & routes
├── graph_client.py     # Microsoft Graph API client
├── exporter.py         # Export logic with progress
├── requirements.txt    # Python dependencies
├── templates/          # Jinja2 HTML templates
│   ├── index.html      # Dashboard
│   ├── settings.html   # Settings form
│   ├── browse.html     # Notebook browser
│   ├── export.html     # Export page
│   └── auth_result.html # Auth callback
└── static/             # CSS & JavaScript
    ├── style.css       # Styles
    └── app.js          # Client-side JS
```

### Running in Development

```bash
# With Flask debug mode
FLASK_DEBUG=1 python app.py

# Or on Windows
set FLASK_DEBUG=1
python app.py
```

### Technology Stack

- **Backend:** Flask 3.0, Python 3.8+
- **Frontend:** Vanilla JavaScript, CSS (no frameworks)
- **API:** Microsoft Graph API v1.0
- **Authentication:** OAuth 2.0 Authorization Code Flow
- **Real-time:** Server-Sent Events (SSE)
- **Production Server:** Waitress (Windows-friendly)

## 🐛 Troubleshooting

### "Invalid redirect URI"
- Ensure Azure app has redirect URI: `http://localhost:8080/auth/callback`
- Check the URI type is **Web** (not SPA or Public client)

### "No notebooks found"
- Verify you have notebooks at [onenote.com](https://www.onenote.com)
- Check Azure app has `Notes.Read` permission
- Try signing out and back in

### "Export stuck at 0%"
- Check browser console for JavaScript errors
- Ensure the export directory is writable
- Try refreshing and starting again

### Images not appearing in Joplin
- Ensure images are in `PageName_attachments/` folder
- Check image paths in Markdown are relative
- Import the entire notebook folder into Joplin

## 📝 License

MIT License - See [LICENSE.md](../LICENSE.md)

## 🔗 Related

- [OneNote CLI Exporter](../onenote-exporter/) - Command-line version
- [OneDrive Backup Tool](../onedrive-backup/) - Backup OneDrive files
- [Microsoft Graph API](https://docs.microsoft.com/graph/overview) - API documentation
