# OneDrive Backup Tool

A Python script to automatically backup your entire OneDrive (personal accounts) to an external drive, preserving the exact folder structure.

## Features

✅ **Automatic authentication** via Microsoft Graph API  
✅ **Preserves folder structure** exactly as in OneDrive  
✅ **Auto-refreshing tokens** - can run for days/weeks without re-authentication  
✅ **Real-time progress tracking**  
✅ **Handles large backups** (500GB+)  
✅ **Supports documents and pictures** (configurable file types)  

## Requirements

- Python 3.6+
- External hard drive with sufficient space
- Microsoft personal account with OneDrive
- Azure app registration (free, one-time setup)

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/onedrive-backup.git
cd onedrive-backup
```

2. Install required dependencies:
```bash
pip install requests
```

## Azure Setup (One-Time)

Before using the script, you need to create an Azure app registration:

### Step 1: Create App Registration

1. Go to [Microsoft Entra Admin Center](https://entra.microsoft.com/)
2. Sign in with your personal Microsoft account
3. Navigate to **App registrations** → **+ New registration**
4. Fill out the form:
   - **Name:** `OneDrive Backup Tool`
   - **Supported account types:** "Accounts in any organizational directory and personal Microsoft accounts"
   - **Redirect URI:** Platform: `Web`, URI: `http://localhost:8080`
5. Click **Register**

### Step 2: Get Application (Client) ID

1. On the app's **Overview** page, copy the **Application (client) ID**
2. Save this - you'll need it when running the script

### Step 3: Create Client Secret

1. Go to **Certificates & secrets** (left sidebar)
2. Click **+ New client secret**
3. Description: `OneDrive Backup Secret`
4. Expiration: `24 months`
5. Click **Add**
6. **IMMEDIATELY copy the Value** (you can only see it once!)
7. Save this with your Client ID

### Step 4: Set API Permissions

1. Go to **API permissions** (left sidebar)
2. Click **+ Add a permission**
3. Select **Microsoft Graph**
4. Select **Delegated permissions**
5. Search for and add these permissions:
   - `Files.Read.All`
   - `offline_access`
6. Click **Add permissions**
7. Click **Grant admin consent** and confirm

You should see green checkmarks next to all permissions.

## Usage

### Basic Usage

Run the script:
```bash
python3 onedrive_backup.py
```

Follow the prompts:
1. Choose option **2** (Login to OneDrive online)
2. Choose option **1** (App Credentials)
3. Enter your **Application (client) ID**
4. Enter your **Client Secret**
5. Enter `common` for Tenant ID
6. Browser opens - sign in and approve permissions
7. Copy the redirect URL from browser and paste into terminal
8. Enter your external drive path (e.g., `/Volumes/MyDrive`)
9. Choose what to backup (documents, pictures, or both)
10. Let it run!

### What Gets Backed Up

By default, the script backs up:

**Documents:**
- PDF, Word (.docx, .doc), Excel (.xlsx, .xls)
- PowerPoint (.pptx, .ppt), Text files (.txt)
- CSV, RTF, ODT

**Pictures:**
- JPG, JPEG, PNG, GIF, BMP
- TIFF, SVG, WebP, HEIC, RAW

You can modify these file types in the script if needed.

## How It Works

1. **Authentication:** Uses OAuth 2.0 with delegated permissions
2. **Token Management:** Automatically refreshes access tokens (valid for 90 days)
3. **API Calls:** Uses Microsoft Graph API to list and download files
4. **Structure Preservation:** Recreates exact OneDrive folder hierarchy on external drive
5. **Progress Tracking:** Shows real-time file counts and paths

## Output Structure

Your backup will be organized exactly as in OneDrive:

```
/Volumes/YourDrive/OneDrive_Backup_20241203_051234/
├── Work/
│   ├── Projects/
│   │   ├── Report.docx
│   │   └── Data.xlsx
│   └── Presentations/
├── Personal/
│   ├── Photos/
│   │   ├── 2023/
│   │   └── 2024/
│   └── Documents/
└── [your exact OneDrive structure]
```

## Troubleshooting

### "Token expired" error
The script automatically refreshes tokens. If this fails, you may need to re-authenticate (run the script again).

### "Destination drive not found"
Make sure your external drive is connected and mounted. Use the exact path shown in Finder.

### "Invalid client secret"
You copied the Secret ID instead of the Value. Go back to Azure and create a new client secret, then copy the **Value** column.

### Browser doesn't open
Make sure `webbrowser` module is available (it's built into Python). Try running in a different terminal.

## Security Notes

- Your Client Secret should be kept private (don't commit to public repos)
- Access tokens expire after ~75 minutes
- Refresh tokens last 90 days and auto-renew when used
- The script never stores your Microsoft password
- All authentication uses official Microsoft OAuth flows

## Limitations

- Personal Microsoft accounts only (work/school accounts have different requirements)
- Requires interactive login once per session
- Download speed depends on your internet connection
- Large files may take time to download

## Contributing

Pull requests welcome! Please ensure:
- Code follows existing style
- Add tests for new features
- Update documentation

## License

MIT License - feel free to use and modify as needed.

## Credits

Created to solve the challenge of backing up large OneDrive accounts without local storage space.

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review Microsoft Graph API documentation
3. Open an issue on GitHub
