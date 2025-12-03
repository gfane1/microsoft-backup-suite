import os
import shutil
from pathlib import Path
from datetime import datetime
import json
import getpass
import requests
import webbrowser
from urllib.parse import urljoin, urlparse, parse_qs

class OneDriveBackup:
    def __init__(self):
        self.onedrive_path = self.find_onedrive_path()
        self.backup_log = []
        self.access_token = None
        self.refresh_token = None
        self.client_id = None
        self.client_secret = None
        self.tenant_id = None
        self.use_api = False
        
    def find_onedrive_path(self):
        """Automatically locate OneDrive folder"""
        possible_paths = [
            Path.home() / "OneDrive",
            Path.home() / "OneDrive - Personal",
            Path(os.environ.get('OneDrive', '')),
            Path(os.environ.get('OneDriveConsumer', '')),
            Path(os.environ.get('OneDriveCommercial', ''))
        ]
        
        for path in possible_paths:
            if path.exists() and path.is_dir():
                return path
        
        return None
    
    def login_to_onedrive_api(self):
        """Login to OneDrive using Microsoft Graph API"""
        print("\n" + "="*50)
        print("OneDrive Online Login")
        print("="*50)
        print("\n⚠️  IMPORTANT LIMITATIONS:")
        print("- Personal Microsoft accounts don't support device code flow")
        print("- You'll need to create a Microsoft App Registration")
        print("- This requires some technical setup")
        print("\n📋 Setup Instructions:")
        print("1. Go to: https://portal.azure.com")
        print("2. Search for 'App registrations' → New registration")
        print("3. Name: 'OneDrive Backup' (any name)")
        print("4. Supported account types: 'Personal Microsoft accounts only'")
        print("5. Register the app")
        print("6. Go to 'Certificates & secrets' → New client secret")
        print("7. Copy the Client ID and Client Secret")
        print("8. Go to 'API permissions' → Add permission → Microsoft Graph")
        print("9. Add: Files.Read.All (Delegated)")
        print("10. Grant admin consent")
        print("\n⚠️  NOTE: This is complex. Alternative: Download files to local OneDrive first")
        print("="*50 + "\n")
        
        choice = input("Choose login method:\n1. App Credentials (Personal Account)\n2. Device Code (Work/School Only)\n3. Skip\nEnter choice: ").strip()
        
        if choice == '1':
            return self.app_credentials_auth()
        elif choice == '2':
            print("\n⚠️  Warning: Device code only works with work/school accounts")
            confirm = input("Do you have a work/school account? (y/n): ").strip().lower()
            if confirm == 'y':
                return self.device_code_auth()
            else:
                print("Returning to main menu...")
                return False
        else:
            return False
    
    def device_code_auth(self):
        """Authenticate using device code flow (no app registration needed)"""
        print("\n📱 Device Code Authentication")
        print("This method is more secure and doesn't require app registration\n")
        
        # Using Microsoft's public client ID for device code flow
        client_id = "d3590ed6-52b3-4102-aeff-aad2292ab01c"  # Microsoft Office client
        authority = "https://login.microsoftonline.com/common"
        
        # Request device code
        device_code_url = f"{authority}/oauth2/v2.0/devicecode"
        data = {
            'client_id': client_id,
            'scope': 'https://graph.microsoft.com/Files.Read.All offline_access'
        }
        
        try:
            response = requests.post(device_code_url, data=data)
            device_code_data = response.json()
            
            if 'error' in device_code_data:
                print(f"❌ Error: {device_code_data.get('error_description', 'Unknown error')}")
                return False
            
            print("\n" + "="*50)
            print("🔐 AUTHENTICATION REQUIRED")
            print("="*50)
            print(f"\n1. Go to: {device_code_data['verification_uri']}")
            print(f"2. Enter code: {device_code_data['user_code']}")
            print(f"3. Sign in with your Microsoft account")
            print(f"\nWaiting for authentication (expires in {device_code_data['expires_in']//60} minutes)...")
            print("="*50 + "\n")
            
            # Poll for token
            token_url = f"{authority}/oauth2/v2.0/token"
            token_data = {
                'client_id': client_id,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': device_code_data['device_code']
            }
            
            import time
            interval = device_code_data.get('interval', 5)
            expires_at = time.time() + device_code_data['expires_in']
            
            while time.time() < expires_at:
                time.sleep(interval)
                token_response = requests.post(token_url, data=token_data)
                token_result = token_response.json()
                
                if 'access_token' in token_result:
                    self.access_token = token_result['access_token']
                    self.use_api = True
                    print("✅ Successfully authenticated!\n")
                    return True
                elif token_result.get('error') == 'authorization_pending':
                    print("⏳ Waiting for authentication...", end='\r')
                    continue
                elif token_result.get('error') == 'authorization_declined':
                    print("\n❌ Authentication declined")
                    return False
                elif token_result.get('error') == 'expired_token':
                    print("\n❌ Authentication expired")
                    return False
                else:
                    print(f"\n❌ Error: {token_result.get('error_description', 'Unknown error')}")
                    return False
            
            print("\n⏱️  Authentication timeout")
            return False
            
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    def app_credentials_auth(self):
        """Authenticate using app credentials (requires app registration)"""
        print("\n🔑 App Credentials Authentication")
        self.client_id = input("Enter Application (client) ID: ").strip()
        self.client_secret = getpass.getpass("Enter Client Secret (hidden): ")
        self.tenant_id = input("Enter Tenant ID (or 'common' for personal): ").strip() or "common"
        
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        
        # For personal accounts, we need delegated permissions with auth code flow
        if self.tenant_id == "common":
            return self.delegated_auth_flow()
        
        # For work/school, use client credentials
        token_url = f"{authority}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }
        
        try:
            response = requests.post(token_url, data=data)
            result = response.json()
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.use_api = True
                print("✅ Successfully authenticated!\n")
                return True
            else:
                print(f"❌ Authentication failed: {result.get('error_description', 'Unknown error')}")
                return False
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    def delegated_auth_flow(self):
        """Interactive auth flow for personal accounts"""
        print("\n🔐 Starting interactive authentication...")
        print("A browser window will open for you to sign in.")
        
        # Generate auth URL
        redirect_uri = "http://localhost:8080"
        scope = "Files.Read.All offline_access"
        auth_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
        auth_url += f"?client_id={self.client_id}"
        auth_url += f"&response_type=code"
        auth_url += f"&redirect_uri={redirect_uri}"
        auth_url += f"&scope={scope}"
        
        print(f"\n1. Opening browser...")
        print(f"2. Sign in with your Microsoft account")
        print(f"3. After approving, you'll be redirected to localhost")
        print(f"4. Copy the 'code=' value from the URL\n")
        
        webbrowser.open(auth_url)
        
        print("After signing in, your browser will show an error page.")
        print("That's normal! Just copy the URL from your browser.")
        redirect_response = input("\nPaste the full redirect URL here: ").strip()
        
        # Extract code from URL
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(redirect_response)
            code = parse_qs(parsed.query)['code'][0]
        except:
            print("❌ Could not extract authorization code from URL")
            return False
        
        # Exchange code for tokens
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        
        try:
            response = requests.post(token_url, data=data)
            result = response.json()
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.refresh_token = result.get('refresh_token')
                self.use_api = True
                print("✅ Successfully authenticated!\n")
                return True
            else:
                print(f"❌ Token exchange failed: {result.get('error_description', 'Unknown error')}")
                return False
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    def refresh_access_token(self):
        """Refresh the access token using refresh token"""
        if not self.refresh_token:
            return False
        
        print("🔄 Refreshing access token...")
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            response = requests.post(token_url, data=data)
            result = response.json()
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.refresh_token = result.get('refresh_token', self.refresh_token)
                print("✅ Token refreshed!")
                return True
            else:
                print(f"❌ Token refresh failed: {result.get('error_description', 'Unknown error')}")
                return False
        except Exception as e:
            print(f"❌ Token refresh error: {e}")
            return False
    
    def download_from_api(self, destination_drive, include_docs=True, include_pics=True):
        """Download files using Microsoft Graph API"""
        if not self.access_token:
            print("❌ Not authenticated")
            return False
        
        destination = Path(destination_drive)
        if not destination.exists():
            print(f"❌ Destination drive '{destination_drive}' not found!")
            return False
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = destination / f"OneDrive_Backup_{timestamp}"
        backup_root.mkdir(exist_ok=True)
        
        print(f"\n💾 Backup destination: {backup_root}\n")
        
        headers = {'Authorization': f'Bearer {self.access_token}'}
        graph_url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
        
        doc_extensions = {'.pdf', '.docx', '.doc', '.txt', '.xlsx', '.xls', 
                         '.pptx', '.ppt', '.odt', '.rtf', '.csv'}
        pic_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', 
                         '.svg', '.webp', '.heic', '.raw'}
        
        total_files = 0
        copied_files = 0
        api_call_count = 0
        
        def make_api_request(url):
            """Make API request with automatic token refresh"""
            nonlocal api_call_count
            api_call_count += 1
            
            # Refresh token every 50 API calls (roughly every 50 minutes for safety)
            if api_call_count % 50 == 0 and self.refresh_token:
                print("\n🔄 Refreshing access token to prevent expiration...")
                if self.refresh_access_token():
                    headers['Authorization'] = f'Bearer {self.access_token}'
            
            response = requests.get(url, headers=headers)
            
            # If unauthorized, try to refresh token
            if response.status_code == 401 and self.refresh_token:
                print("\n⚠️  Token expired, refreshing...")
                if self.refresh_access_token():
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    response = requests.get(url, headers=headers)
            
            return response
        
        try:
            def download_folder(url, local_path, depth=0):
                nonlocal total_files, copied_files
                
                response = make_api_request(url)
                if response.status_code != 200:
                    print(f"❌ Error accessing folder: {response.status_code}")
                    return
                
                items = response.json().get('value', [])
                
                for item in items:
                    name = item['name']
                    
                    if 'folder' in item:
                        # It's a folder, recurse and preserve structure
                        new_local_path = local_path / name
                        new_local_path.mkdir(exist_ok=True, parents=True)
                        children_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item['id']}/children"
                        download_folder(children_url, new_local_path, depth + 1)
                    else:
                        # It's a file
                        ext = Path(name).suffix.lower()
                        should_download = False
                        
                        # Check if we should download this file type
                        if include_docs and ext in doc_extensions:
                            should_download = True
                        elif include_pics and ext in pic_extensions:
                            should_download = True
                        
                        if should_download:
                            total_files += 1
                            download_url = item.get('@microsoft.graph.downloadUrl')
                            
                            if download_url:
                                try:
                                    # Preserve exact folder structure
                                    file_path = local_path / name
                                    file_path.parent.mkdir(parents=True, exist_ok=True)
                                    
                                    file_response = requests.get(download_url)
                                    if file_response.status_code == 200:
                                        with open(file_path, 'wb') as f:
                                            f.write(file_response.content)
                                        copied_files += 1
                                        # Show relative path from backup root
                                        rel_path = file_path.relative_to(backup_root)
                                        print(f"  [{'  ' * depth}{copied_files}/{total_files}] ✓ {rel_path}")
                                    else:
                                        print(f"  {'  ' * depth}✗ {name}: Download failed (status {file_response.status_code})")
                                except Exception as e:
                                    print(f"  {'  ' * depth}✗ {name}: {e}")
            
            print("📥 Downloading files from OneDrive (preserving folder structure)...\n")
            download_folder(graph_url, backup_root)
            
            # Print summary
            print("\n" + "="*50)
            print("📊 BACKUP SUMMARY")
            print("="*50)
            print(f"Total files found: {total_files}")
            print(f"Successfully downloaded: {copied_files}")
            print(f"Backup location: {backup_root}")
            print(f"\n✅ Folder structure preserved exactly as in OneDrive!")
            
            return True
            
        except Exception as e:
            print(f"❌ Download error: {e}")
            return False
    
    def get_documents_and_pictures(self):
        """Find all documents and pictures in OneDrive"""
        if not self.onedrive_path:
            return [], []
        
        doc_extensions = {'.pdf', '.docx', '.doc', '.txt', '.xlsx', '.xls', 
                         '.pptx', '.ppt', '.odt', '.rtf', '.csv'}
        pic_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', 
                         '.svg', '.webp', '.heic', '.raw'}
        
        documents = []
        pictures = []
        
        print("🔍 Scanning OneDrive for files...")
        folder_count = 0
        skipped_online_only = 0
        
        for root, dirs, files in os.walk(self.onedrive_path):
            folder_count += 1
            if folder_count % 10 == 0:
                print(f"   Scanned {folder_count} folders, found {len(documents)} docs, {len(pictures)} pics...", end='\r')
            
            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()
                
                # Skip files that are online-only (0 bytes or have cloud icon attributes)
                try:
                    if file_path.stat().st_size == 0:
                        skipped_online_only += 1
                        continue
                except:
                    continue
                
                if ext in doc_extensions:
                    documents.append(file_path)
                elif ext in pic_extensions:
                    pictures.append(file_path)
        
        print(f"\n✓ Scan complete! Found {len(documents)} documents and {len(pictures)} pictures")
        if skipped_online_only > 0:
            print(f"⚠️  Skipped {skipped_online_only} online-only files (not downloaded locally)")
            print("   To backup these files, either:")
            print("   1. Download them in OneDrive first, or")
            print("   2. Use the online login method when running this script\n")
        else:
            print()
        return documents, pictures
    
    def backup_files(self, destination_drive, include_docs=True, include_pics=True):
        """Backup files to external drive"""
        if not self.onedrive_path:
            print("❌ OneDrive folder not found!")
            print("Please ensure OneDrive is installed and synced.")
            return False
        
        destination = Path(destination_drive)
        if not destination.exists():
            print(f"❌ Destination drive '{destination_drive}' not found!")
            return False
        
        # Create backup folder with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = destination / f"OneDrive_Backup_{timestamp}"
        backup_root.mkdir(exist_ok=True)
        
        print(f"\n📁 OneDrive location: {self.onedrive_path}")
        print(f"💾 Backup destination: {backup_root}\n")
        
        documents, pictures = self.get_documents_and_pictures()
        
        total_files = 0
        copied_files = 0
        failed_files = []
        
        # Backup documents
        if include_docs and documents:
            print(f"📄 Backing up {len(documents)} documents...")
            docs_folder = backup_root / "Documents"
            docs_folder.mkdir(exist_ok=True)
            
            for idx, doc in enumerate(documents, 1):
                total_files += 1
                try:
                    relative_path = doc.relative_to(self.onedrive_path)
                    dest_file = docs_folder / relative_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    shutil.copy2(doc, dest_file)
                    copied_files += 1
                    self.backup_log.append({
                        'file': str(doc),
                        'destination': str(dest_file),
                        'status': 'success'
                    })
                    # Show progress every file
                    print(f"  [{idx}/{len(documents)}] ✓ {relative_path.name[:50]}", end='\r')
                except Exception as e:
                    failed_files.append((doc, str(e)))
                    self.backup_log.append({
                        'file': str(doc),
                        'status': 'failed',
                        'error': str(e)
                    })
                    print(f"  [{idx}/{len(documents)}] ✗ {doc.name}: {e}")
            print()  # New line after progress
        
        # Backup pictures
        if include_pics and pictures:
            print(f"\n🖼️  Backing up {len(pictures)} pictures...")
            pics_folder = backup_root / "Pictures"
            pics_folder.mkdir(exist_ok=True)
            
            for idx, pic in enumerate(pictures, 1):
                total_files += 1
                try:
                    relative_path = pic.relative_to(self.onedrive_path)
                    dest_file = pics_folder / relative_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    shutil.copy2(pic, dest_file)
                    copied_files += 1
                    self.backup_log.append({
                        'file': str(pic),
                        'destination': str(dest_file),
                        'status': 'success'
                    })
                    # Show progress every file
                    print(f"  [{idx}/{len(pictures)}] ✓ {relative_path.name[:50]}", end='\r')
                except Exception as e:
                    failed_files.append((pic, str(e)))
                    self.backup_log.append({
                        'file': str(pic),
                        'status': 'failed',
                        'error': str(e)
                    })
                    print(f"  [{idx}/{len(pictures)}] ✗ {pic.name}: {e}")
            print()  # New line after progress
        
        # Save backup log
        log_file = backup_root / "backup_log.json"
        with open(log_file, 'w') as f:
            json.dump({
                'timestamp': timestamp,
                'total_files': total_files,
                'copied_files': copied_files,
                'failed_files': len(failed_files),
                'files': self.backup_log
            }, f, indent=2)
        
        # Print summary
        print("\n" + "="*50)
        print("📊 BACKUP SUMMARY")
        print("="*50)
        print(f"Total files found: {total_files}")
        print(f"Successfully copied: {copied_files}")
        print(f"Failed: {len(failed_files)}")
        print(f"Backup location: {backup_root}")
        print(f"Log file: {log_file}")
        
        if failed_files:
            print("\n⚠️  Failed files:")
            for file, error in failed_files[:10]:
                print(f"  - {file.name}: {error}")
            if len(failed_files) > 10:
                print(f"  ... and {len(failed_files) - 10} more")
        
        return True

def main():
    print("="*50)
    print("OneDrive Backup Tool")
    print("="*50)
    
    backup = OneDriveBackup()
    
    # Always give user the choice
    if backup.onedrive_path:
        print(f"\n✓ Local OneDrive found at: {backup.onedrive_path}")
        print("\n⚠️  Note: Local OneDrive may contain Files On-Demand (0 KB placeholders)")
        print("\nHow would you like to backup?")
        print("1. Use local OneDrive folder (only backs up downloaded files)")
        print("2. Login to OneDrive online and download all files from cloud")
        print("3. Exit")
        
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == '2':
            if not backup.login_to_onedrive_api():
                print("❌ Login failed. Exiting.")
                return
        elif choice == '3':
            return
        # choice == '1' continues with local folder
    else:
        print("\n⚠️  Could not locate local OneDrive folder.")
        print("\nOptions:")
        print("1. Enter OneDrive path manually")
        print("2. Login to OneDrive online and download files")
        print("3. Exit")
        
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == '1':
            manual_path = input("Enter your OneDrive path: ").strip()
            backup.onedrive_path = Path(manual_path)
            
            if not backup.onedrive_path.exists():
                print("❌ Invalid path. Trying online login...")
                choice = '2'
        
        if choice == '2':
            if not backup.login_to_onedrive_api():
                print("❌ Login failed. Exiting.")
                return
        elif choice == '3':
            return
    
    # Get destination drive
    print("\nEnter the path to your external drive (e.g., E:, /media/backup, etc.):")
    destination = input("> ").strip()
    
    # Ask what to backup
    print("\nWhat would you like to backup?")
    print("1. Documents only")
    print("2. Pictures only")
    print("3. Both documents and pictures")
    choice = input("Enter choice (1-3): ").strip()
    
    include_docs = choice in ['1', '3']
    include_pics = choice in ['2', '3']
    
    print("\n🚀 Starting backup...")
    
    if backup.use_api:
        backup.download_from_api(destination, include_docs, include_pics)
    else:
        backup.backup_files(destination, include_docs, include_pics)
    
    print("\n✅ Backup complete!")

if __name__ == "__main__":
    main()
