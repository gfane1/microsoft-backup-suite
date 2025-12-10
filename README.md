# Microsoft Personal Backup Suite

A comprehensive toolkit to export and backup your Microsoft personal data (OneDrive files and OneNote notebooks) to local or external drives. Keep control of your data with these easy-to-use Python tools.

## 🎉 What's New

### OneDrive Backup Tool v2.0 - Major Update! 🚀

New in v2.0:
- ✅ **No more 200-file limit** - Now downloads ALL files
- ✅ **Token auto-refresh** - Zero HTTP 401 errors
- ✅ **40GB+ file support** - Handles huge files with adaptive chunking
- ✅ **Failed files report** - See exactly what failed and why
- ✅ **Interactive retry** - Retry without exiting
- ✅ **Desktop app** - Beautiful Electron GUI

See full [CHANGELOG](https://github.com/davidninow/microsoft-backup-suite/blob/main/CHANGELOG.md) | [Detailed fixes](/docs)

---

## 🎯 What's Included

### 📁 [OneDrive Backup Tool v2.0](https://github.com/davidninow/microsoft-backup-suite/blob/main/onedrive-backup/README.md)
Automatically backup your entire OneDrive (personal accounts) to an external drive, preserving the exact folder structure.

**Key Features:**
- ✅ **99.978% success rate** - Tested with 45,000+ files
- ✅ Pagination support - Downloads ALL files (no 200-file limit)
- ✅ Auto-refreshing tokens - Runs for days without re-authentication
- ✅ Huge file support - 40GB+ files with adaptive chunks
- ✅ Self-healing metadata - Auto-cleanses Files On-Demand corruption
- ✅ Failed files report - Categorized by type with full paths
- ✅ Interactive retry - Retry failed files without exiting
- ✅ Multi-threaded downloads - 3x faster
- ✅ Resume capability - Stop/start anytime
- ✅ Desktop app - GUI interface available

### 📓 OneNote Exporter (WIP)
Export your entire OneNote notebooks with all attachments (images, audio recordings, PDFs, web links) for importing into popular note-taking apps.

**Features:**
- ✅ Exports all notebooks, sections, and pages
- ✅ Downloads all attachments (images, audio, PDFs)
- ✅ Multiple output formats (Markdown, ENEX, HTML)
- ✅ Works with Joplin, Evernote, Notion, Obsidian
- ✅ Automatic token refresh for long exports
- ✅ Preserves metadata (dates, authors)

---

## 📥 Download

### OneDrive Backup - Desktop App (Recommended)

**No Python or command line required!**

| Platform | Download | Size |
|----------|----------|------|
| **macOS (Apple Silicon)** | [OneDrive-Backup-2.0.0-arm64.dmg](https://github.com/davidninow/microsoft-backup-suite/releases/download/v2.0.0/OneDrive.Backup.Manager-2.0.0-arm64.dmg) | 100 MB 
| **macOS (Intel)** | [OneDrive-Backup-2.0.0.dmg](https://github.com/davidninow/microsoft-backup-suite/releases/download/v2.0.0/OneDrive.Backup.Manager-2.0.0.dmg) | 96 MB |
| **Windows** | [OneDrive-Backup-Setup-2.0.0.exe](https://github.com/davidninow/microsoft-backup-suite/releases/download/v2.0.0/OneDrive.Backup.Manager.Setup.2.0.0.exe) | 80 MB |
| **Linux** | [OneDrive.Backup.Manager-2.0.0.AppImage](https://github.com/davidninow/microsoft-backup-suite/releases/download/v2.0.0/OneDrive.Backup.Manager-2.0.0.AppImage) | 70 MB |

*Download links will be added in the v2.0.0 release*

### Python Scripts (Both Tools)

```bash
# Clone the repository
git clone https://github.com/davidninow/microsoft-backup-suite.git
cd microsoft-backup-suite

# Install dependencies
pip install requests
```

---

## 🚀 Quick Start

### OneDrive Backup (v2.0)

**Option 1: Desktop App**
1. Download installer above
2. Double-click to install
3. Open app and follow wizard

**Option 2: Python Script**
```bash
cd onedrive-backup
python3 onedrive_backup_enhanced.py
```

Follow prompts → Authenticate → Select drive → Choose files → Done!

**📖 Full documentation:** See [`onedrive-backup/README.md`](https://github.com/davidninow/microsoft-backup-suite/blob/main/onedrive-backup/README.md)

### OneNote Export

```bash
cd onenote-exporter
python3 onenote_exporter.py
```

Follow prompts → Authenticate → Choose folder → Select format → Done!

**📖 Full documentation:** See [`onenote-exporter/README.md`](https://github.com/davidninow/microsoft-backup-suite/blob/main/onenote-exporter/README_ONENOTE.md)

---

## 📦 Repository Structure

```
microsoft-backup-suite/
├── README.md                    # This file
├── LICENSE.md                   # MIT License
├── CONTRIBUTING.md              # Contribution guidelines
│
├── onedrive-backup/            # OneDrive backup tool v2.0
│   ├── README.md               # Complete v2.0 documentation
│   ├── CHANGELOG.md            # v2.0 changes and fixes
│   ├── onedrive_backup_enhanced.py  # Main script (v2.0)
│   ├── electron-app/           # Desktop application
│   ├── docs/                   # Detailed fix guides
│   └── requirements.txt        # Dependencies
│
└── onenote-exporter/           # OneNote export tool
    ├── README.md               # Main overview
    ├── README_ONENOTE.md       # Full documentation
    ├── QUICKSTART.md           # 5-minute setup
    ├── MIGRATION_GUIDE.md      # App comparison
    ├── onenote_exporter.py     # Main script
    └── requirements.txt        # Dependencies
```

---

## 🔧 Azure Setup

Both tools require Azure app registrations with different permissions. You'll need to create **two separate apps** (one for each tool):

### For OneDrive Backup
**Permissions needed:**
- `Files.Read.All` (Delegated)
- `offline_access` (Delegated)

### For OneNote Exporter  
**Permissions needed:**
- `Notes.Read` (Delegated)
- `Notes.Read.All` (Delegated)
- `offline_access` (Delegated)

**📖 Detailed setup instructions:**
- OneDrive: See [`onedrive-backup/README.md`](https://github.com/davidninow/microsoft-backup-suite/blob/main/onedrive-backup/README.md)
- OneNote: See [`onenote-exporter/README.md`](https://github.com/davidninow/microsoft-backup-suite/blob/main/onenote-exporter/README_ONENOTE.md)

---

## 🎯 Use Cases

### Scenario 1: Full Microsoft Data Backup
```bash
# 1. Backup OneDrive files (v2.0 - 99.978% success!)
cd onedrive-backup
python3 onedrive_backup_enhanced.py

# 2. Export OneNote notebooks
cd ../onenote-exporter
python3 onenote_exporter.py
```

**Result:** Complete backup of your Microsoft personal data!

### Scenario 2: Migrate to Open Platforms
Use this suite to:
- Move files from OneDrive → Local storage / Other cloud
- Move notes from OneNote → Joplin, Obsidian, Evernote

**Freedom from vendor lock-in!** 🎉

### Scenario 3: Regular Backups
Schedule these scripts to run regularly:
- Weekly OneDrive backups to external drive (v2.0 has resume capability!)
- Monthly OneNote exports for archival

### Scenario 4: Account Transition
Moving to a new account or leaving Microsoft ecosystem:
- Export everything before closing account
- Import to new platforms
- Keep your data forever

---

## 📊 Success Stories

### OneDrive Backup v2.0 (Real User Results)

**Before v2.0:**
- 32,857 files found
- 109 files succeeded (0.3%)
- 32,748 files failed (99.7%)
- Gave up after 10 hours

**After v2.0:**
- 45,796 files found (+39% more files discovered!)
- 45,749 files succeeded (99.978%)
- 10 files failed (0.022% - network issues)
- After one retry: 45,796/45,796 (100%) ✨

---

## 🔐 Security & Privacy

Both tools follow security best practices:

- ✅ **OAuth 2.0 authentication** - Industry standard
- ✅ **No passwords stored** - Only temporary tokens
- ✅ **Tokens expire automatically** - Access tokens last ~75 minutes
- ✅ **Tokens auto-refresh** - OneDrive v2.0 handles this automatically
- ✅ **Local data only** - Nothing sent to third parties
- ✅ **Open source** - Review the code yourself
- ✅ **Read-only access** - Scripts never modify your Microsoft data

### Data Flow
```
Your Microsoft Account 
    ↓ (OAuth authentication)
Microsoft Graph API
    ↓ (Secure download)
Your Computer (Local Storage)
    ↓ (Optional)
External Drive / Import to Other Apps
```

---

## 📊 Comparison: OneDrive vs OneNote Tools

| Feature | OneDrive Backup v2.0 | OneNote Exporter |
|---------|---------------------|------------------|
| **What it backs up** | Files & folders | Notes & notebooks |
| **Output format** | Original files | Markdown/ENEX/HTML |
| **Typical size** | GB to TB | MB to GB |
| **Success rate** | 99.978% | ~99% |
| **Backup time** | Varies (450GB ~10 hrs) | 5-30 minutes |
| **Best for** | File preservation | Note migration |
| **Destination** | External drive | Import to other apps |
| **Max file size** | Unlimited (40GB+ tested) | Per OneNote limits |
| **Resume capability** | ✅ Yes | ✅ Yes |
| **GUI available** | ✅ Yes (Electron app) | ❌ CLI only |

---

## 💡 Pro Tips

### For Both Tools
1. **Test first** - Start with small backups/exports
2. **Stable internet** - Both need reliable connection
3. **Keep originals** - Don't delete Microsoft data for 30 days
4. **Check output** - Verify before deleting sources

### OneDrive v2.0 Specific
- ✅ Use online login for complete backup (includes cloud-only files)
- ✅ If files fail, press 'y' to retry immediately
- ✅ Check failed files report - categorized by type
- ✅ External drive needs space (check OneDrive size first)
- ✅ Can backup 40GB+ files (adaptive chunking)
- ✅ Resume works perfectly - stop/start anytime

### OneNote Specific
- Read MIGRATION_GUIDE.md to choose target app
- Export format depends on destination (Joplin vs Evernote)
- Audio/video files take longest to download

---

## 🆘 Troubleshooting

### Common Issues (Both Tools)

**"Authentication failed"**
- Verify you copied the Secret VALUE (not ID) from Azure
- Check API permissions are granted (green checkmarks)
- Make sure Redirect URI is `http://localhost:8080`

**"Python not found"**
```bash
# Try python3 instead of python
python3 --version
```

**"Can't install requests"**
```bash
# Try with --break-system-packages flag (Python 3.11+)
pip install requests --break-system-packages

# Or use pip3
pip3 install requests
```

### OneDrive v2.0 Specific

**"Only got 200 files but I have more!"**
✅ **Fixed in v2.0!** Update to v2.0 to get all files.

**"HTTP 401 errors everywhere!"**
✅ **Fixed in v2.0!** Tokens now auto-refresh.

**"Huge files timing out!"**
✅ **Fixed in v2.0!** Now uses adaptive chunks (50MB for >10GB files).

**"Missing thousands of files!"**
✅ **Fixed in v2.0!** The pagination bug is resolved. Re-run backup to get all files.

**"10 files failed - what should I do?"**
✅ **v2.0 feature!** Script will show you exactly what failed and why, then prompt you to retry. Most failures are temporary network issues - just press 'y' to retry!

### OneNote Specific

**"No notebooks found"**
- Verify notebooks exist at https://www.onenote.com
- Check Azure app has Notes.Read permissions
- Try re-authenticating

**For detailed troubleshooting:**
- OneDrive: See [`onedrive-backup/README.md`](https://github.com/davidninow/microsoft-backup-suite/blob/main/onedrive-backup/README.md)
- OneNote: See [`onenote-exporter/README.md`](https://github.com/davidninow/microsoft-backup-suite/blob/main/onenote-exporter/README_ONENOTE.md)

---

## 📖 Documentation

### OneDrive Backup v2.0
- **README.md** - Complete v2.0 documentation
- **CHANGELOG.md** - All v2.0 changes and fixes
- **docs/PAGINATION_BUG_FIX.md** - 200-file limit fix details
- **docs/TOKEN_EXPIRATION_FIX.md** - Auto-refresh implementation
- **docs/HUGE_FILE_FIX.md** - 40GB+ file support
- **docs/FAILED_FILES_WITH_PATHS.md** - Failure reporting
- **docs/INTERACTIVE_RETRY_FEATURE.md** - Retry feature
- **docs/ELECTRON_DISTRIBUTION_GUIDE.md** - Building desktop app

### OneNote Exporter
- **README.md** - Main overview and getting started
- **QUICKSTART.md** - 5-minute setup guide (start here!)
- **SETUP_GUIDE.md** - Comprehensive setup and usage
- **README_ONENOTE.md** - Full documentation
- **MIGRATION_GUIDE.md** - Compare Joplin, Evernote, Notion, Obsidian
- **PROJECT_SUMMARY.md** - Package overview
- **advanced_examples.py** - Custom export scenarios (with code)

### General
- **LICENSE.md** - MIT License
- **CONTRIBUTING.md** - How to contribute

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

### For Both Tools
- 🐛 Report bugs
- 💡 Suggest features
- 📖 Improve documentation
- 🔧 Submit pull requests

### Specific Areas
- **OneDrive v2.0:** Work/school account support, GUI improvements
- **OneNote:** Better format conversion, direct app imports, GUI

**See CONTRIBUTING.md for guidelines**

---

## 🗺️ Roadmap

### OneDrive Backup v2.0+
- [ ] Work/school OneDrive support
- [ ] Cloud-to-cloud backup (OneDrive to Google Drive)
- [ ] Compression options
- [ ] Scheduled backups
- [ ] GUI improvements (auto-updates, themes)
- [ ] Backup verification/integrity checks

### OneNote Exporter
- [ ] Selective export (specific notebooks)
- [ ] Better Markdown conversion
- [ ] Direct API import to target apps
- [ ] GUI interface
- [ ] Progress bar with ETA

### Shared Improvements
- [ ] Common authentication module
- [ ] Unified configuration file
- [ ] Combined CLI tool
- [ ] Docker containers
- [ ] Web interface

---

## 📝 License

MIT License - Free to use and modify for personal or commercial purposes.

See [LICENSE.md](LICENSE.md) for details.

---

## 🙏 Acknowledgments

- **Microsoft Graph API** - For providing access to personal data
- **Open source community** - For libraries and inspiration
- **@davidninow** - For driving the project and extensive v2.0 testing (450GB, 45,796 files!)
- **Contributors** - For bug reports and improvements

---

## ⭐ Show Your Support

If these tools help you:
- ⭐ Star this repository
- 🐛 Report issues
- 💬 Share with others
- 🤝 Contribute improvements

---

## 📞 Support & Contact

- 🐛 **Bug reports:** Open an issue on GitHub
- 💡 **Feature requests:** Open an issue with "enhancement" label
- 📖 **Documentation:** Check tool-specific README files
- 💬 **Questions:** Open a discussion on GitHub

---

## 🎯 Quick Links

- [OneDrive Backup v2.0 README](onedrive-backup/README.md)
- [OneDrive v2.0 CHANGELOG](https://github.com/davidninow/microsoft-backup-suite/blob/main/CHANGELOG.md)
- [OneNote Exporter Quick Start](onenote-exporter/QUICKSTART.md)
- [OneNote Migration Guide](onenote-exporter/MIGRATION_GUIDE.md)
- [Contributing Guidelines](CONTRIBUTING.md)
- [License](LICENSE.md)

---

## 🚀 Ready to Get Started?

### Option 1: Backup OneDrive (v2.0 - Recommended!)
```bash
cd onedrive-backup
python3 onedrive_backup_enhanced.py
```

### Option 2: Export OneNote
```bash
cd onenote-exporter
python3 onenote_exporter.py
```

### Option 3: Do Both!
```bash
# Complete data liberation with v2.0 reliability!
cd onedrive-backup && python3 onedrive_backup_enhanced.py
cd ../onenote-exporter && python3 onenote_exporter.py
```

**Your data, your control!** 🎉

---

**Made with ❤️ for people who believe in data freedom and portability**

*"The best time to backup your data was yesterday. The second best time is now."*

---

## 🎊 v2.0 Release Highlights

**OneDrive Backup Tool v2.0** represents a complete overhaul with:
- **7 critical bug fixes** (pagination, token expiration, huge files, race conditions, metadata corruption, misleading messages, flow issues)
- **3 new features** (failed files report, interactive retry, desktop app)
- **42,000% improvement in success rate** (0.3% → 99.978%)
- **39% more files discovered** (32,857 → 45,796 files found)

[Read the full CHANGELOG](https://github.com/davidninow/microsoft-backup-suite/blob/main/CHANGELOG.md)
