# OneNote Exporter v3.2

A Python tool to export your entire OneNote notebooks with all attachments (images, audio recordings, PDFs, web links, etc.) for importing into popular note-taking apps like **Joplin**, **Obsidian**, **Evernote**, and **Notion**.

## 🆕 What's New in v3.2

- ✅ **Joplin/Obsidian Compatible Markdown** - YAML front matter with proper metadata
- ✅ **Fixed Image Export** - Images now display correctly with local file paths
- ✅ **Improved HTML→Markdown** - Better conversion of images, lists, code blocks, formatting
- ✅ **Parent/Child Page Support** - Preserves page hierarchy from OneNote
- ✅ **Navigable Index** - Clickable `index.md` with full notebook structure
- ✅ **81 Unit Tests** - Comprehensive test coverage for reliability
- ✅ **Index Builder Module** - Modular, testable code architecture

### Previous Versions
- **v3.0**: Full pagination, preflight inventory, interactive selection, robust retry
- **v2.0**: Section groups, settings file, progress reporting

## ✨ Features

- **Complete Export**: Exports all notebooks, section groups, sections, and pages from OneNote
- **Full Pagination**: Correctly handles Microsoft Graph API pagination (no more missing pages!)
- **Preflight Scan**: Generates inventory before export to verify what Graph can see
- **Preserves Attachments**: Downloads all embedded files:
  - 🖼️ Images (PNG, JPG, etc.)
  - 🎵 Audio recordings (M4A, WAV, etc.)
  - 📄 PDF documents
  - 🔗 Web embeds and links
- **Multiple Formats**: Exports to:
  - Markdown (for Joplin)
  - ENEX (for Evernote)
  - HTML (universal format)
- **Preserves Structure**: Maintains your notebook → section group → section → page hierarchy
- **Metadata Preservation**: Keeps creation dates, modification dates, and authors
- **Settings File**: Configure defaults in `settings.json` (client_id, output path, format)
- **Resume Support**: Can handle large exports with automatic token refresh

## 📋 Requirements

- Python 3.6+
- Microsoft personal account with OneNote
- Azure app registration (free, one-time setup)
- Storage space for exported notebooks

## 🔧 Installation

1. **Clone or download this repository**

2. **Install required Python packages:**
```bash
pip install requests
```

That's it! The script uses only built-in Python libraries plus `requests`.

## 🚀 Azure Setup (One-Time)

Before using the tool, you need to create an Azure app registration. This gives the script permission to read your OneNote notebooks.

### Step 1: Create App Registration

1. Go to [Microsoft Entra Admin Center](https://entra.microsoft.com/)
2. Sign in with your personal Microsoft account
3. Navigate to **Identity** → **Applications** → **App registrations**
4. Click **+ New registration**
5. Fill out the form:
   - **Name:** `OneNote Exporter`
   - **Supported account types:** "Accounts in any organizational directory and personal Microsoft accounts"
   - **Redirect URI:** Platform: `Web`, URI: `http://localhost:8080`
6. Click **Register**

### Step 2: Get Application (Client) ID

1. On the app's **Overview** page, copy the **Application (client) ID**
2. Save this - you'll need it when running the script

### Step 3: Create Client Secret

1. Go to **Certificates & secrets** (left sidebar)
2. Click **+ New client secret**
3. Description: `OneNote Exporter Secret`
4. Expiration: Choose `24 months` (maximum)
5. Click **Add**
6. **IMMEDIATELY copy the Value** (you can only see it once!)
7. Save this with your Client ID

### Step 4: Set API Permissions

1. Go to **API permissions** (left sidebar)
2. Click **+ Add a permission**
3. Select **Microsoft Graph**
4. Select **Delegated permissions**
5. Search for and add these permissions:
   - `Notes.Read`
   - `Notes.Read.All`
   - `offline_access`
6. Click **Add permissions**
7. Click **Grant admin consent for [Your Account]** and confirm

You should see green checkmarks next to all permissions.

## 📖 Usage

### Quick Start with Settings File

1. **Copy the example settings file:**
```bash
cp settings.example.json settings.json
```

2. **Edit `settings.json` with your Client ID:**
```json
{
  "auth": {
    "client_id": "YOUR_CLIENT_ID_HERE",
    "tenant": "consumers"
  },
  "export": {
    "output_root": "C:/OneNote-Exports",
    "format": "joplin",
    "include_notebooks": [],
    "exclude_notebooks": []
  }
}
```

> **⚠️ Security Note:** The `client_secret` is NEVER stored in settings.json. You will always be prompted to enter it at runtime.

3. **Run the exporter:**
```bash
python onenote_exporter.py
```

### Command Line Options

```bash
# Basic usage
python onenote_exporter.py

# Preflight only - scan and generate index files without exporting
python onenote_exporter.py --preflight-only

# Override output directory
python onenote_exporter.py --output "D:/Backups/OneNote"

# No pause at end (for scripted runs)
python onenote_exporter.py --no-pause

# Use a different settings file
python onenote_exporter.py --settings my_settings.json

# Combine options
python onenote_exporter.py --preflight-only --output "C:/Temp" --no-pause
```

### Settings File Options

| Setting | Description | Default |
|---------|-------------|---------|
| `auth.client_id` | Azure App Client ID | *(prompt)* |
| `auth.tenant` | Azure tenant (`consumers` for personal) | `consumers` |
| `export.output_root` | Export destination path | *(prompt)* |
| `export.format` | `joplin`, `enex`, `both`, or `raw_html` | `joplin` |
| `export.include_notebooks` | Only export these notebooks (empty = all) | `[]` |
| `export.exclude_notebooks` | Skip these notebooks | `[]` |

### Basic Usage (No Settings File)

1. **Run the script:**
```bash
python3 onenote_exporter.py
```

2. **Follow the prompts:**
   - Enter your **Application (client) ID**
   - Enter your **Client Secret** (always prompted, hidden input)
   - Enter `consumers` for Tenant ID (for personal accounts)
   - Browser opens → sign in and approve permissions
   - Copy the redirect URL from browser and paste into terminal
   - Enter destination path (e.g., `C:/OneNote-Exports`)
   - Choose export format

3. **Wait for completion:**
   - Preflight scan shows all notebooks/sections/pages found
   - Export proceeds with progress output
   - Final summary compares preflight totals to exported totals
   - Press Enter to exit (or use `--no-pause`)

### Preflight Only Mode

To see what Microsoft Graph can access without exporting:

```bash
python onenote_exporter.py --preflight-only --output "C:/Temp"
```

This generates:
- `index.md` - Human-readable inventory
- `index.json` - Machine-readable inventory

Compare these totals with your OneNote desktop app to verify Graph API access.

### Export Format Options

When running the script, you can choose:

1. **Joplin** (default) - Markdown files
2. **ENEX** - Evernote export files
3. **Both** - Creates Markdown and ENEX files
4. **Raw HTML** - Only raw HTML files (no conversion)

## 📁 Output Structure

Your export will be organized as follows:

```
OneNote_Export_20241215_143052/
├── index.md                           # Preflight inventory (human-readable)
├── index.json                         # Preflight inventory (machine-readable)
├── export_summary.json                # Export statistics
├── error_log.json                     # Errors if any occurred
│
├── Personal Notebook/
│   ├── Quick Notes/
│   │   ├── meeting_notes.html         # Raw HTML
│   │   ├── meeting_notes_attachments/ # All attachments
│   │   │   ├── image_1.png
│   │   │   ├── audio_1.m4a
│   │   │   └── document.pdf
│   │   ├── joplin/                    # Markdown files for Joplin
│   │   │   └── meeting_notes.md
│   │   └── evernote/                  # ENEX files for Evernote
│   │       └── meeting_notes.enex
│   │
│   └── Section Group Name/            # Section groups preserved!
│       └── Nested Section/
│           └── ...
│
├── Work Notebook/
│   └── ... (same structure)
│
└── ... (all your notebooks)
```

## 📥 Importing to Note-Taking Apps

### Joplin

1. Open Joplin desktop application
2. Go to **File** → **Import** → **MD - Markdown (Directory)**
3. Select the `joplin` folder from any exported notebook
4. Joplin will import all markdown files

**For attachments:**
- Copy the `*_attachments` folders to your Joplin resources directory:
  - **Mac/Linux:** `~/.config/joplin-desktop/resources/`
  - **Windows:** `%USERPROFILE%\.config\joplin-desktop\resources\`
- Or use Joplin's **File** → **Import** → **MD - Markdown + Attachments**

### Evernote

1. Open Evernote desktop application
2. Go to **File** → **Import Notes** → **Import Evernote Export File (.enex)**
3. Select ENEX files from the `evernote` folder
4. Choose the notebook to import into
5. Click **Import**

**Notes:**
- Import one ENEX file at a time for better organization
- Evernote has attachment size limits (25MB per note for free accounts)
- Some formatting may need adjustment

### Notion

1. In Notion, create a new page
2. Click **Import** → **HTML**
3. Select HTML files from the exported notebooks
4. Manually drag attachments from `*_attachments` folders into the imported pages

### Other Apps

Most note-taking apps support:
- **HTML import** - Use the raw HTML files
- **Markdown import** - Use the Joplin markdown files
- **Manual copy-paste** - Open HTML files in a browser and copy content

## 🎯 What Gets Exported

### Supported Content Types

✅ **Text and Formatting**
- Headers, paragraphs, lists
- Bold, italic, underline
- Links and tables

✅ **Images**
- Embedded images
- Pasted screenshots
- Drawn sketches

✅ **Audio**
- Voice recordings
- Audio notes
- Embedded audio files

✅ **Files**
- PDF documents
- Office documents (links)
- Other embedded files

✅ **Metadata**
- Page creation date
- Last modified date
- Author information

### Known Limitations

⚠️ **Not Supported:**
- OneNote-specific features (tags, to-do checkboxes)
- Ink/pen drawings (exported as images)
- Equation objects (may export as images)
- Some embedded objects (Office docs may be links only)
- Page backgrounds and themes

⚠️ **Partial Support:**
- Complex tables (may need reformatting)
- Some advanced formatting (may be simplified)
- Large video files (size limits apply)

## 🔍 Troubleshooting

### Authentication Issues

**"Invalid client secret"**
- You copied the Secret ID instead of the Value
- Create a new client secret in Azure
- Make sure to copy the **Value** column

**"Browser doesn't open"**
- Try a different browser as your default
- Manually copy the authentication URL from terminal
- Make sure port 8080 is not blocked

**"Token expired"**
- The script automatically refreshes tokens
- If it fails, run the script again
- You may need to re-authenticate

### Export Issues

**"No notebooks found"**
- Make sure you have OneNote notebooks in your account
- Check API permissions are granted in Azure
- Try signing out and back into OneNote

**"Download failed" errors**
- Some attachments may be too large
- Network timeouts can cause failures
- The script continues exporting other content

**"Out of memory" errors**
- Export notebooks one at a time
- Close other applications
- Consider using a machine with more RAM

### Import Issues

**Joplin: "Import failed"**
- Make sure you're importing the correct format (Markdown)
- Check that markdown files are valid UTF-8
- Import one notebook at a time

**Evernote: "File size limit"**
- Split large notebooks into smaller chunks
- Remove large attachments before importing
- Consider upgrading Evernote plan

## 🛡️ Security & Privacy

- **Your credentials are never stored** - only used during authentication
- **Access tokens are temporary** - expire after ~75 minutes
- **Refresh tokens last 90 days** - auto-renewed when used
- **All data is stored locally** - nothing sent to third parties
- **OAuth 2.0 standard** - industry-standard secure authentication

### Best Practices

- Keep your Client Secret private
- Don't commit credentials to version control
- Delete exported files after importing
- Revoke app permissions in Azure when done (optional)

## 🤝 Contributing

Contributions welcome! Please:
- Follow the existing code style
- Test with real OneNote notebooks
- Update documentation for new features
- Submit pull requests to the main branch

## 📝 License

MIT License - see LICENSE file for details

## 🐛 Known Issues

1. **Large exports may be slow** - Graph API has rate limits
2. **Some formatting lost** - Conversion from HTML to Markdown is imperfect
3. **Embedded Office docs** - May export as links, not files
4. **OneNote equations** - Export as images, not editable equations
5. **Handwriting** - Exported as images, not searchable text

## 🗺️ Roadmap

Future improvements:
- [ ] Selective export (specific notebooks/sections)
- [ ] Incremental export (only new/modified pages)
- [ ] Better Markdown conversion (using Pandoc - see `README_PANDOC_CLEANUP.md`)
- [ ] Direct import to Joplin/Evernote APIs
- [ ] GUI interface for easier use
- [ ] Progress bar with ETA
- [ ] Parallel downloads for speed
- [ ] OCR for handwritten notes

## 🧪 Testing

Run the unit tests:

```bash
cd onenote-exporter
python -m pytest test_onenote_exporter.py -v
```

Or with unittest:

```bash
python -m unittest test_onenote_exporter -v
```

### Manual Test Plan

1. **Preflight Only Test:**
   ```bash
   python onenote_exporter.py --preflight-only --output ./test_output
   ```
   - Verify `index.md` lists all expected notebooks
   - Compare page counts to OneNote desktop app

2. **Full Export Test:**
   ```bash
   python onenote_exporter.py --output ./test_output
   ```
   - Verify final summary shows matching preflight/export totals
   - Spot-check exported pages match originals

3. **Settings File Test:**
   - Create `settings.json` with your `client_id`
   - Run without any arguments
   - Verify client_id is loaded but secret is still prompted

## 💡 Tips

1. **Start small** - Test with a small notebook first
2. **Check permissions** - Make sure Azure app has correct permissions
3. **Stable internet** - Large exports need reliable connection
4. **Review exports** - Check a few pages before deleting OneNote
5. **Backup originals** - Keep OneNote notebooks until verified
6. **Import gradually** - Don't import everything at once

## 📞 Support

For issues:
1. Check the Troubleshooting section above
2. Review Azure permissions settings
3. Check Microsoft Graph API status
4. Open an issue on GitHub with:
   - Error messages
   - Export summary
   - Python version
   - OS information

## 🙏 Acknowledgments

- Microsoft Graph API documentation
- OneNote export format research
- Community feedback and testing

---

**Made with ❤️ for OneNote users transitioning to open platforms**
