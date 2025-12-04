# Microsoft Personal Backup Suite

A comprehensive toolkit to export and backup your Microsoft personal data (OneDrive files and OneNote notebooks) to local or external drives. Keep control of your data with these easy-to-use Python tools.

## 🎯 What's Included

### 📁 OneDrive Backup Tool
Automatically backup your entire OneDrive (personal accounts) to an external drive, preserving the exact folder structure.

**Features:**
- ✅ Automatic authentication via Microsoft Graph API
- ✅ Preserves folder structure exactly as in OneDrive
- ✅ Auto-refreshing tokens - can run for days/weeks
- ✅ Real-time progress tracking
- ✅ Handles large backups (500GB+)
- ✅ Resume capability for interrupted downloads

### 📓 OneNote Exporter
Export your entire OneNote notebooks with all attachments (images, audio recordings, PDFs, web links) for importing into popular note-taking apps.

**Features:**
- ✅ Exports all notebooks, sections, and pages
- ✅ Downloads all attachments (images, audio, PDFs)
- ✅ Multiple output formats (Markdown, ENEX, HTML)
- ✅ Works with Joplin, Evernote, Notion, Obsidian
- ✅ Automatic token refresh for long exports
- ✅ Preserves metadata (dates, authors)

## 🚀 Quick Start

### Prerequisites
- Python 3.6+
- Microsoft personal account
- Azure app registration(s) - **free, one-time setup**
- External drive (for OneDrive backup) or destination folder

### Installation

```bash
# Clone the repository
git clone https://github.com/davidninow/microsoft-backup-suite.git
cd microsoft-backup-suite

# Install dependencies
pip install requests
```

### OneDrive Backup

```bash
cd onedrive-backup
python3 onedrive_backup.py
```

Follow the prompts to:
1. Authenticate with your Microsoft account
2. Select your external drive
3. Choose what to backup (documents, pictures, or both)

**📖 Full documentation:** See `onedrive-backup/README.md`

### OneNote Export

```bash
cd onenote-exporter
python3 onenote_exporter.py
```

Follow the prompts to:
1. Authenticate with your Microsoft account
2. Choose destination folder
3. Select export format (Joplin, Evernote, both)

**📖 Full documentation:** See `onenote-exporter/README.md`

## 📦 Repository Structure

```
microsoft-backup-suite/
├── README.md                    # This file
├── LICENSE.md                   # MIT License
├── CONTRIBUTING.md              # Contribution guidelines
│
├── onedrive-backup/            # OneDrive backup tool
│   ├── README.md               # Detailed OneDrive docs
│   ├── onedrive_backup.py      # Main backup script
│   └── requirements.txt        # Dependencies
│
└── onenote-exporter/           # OneNote export tool
    ├── README.md               # Main overview & getting started
    ├── README_ONENOTE.md       # Full documentation
    ├── QUICKSTART.md           # 5-minute setup guide
    ├── SETUP_GUIDE.md          # Complete setup guide
    ├── MIGRATION_GUIDE.md      # App comparison & import guide
    ├── PROJECT_SUMMARY.md      # Package overview
    ├── onenote_exporter.py     # Main export script
    ├── advanced_examples.py    # Custom export scenarios
    └── requirements.txt        # Dependencies
```

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
- OneDrive: See `onedrive-backup/README.md`
- OneNote: See `onenote-exporter/QUICKSTART.md`

## 🎯 Use Cases

### Scenario 1: Full Microsoft Data Backup
```bash
# 1. Backup OneDrive files
cd onedrive-backup
python3 onedrive_backup.py

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
- Weekly OneDrive backups to external drive
- Monthly OneNote exports for archival

### Scenario 4: Account Transition
Moving to a new account or leaving Microsoft ecosystem:
- Export everything before closing account
- Import to new platforms
- Keep your data forever

## 🔐 Security & Privacy

Both tools follow security best practices:

- ✅ **OAuth 2.0 authentication** - Industry standard
- ✅ **No passwords stored** - Only temporary tokens
- ✅ **Tokens expire automatically** - Access tokens last ~75 minutes
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

## 📊 Comparison: OneDrive vs OneNote Tools

| Feature | OneDrive Backup | OneNote Exporter |
|---------|----------------|------------------|
| **What it backs up** | Files & folders | Notes & notebooks |
| **Output format** | Original files | Markdown/ENEX/HTML |
| **Typical size** | GB to TB | MB to GB |
| **Backup time** | Varies by size | 5-30 minutes |
| **Best for** | File preservation | Note migration |
| **Destination** | External drive | Import to other apps |

## 💡 Pro Tips

### For Both Tools
1. **Test first** - Start with small backups/exports
2. **Stable internet** - Both need reliable connection
3. **Keep originals** - Don't delete Microsoft data for 30 days
4. **Check output** - Verify before deleting sources

### OneDrive Specific
- Use Files On-Demand carefully (may skip cloud-only files)
- Consider using online login for complete backup
- External drive needs sufficient space (check OneDrive size)

### OneNote Specific
- Read MIGRATION_GUIDE.md to choose target app
- Export format depends on destination (Joplin vs Evernote)
- Audio/video files take longest to download

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
# Try with user flag
pip install --user requests

# Or use pip3
pip3 install requests
```

### Tool-Specific Issues

**OneDrive: "Online-only files skipped"**
- Download files in OneDrive first, OR
- Use online login option in script

**OneNote: "No notebooks found"**
- Verify notebooks exist at https://www.onenote.com
- Check Azure app has Notes.Read permissions
- Try re-authenticating

**For detailed troubleshooting:**
- OneDrive: See `onedrive-backup/README.md`
- OneNote: See `onenote-exporter/README_ONENOTE.md`

## 📖 Documentation

### OneDrive Backup
- **README.md** - Complete documentation with setup, usage, troubleshooting

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

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

### For Both Tools
- 🐛 Report bugs
- 💡 Suggest features
- 📖 Improve documentation
- 🔧 Submit pull requests

### Specific Areas
- **OneDrive:** Work/school account support, incremental backups
- **OneNote:** Better format conversion, direct app imports, GUI

**See CONTRIBUTING.md for guidelines**

## 🗺️ Roadmap

### OneDrive Backup
- [ ] Work/school OneDrive support
- [ ] Incremental backup (only changed files)
- [ ] Compression options
- [ ] Scheduled backups
- [ ] GUI version

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

## 📝 License

MIT License - Free to use and modify for personal or commercial purposes.

See [LICENSE.md](LICENSE.md) for details.

## 🙏 Acknowledgments

- **Microsoft Graph API** - For providing access to personal data
- **Open source community** - For libraries and inspiration
- **Users** - For feedback and contributions

## ⭐ Show Your Support

If these tools help you:
- ⭐ Star this repository
- 🐛 Report issues
- 💬 Share with others
- 🤝 Contribute improvements

## 📞 Support & Contact

- 🐛 **Bug reports:** Open an issue on GitHub
- 💡 **Feature requests:** Open an issue with "enhancement" label
- 📖 **Documentation:** Check tool-specific README files
- 💬 **Questions:** Open a discussion on GitHub

## 🎯 Quick Links

- [OneDrive Backup README](onedrive-backup/README.md)
- [OneNote Exporter Quick Start](onenote-exporter/QUICKSTART.md)
- [OneNote Migration Guide](onenote-exporter/MIGRATION_GUIDE.md)
- [Contributing Guidelines](CONTRIBUTING.md)
- [License](LICENSE.md)

---

## 🚀 Ready to Get Started?

### Option 1: Backup OneDrive
```bash
cd onedrive-backup
python3 onedrive_backup.py
```

### Option 2: Export OneNote
```bash
cd onenote-exporter
python3 onenote_exporter.py
```

### Option 3: Do Both!
```bash
# Complete data liberation
cd onedrive-backup && python3 onedrive_backup.py
cd ../onenote-exporter && python3 onenote_exporter.py
```

**Your data, your control!** 🎉

---

**Made with ❤️ for people who believe in data freedom and portability**

*"The best time to backup your data was yesterday. The second best time is now."*
