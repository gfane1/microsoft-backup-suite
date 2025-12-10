import os
import shutil
from pathlib import Path
from datetime import datetime
import json
import getpass
import requests
import webbrowser
from urllib.parse import urljoin, urlparse, parse_qs
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import threading

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
        self.downloaded_files = {}  # Changed to dict to store metadata
        self.progress_file = None
        self.large_file_threshold = 100 * 1024 * 1024  # 100MB
        self.file_metadata = {}  # Store file hashes and sizes for incremental backup
        self.metadata_file = None
        self.max_workers = 3  # Number of parallel downloads
        self.progress_lock = Lock()  # Thread-safe progress updates
        self.verification_failures = []
        
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
    
    def check_disk_space(self, destination, required_space_bytes):
        """
        Check if destination has enough free space.
        
        Args:
            destination: Path to destination drive
            required_space_bytes: Space needed in bytes
            
        Returns:
            tuple: (has_space: bool, available_bytes: int, required_bytes: int)
        """
        try:
            stat = shutil.disk_usage(destination)
            available = stat.free
            
            # Add 10% buffer for safety
            required_with_buffer = required_space_bytes * 1.1
            
            return (available >= required_with_buffer, available, required_with_buffer)
        except Exception as e:
            print(f"⚠️  Warning: Could not check disk space: {e}")
            return (True, 0, 0)  # Assume OK if we can't check
    
    def format_size(self, bytes_size):
        """Format bytes into human-readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"
    
    def calculate_file_hash(self, file_path, chunk_size=8192):
        """
        Calculate SHA256 hash of a file.
        
        Args:
            file_path: Path to file
            chunk_size: Size of chunks to read (default 8KB)
            
        Returns:
            str: Hexadecimal hash string
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            print(f"⚠️  Could not hash {file_path}: {e}")
            return None
    
    def verify_file(self, file_path, expected_size, item_id=None):
        """
        Verify downloaded file integrity.
        
        Args:
            file_path: Path to downloaded file
            expected_size: Expected file size in bytes
            item_id: OneDrive item ID (optional)
            
        Returns:
            bool: True if file is valid, False otherwise
        """
        try:
            if not file_path.exists():
                return False
            
            actual_size = file_path.stat().st_size
            
            # Size verification
            if actual_size != expected_size:
                print(f"⚠️  Size mismatch: {file_path.name} (expected {expected_size}, got {actual_size})")
                # Remove bad metadata if it exists
                if item_id and item_id in self.file_metadata:
                    with self.progress_lock:
                        del self.file_metadata[item_id]
                return False
            
            # Calculate hash for integrity check
            file_hash = self.calculate_file_hash(file_path)
            if not file_hash:
                print(f"⚠️  Could not calculate hash for {file_path.name}")
                return False
            
            # Only store metadata if file is valid AND has actual content
            if file_hash and item_id and actual_size > 0:  # ← Added size check
                with self.progress_lock:
                    self.file_metadata[item_id] = {
                        'size': actual_size,
                        'hash': file_hash,
                        'path': str(file_path),
                        'modified': datetime.now().isoformat()
                    }
            elif actual_size == 0:
                print(f"⚠️  Skipping metadata for 0-byte file: {file_path.name}")
            
            return True
            
        except Exception as e:
            print(f"⚠️  Verification error for {file_path}: {e}")
            # Remove bad metadata if it exists
            if item_id and item_id in self.file_metadata:
                with self.progress_lock:
                    del self.file_metadata[item_id]
            return False
    
    def should_download_file(self, item_id, file_size, file_path):
        """
        Determine if file needs to be downloaded (incremental backup logic).
        
        Args:
            item_id: OneDrive item ID
            file_size: Size of file in OneDrive
            file_path: Local destination path
            
        Returns:
            bool: True if file should be downloaded, False if can skip
        """
        # If file doesn't exist locally, must download
        if not file_path.exists():
            return True
        
        # If we have no metadata, check if file size matches (trust the file on disk)
        if item_id not in self.file_metadata:
            local_size = file_path.stat().st_size
            
            # If size matches, trust the file and skip download
            if local_size == file_size and local_size > 0:
                print(f"  ✓ File exists with correct size, skipping: {file_path.name}")
                return False  # Skip - file is good!
            else:
                # Size mismatch or 0-byte file - need to download
                print(f"  🔄 File size mismatch ({local_size} vs {file_size}), re-downloading: {file_path.name}")
                try:
                    file_path.unlink()
                except Exception as e:
                    print(f"  ⚠️  Could not delete mismatched file: {e}")
                return True
        
        # Check if local file matches metadata
        metadata = self.file_metadata[item_id]
        local_size = file_path.stat().st_size
        
        # If sizes don't match, delete and re-download
        if local_size != metadata.get('size') or local_size != file_size:
            print(f"  🔄 Size mismatch, re-downloading: {file_path.name}")
            try:
                file_path.unlink()
            except Exception as e:
                print(f"  ⚠️  Could not delete mismatched file: {e}")
            return True
        
        # Verify hash if available
        if 'hash' in metadata:
            local_hash = self.calculate_file_hash(file_path)
            if local_hash != metadata['hash']:
                print(f"  🔄 Hash mismatch (corrupted), re-downloading: {file_path.name}")
                try:
                    file_path.unlink()
                except Exception as e:
                    print(f"  ⚠️  Could not delete corrupted file: {e}")
                return True
        
        # File is identical, skip download
        return False
    
    def load_metadata(self, backup_root):
        """Load existing backup metadata for incremental backups"""
        self.metadata_file = backup_root / ".backup_metadata.json"
        
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    data = json.load(f)
                    raw_metadata = data.get('files', {})
                
                # Cleanse metadata: Remove 0-byte entries (from Files On-Demand placeholders)
                original_count = len(raw_metadata)
                self.file_metadata = {
                    item_id: file_info 
                    for item_id, file_info in raw_metadata.items() 
                    if file_info.get('size', 0) > 0  # Only keep files with actual size
                }
                
                cleansed_count = original_count - len(self.file_metadata)
                
                print(f"📋 Loaded metadata for {len(self.file_metadata)} existing files")
                if cleansed_count > 0:
                    print(f"🧹 Cleansed {cleansed_count} zero-byte entries from metadata")
                    print(f"   (These were likely Files On-Demand placeholders)")
                
            except Exception as e:
                print(f"⚠️  Could not load metadata: {e}")
                self.file_metadata = {}
    
    def save_metadata(self):
        """Save backup metadata for future incremental backups (thread-safe)"""
        if self.metadata_file:
            try:
                # Create thread-safe snapshot
                with self.progress_lock:
                    metadata_snapshot = dict(self.file_metadata)
                
                # Write snapshot to file
                with open(self.metadata_file, 'w') as f:
                    json.dump({
                        'files': metadata_snapshot,
                        'last_backup': datetime.now().isoformat()
                    }, f, indent=2)
            except Exception as e:
                print(f"⚠️  Could not save metadata: {e}")
    
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
    
    def download_large_file(self, url, destination, filename, expected_size, depth=0, item_id=None):
        """
        Download large files in chunks with progress tracking and resume capability.
        
        Features:
        - Adaptive chunk size (50MB for huge files, 20MB for large, 10MB for normal)
        - Resume capability if download is interrupted
        - Real-time progress tracking with speed and ETA
        - Automatic retry on timeout
        - Graceful handling of interruptions
        - Post-download verification
        - Proactive URL refresh for huge files (>10GB)
        """
        # Adaptive chunk size based on file size
        if expected_size > 10 * 1024 * 1024 * 1024:  # > 10 GB
            chunk_size = 50 * 1024 * 1024  # 50 MB chunks for huge files
            print(f"  {'  ' * depth}📦 Huge file detected ({expected_size/(1024**3):.1f}GB), using 50MB chunks")
        elif expected_size > 1 * 1024 * 1024 * 1024:  # > 1 GB
            chunk_size = 20 * 1024 * 1024  # 20 MB chunks for large files
        else:
            chunk_size = 10 * 1024 * 1024  # 10 MB chunks for normal files
        
        temp_file = destination.parent / f".{destination.name}.download"
        
        # Check if partial download exists
        downloaded_size = 0
        if temp_file.exists():
            downloaded_size = temp_file.stat().st_size
            print(f"  {'  ' * depth}📥 Resuming {filename} from {downloaded_size / (1024*1024):.1f}MB")
        
        max_retries = 3
        retry_count = 0
        download_start_time = time.time()
        last_url_refresh_time = download_start_time
        url_refresh_interval = 60 * 60  # Refresh URL every 60 minutes for huge files
        
        while retry_count < max_retries:
            try:
                # Make request with range header if resuming
                headers_with_range = {}
                if downloaded_size > 0:
                    headers_with_range['Range'] = f'bytes={downloaded_size}-'
                
                response = requests.get(url, headers=headers_with_range, stream=True, timeout=60)
                
                # If server doesn't support resume (206), start fresh
                if downloaded_size > 0 and response.status_code not in [200, 206]:
                    if response.status_code == 416:  # Range not satisfiable - file might be complete
                        # Check if temp file size matches what we expect
                        if temp_file.exists():
                            temp_file.rename(destination)
                            # Verify the file
                            if self.verify_file(destination, expected_size, item_id):
                                class SuccessResponse:
                                    status_code = 200
                                return SuccessResponse()
                            else:
                                print(f"  {'  ' * depth}❌ Verification failed, re-downloading")
                                destination.unlink()
                                downloaded_size = 0
                                continue
                    
                    print(f"  {'  ' * depth}⚠️  Server doesn't support resume (status {response.status_code}), starting fresh")
                    downloaded_size = 0
                    if temp_file.exists():
                        temp_file.unlink()
                    response = requests.get(url, stream=True, timeout=60)
                
                if response.status_code not in [200, 206]:
                    # If 401 and we're just starting, try to get a fresh download URL
                    if response.status_code == 401 and downloaded_size == 0 and item_id:
                        print(f"\n  {'  ' * depth}🔄 {filename}: Download URL expired, refreshing...")
                        fresh_url = self.get_fresh_download_url(item_id)
                        if fresh_url:
                            url = fresh_url  # Update URL for next retry
                            continue  # Retry with fresh URL
                        else:
                            print(f"  {'  ' * depth}❌ Could not refresh download URL")
                            return None
                    
                    print(f"  {'  ' * depth}❌ HTTP {response.status_code} received")
                    return response
                
                # Get total file size
                if response.status_code == 206:
                    # Partial content - parse Content-Range header
                    content_range = response.headers.get('Content-Range', '')
                    if '/' in content_range:
                        total_size = int(content_range.split('/')[-1])
                    else:
                        total_size = int(response.headers.get('content-length', 0)) + downloaded_size
                else:
                    # Full content
                    total_size = int(response.headers.get('content-length', 0))
                
                # Open file in append mode if resuming, write mode if starting fresh
                mode = 'ab' if downloaded_size > 0 and response.status_code == 206 else 'wb'
                if mode == 'wb':
                    downloaded_size = 0  # Reset if starting fresh
                
                with open(temp_file, mode) as f:
                    start_time = time.time()
                    last_print_time = start_time
                    chunk_start_time = start_time
                    chunk_start_size = downloaded_size
                    
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            # Print progress every 2 seconds
                            current_time = time.time()
                            
                            # For huge files (>10GB), proactively refresh URL every 60 minutes
                            if expected_size > 10 * 1024 * 1024 * 1024 and item_id:
                                if current_time - last_url_refresh_time >= url_refresh_interval:
                                    print(f"\n  {'  ' * depth}🔄 Proactive URL refresh (60 min elapsed)...")
                                    fresh_url = self.get_fresh_download_url(item_id)
                                    if fresh_url:
                                        print(f"  {'  ' * depth}✓ Fresh URL obtained, continuing download...")
                                        url = fresh_url
                                        last_url_refresh_time = current_time
                                        # Save progress and restart with fresh URL
                                        f.flush()
                                        # Break and restart with new URL
                                        break
                                    else:
                                        print(f"  {'  ' * depth}⚠️  Could not refresh URL proactively, continuing...")
                            
                            if current_time - last_print_time >= 2 or downloaded_size >= total_size:
                                # Calculate speed based on recent chunks for more accuracy
                                time_delta = current_time - chunk_start_time
                                if time_delta > 0:
                                    recent_speed = (downloaded_size - chunk_start_size) / time_delta / (1024 * 1024)  # MB/s
                                else:
                                    recent_speed = 0
                                
                                percent = (downloaded_size / total_size * 100) if total_size > 0 else 0
                                eta = (total_size - downloaded_size) / (recent_speed * 1024 * 1024) if recent_speed > 0 else 0
                                
                                # Format ETA nicely
                                if eta > 3600:
                                    eta_str = f"{eta/3600:.1f}h"
                                elif eta > 60:
                                    eta_str = f"{eta/60:.1f}m"
                                else:
                                    eta_str = f"{eta:.0f}s"
                                
                                print(f"  {'  ' * depth}📥 {filename[:35]}: {downloaded_size/(1024*1024):.1f}/{total_size/(1024*1024):.1f}MB ({percent:.1f}%) @ {recent_speed:.2f}MB/s, ETA: {eta_str}     ", end='\r')
                                last_print_time = current_time
                                
                                # Reset chunk timing for next calculation
                                chunk_start_time = current_time
                                chunk_start_size = downloaded_size
                    
                    # If we broke out for URL refresh, continue with new URL
                    if downloaded_size < total_size and expected_size > 10 * 1024 * 1024 * 1024:
                        continue  # Retry with fresh URL
                
                # Download complete, move temp file to final location
                if temp_file.exists():
                    temp_file.rename(destination)
                
                print()  # New line after progress
                
                # Verify the downloaded file
                if not self.verify_file(destination, expected_size, item_id):
                    with self.progress_lock:
                        self.verification_failures.append(str(destination))
                    print(f"  {'  ' * depth}⚠️  Verification failed for {filename}")
                    # Don't return error - file is downloaded, just flagged for review
                
                # Create a success response object
                class SuccessResponse:
                    status_code = 200
                
                return SuccessResponse()
                
            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count < max_retries:
                    print(f"\n  {'  ' * depth}⏱️  Timeout for {filename}, retrying ({retry_count}/{max_retries})...")
                    time.sleep(5)  # Wait before retry
                    continue
                else:
                    print(f"\n  {'  ' * depth}❌ Max retries reached for {filename}, progress saved")
                    return None
                    
            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count < max_retries:
                    print(f"\n  {'  ' * depth}⚠️  Network error for {filename}, retrying ({retry_count}/{max_retries}): {e}")
                    time.sleep(5)
                    continue
                else:
                    print(f"\n  {'  ' * depth}❌ Max retries reached for {filename}: {e}")
                    return None
                    
            except KeyboardInterrupt:
                print(f"\n  {'  ' * depth}⏸️  Download interrupted for {filename}, progress saved to {temp_file.name}")
                raise  # Re-raise to be caught by main handler
                
            except Exception as e:
                print(f"\n  {'  ' * depth}❌ Error downloading {filename}: {e}")
                if temp_file.exists() and downloaded_size == 0:
                    temp_file.unlink()  # Clean up corrupted temp file only if we haven't made progress
                return None
        
        return None  # If we exit the retry loop without success
    
    def get_fresh_download_url(self, item_id):
        """Get a fresh download URL for an item when the old one expires"""
        try:
            item_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}"
            response = requests.get(item_url, headers=self.api_headers, timeout=30)
            
            if response.status_code == 401:
                # Token expired, refresh and retry
                if self.refresh_access_token():
                    self.api_headers['Authorization'] = f'Bearer {self.access_token}'
                    response = requests.get(item_url, headers=self.api_headers, timeout=30)
            
            if response.status_code == 200:
                item_data = response.json()
                return item_data.get('@microsoft.graph.downloadUrl')
        except Exception as e:
            print(f"  ⚠️  Failed to refresh download URL: {e}")
        
        return None
    
    def download_single_file(self, download_task):
        """
        Download a single file (used by thread pool).
        
        Args:
            download_task: Dictionary containing file info
            
        Returns:
            dict: Result of download operation
        """
        item = download_task['item']
        local_path = download_task['local_path']
        depth = download_task['depth']
        backup_root = download_task['backup_root']
        
        name = item['name']
        item_id = item['id']
        file_size = item.get('size', 0)
        download_url = item.get('@microsoft.graph.downloadUrl')
        
        file_path = local_path / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        result = {
            'item_id': item_id,
            'name': name,
            'path': file_path,
            'size': file_size,
            'success': False,
            'skipped': False,
            'error': None
        }
        
        # Check if we can skip this file (incremental backup)
        if not self.should_download_file(item_id, file_size, file_path):
            result['skipped'] = True
            result['success'] = True
            with self.progress_lock:
                self.downloaded_files[item_id] = {
                    'size': file_size,
                    'path': str(file_path),
                    'timestamp': datetime.now().isoformat()
                }
            return result
        
        if not download_url:
            result['error'] = "No download URL available"
            return result
        
        try:
            # Use chunked download for large files
            if file_size > self.large_file_threshold:
                file_response = self.download_large_file(download_url, file_path, name, file_size, depth, item_id)
            else:
                # Small file - simple download with verification
                file_response = requests.get(download_url, timeout=300)
                
                # If 401, the download URL expired - get a fresh one
                if file_response.status_code == 401:
                    print(f"  🔄 {name}: Download URL expired, refreshing...")
                    fresh_url = self.get_fresh_download_url(item_id)
                    if fresh_url:
                        file_response = requests.get(fresh_url, timeout=300)
                    else:
                        result['error'] = "Download URL expired and could not be refreshed"
                        print(f"  ❌ {name}: Could not refresh download URL")
                        return result
                
                if file_response.status_code == 200:
                    with open(file_path, 'wb') as f:
                        f.write(file_response.content)
                    
                    # Verify small file
                    if not self.verify_file(file_path, file_size, item_id):
                        with self.progress_lock:
                            self.verification_failures.append(str(file_path))
                        print(f"  ⚠️  Verification failed for {name}")
            
            if file_response and file_response.status_code == 200:
                result['success'] = True
                # Only track files with actual content
                if file_size > 0:
                    with self.progress_lock:
                        self.downloaded_files[item_id] = {
                            'size': file_size,
                            'path': str(file_path),
                            'timestamp': datetime.now().isoformat()
                        }
                else:
                    print(f"  ⚠️  Skipping 0-byte file from progress: {name}")
                
                # Print success message
                rel_path = file_path.relative_to(backup_root)
                size_mb = file_size / (1024 * 1024)
                with self.progress_lock:
                    print(f"  ✓ {rel_path} ({size_mb:.1f}MB)")
            elif file_response:
                result['error'] = f"HTTP {file_response.status_code}"
                print(f"  ❌ {name}: HTTP {file_response.status_code}")
            
        except Exception as e:
            error_msg = str(e)
            result['error'] = error_msg
            print(f"  ✗ {name}: {error_msg}")
        
        return result
    
    def download_from_api(self, destination_drive, include_docs=True, include_pics=True, include_videos=True, include_all=False, resume_backup_path=None):
        """Download files using Microsoft Graph API with multi-threading"""
        if not self.access_token:
            print("❌ Not authenticated")
            return False
        
        destination = Path(destination_drive)
        if not destination.exists():
            print(f"❌ Destination drive '{destination_drive}' not found!")
            return False
        
        # Use the backup path passed from main() if resuming
        if resume_backup_path:
            backup_root = resume_backup_path
            print(f"\n✓ Resuming backup: {backup_root.name}")
        else:
            # Create new backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_root = destination / f"OneDrive_Backup_{timestamp}"
            backup_root.mkdir(exist_ok=True)
            print(f"\n✓ Starting new backup: {backup_root.name}")
        
        # Load metadata for incremental backup
        self.load_metadata(backup_root)
        
        # Progress tracking
        self.progress_file = backup_root / ".progress.json"
        if self.progress_file.exists():
            with open(self.progress_file, 'r') as f:
                progress_data = json.load(f)
                raw_downloaded = progress_data.get('downloaded_files', {})
            
            # Cleanse progress: Remove 0-byte entries
            original_count = len(raw_downloaded)
            self.downloaded_files = {
                item_id: file_info 
                for item_id, file_info in raw_downloaded.items() 
                if file_info.get('size', 0) > 0  # Only keep files with actual size
            }
            
            cleansed_count = original_count - len(self.downloaded_files)
            
            print(f"📂 Loaded progress: {len(self.downloaded_files)} files already downloaded")
            if cleansed_count > 0:
                print(f"🧹 Cleansed {cleansed_count} zero-byte entries from progress")
                print(f"   (These files will be re-downloaded properly)")
            print()
        
        print(f"💾 Backup destination: {backup_root}\n")
        
        # Create headers dict that we can update when refreshing tokens
        self.api_headers = {'Authorization': f'Bearer {self.access_token}'}
        
        # PHASE 1: Scan and calculate total size
        print("🔍 Phase 1: Scanning OneDrive and calculating space requirements...\n")
        
        graph_url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
        
        doc_extensions = {'.pdf', '.docx', '.doc', '.txt', '.xlsx', '.xls', 
                         '.pptx', '.ppt', '.odt', '.rtf', '.csv'}
        pic_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', 
                         '.svg', '.webp', '.heic', '.raw'}
        video_extensions = {'.mov', '.mp4', '.avi', '.mkv', '.wmv', '.flv', 
                           '.m4v', '.mpg', '.mpeg', '.3gp', '.webm'}
        
        total_size_bytes = 0
        files_to_download = []
        scanned_files = 0
        skipped_files = 0
        consecutive_refresh_failures = 0
        
        def make_api_request(url, retry_count=0, max_retries=3):
            """Make API request with automatic token refresh"""
            nonlocal consecutive_refresh_failures
            
            try:
                response = requests.get(url, headers=self.api_headers, timeout=30)
                
                if response.status_code == 401:
                    if self.refresh_token and consecutive_refresh_failures < 3:
                        print("\n🔄 Access token expired, refreshing...")
                        if self.refresh_access_token():
                            # Update the global headers
                            self.api_headers['Authorization'] = f'Bearer {self.access_token}'
                            consecutive_refresh_failures = 0
                            print("✓ Token refreshed, retrying request...")
                            # Retry the request with new token
                            return make_api_request(url, retry_count, max_retries)
                        else:
                            consecutive_refresh_failures += 1
                            print(f"❌ Token refresh failed (attempt {consecutive_refresh_failures}/3)")
                            if consecutive_refresh_failures >= 3:
                                print("❌ Too many token refresh failures. Please re-authenticate.")
                                return None
                    else:
                        print("❌ Authentication failed and cannot refresh. Please re-run the script.")
                        return None
                
                if response.status_code == 200:
                    consecutive_refresh_failures = 0  # Reset on success
                    return response
                
                return response
                
            except requests.exceptions.Timeout:
                if retry_count < max_retries:
                    print(f"\n⏱️  Request timeout, retrying ({retry_count + 1}/{max_retries})...")
                    time.sleep(2)
                    return make_api_request(url, retry_count + 1, max_retries)
                else:
                    print(f"\n❌ Max retries reached for {url[:50]}...")
                    return None
            except requests.exceptions.RequestException as e:
                print(f"\n❌ Network error: {e}")
                return None
        
        def scan_folder(url, local_path, depth=0):
            """Scan folder and collect files to download (with pagination support)"""
            nonlocal total_size_bytes, scanned_files, skipped_files
            
            # Handle pagination - Microsoft Graph API returns max 200 items per page
            current_url = url
            page_count = 0
            
            while current_url:
                page_count += 1
                
                response = make_api_request(current_url)
                if response is None or response.status_code != 200:
                    return
                
                data = response.json()
                items = data.get('value', [])
                
                # Check for next page
                next_link = data.get('@odata.nextLink')
                
                if page_count > 1:
                    print(f"  {'  ' * depth}📄 Page {page_count}: Processing {len(items)} more items in {local_path.name or 'root'}...")
                
                for item in items:
                    name = item['name']
                    item_id = item['id']
                    
                    if 'folder' in item:
                        # Recurse into folder
                        new_local_path = local_path / name
                        new_local_path.mkdir(exist_ok=True, parents=True)
                        children_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/children"
                        scan_folder(children_url, new_local_path, depth + 1)
                    else:
                        # It's a file
                        ext = Path(name).suffix.lower()
                        should_include = False
                        
                        if include_all:
                            should_include = True
                        elif include_docs and ext in doc_extensions:
                            should_include = True
                        elif include_pics and ext in pic_extensions:
                            should_include = True
                        elif include_videos and ext in video_extensions:
                            should_include = True
                        
                        if should_include:
                            scanned_files += 1
                            file_size = item.get('size', 0)
                            file_path = local_path / name
                            
                            # Check if we need to download this file
                            if self.should_download_file(item_id, file_size, file_path):
                                total_size_bytes += file_size
                                files_to_download.append({
                                    'item': item,
                                    'local_path': local_path,
                                    'depth': depth,
                                    'backup_root': backup_root
                                })
                            else:
                                skipped_files += 1
                            
                            if scanned_files % 100 == 0:
                                print(f"  Scanned: {scanned_files} files, Need to download: {len(files_to_download)} ({self.format_size(total_size_bytes)})", end='\r')
                
                # Move to next page if it exists
                current_url = next_link
        
        # Start scanning
        scan_folder(graph_url, backup_root)
        
        print(f"\n\n✓ Scan complete!")
        print(f"  Total files found: {scanned_files}")
        print(f"  Files to download: {len(files_to_download)}")
        print(f"  Files skipped (unchanged): {skipped_files}")
        print(f"  Size to download: {self.format_size(total_size_bytes)}\n")
        
        # PHASE 2: Check disk space
        print("💾 Phase 2: Checking available disk space...\n")
        
        has_space, available, required = self.check_disk_space(destination, total_size_bytes)
        
        print(f"  Available space: {self.format_size(available)}")
        print(f"  Required space: {self.format_size(required)} (including 10% buffer)")
        
        if not has_space:
            print(f"\n❌ ERROR: Insufficient disk space!")
            print(f"  Need: {self.format_size(required - available)} more")
            print(f"\nOptions:")
            print(f"  1. Free up space on {destination}")
            print(f"  2. Use a different destination drive")
            print(f"  3. Select fewer file types to backup")
            return False
        
        print(f"  ✓ Sufficient space available\n")
        
        if len(files_to_download) == 0:
            print("✅ All files are up to date! No downloads needed.")
            return True
        
        # PHASE 3: Download files with multi-threading
        print(f"📥 Phase 3: Downloading {len(files_to_download)} files using {self.max_workers} parallel threads...\n")
        
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0
        failed_files = []  # Track failed files with reasons
        
        def save_progress():
            """Save current progress (thread-safe)"""
            # Create a snapshot while holding the lock to avoid "dictionary changed size during iteration"
            with self.progress_lock:
                files_snapshot = dict(self.downloaded_files)
            
            # Write snapshot to file (no lock needed for file I/O)
            with open(self.progress_file, 'w') as f:
                json.dump({
                    'downloaded_files': files_snapshot,
                    'timestamp': datetime.now().isoformat()
                }, f)
            self.save_metadata()
        
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all download tasks
                future_to_file = {executor.submit(self.download_single_file, task): task for task in files_to_download}
                
                # Process completed downloads
                for future in as_completed(future_to_file):
                    task = future_to_file[future]
                    result = future.result()
                    
                    if result['success']:
                        if result['skipped']:
                            skipped_count += 1
                        else:
                            downloaded_count += 1
                    else:
                        failed_count += 1
                        # Track failure with reason
                        failed_files.append({
                            'name': result['name'],
                            'path': str(result['path']),
                            'error': result.get('error', 'Unknown error')
                        })
                    
                    # Save progress every 10 files
                    if (downloaded_count + skipped_count + failed_count) % 10 == 0:
                        save_progress()
                    
                    # Show progress
                    total_processed = downloaded_count + skipped_count + failed_count
                    print(f"  Progress: {total_processed}/{len(files_to_download)} (Downloaded: {downloaded_count}, Skipped: {skipped_count}, Failed: {failed_count})", end='\r')
            
            print()  # New line after progress
            
            # Final save
            save_progress()
            
            # Print summary
            print("\n" + "="*50)
            print("📊 BACKUP SUMMARY")
            print("="*50)
            print(f"Total files processed: {len(files_to_download)}")
            print(f"Successfully downloaded: {downloaded_count}")
            print(f"Skipped (unchanged): {skipped_count}")
            print(f"Failed: {failed_count}")
            print(f"Backup location: {backup_root}")
            
            # List failed files with reasons
            if failed_files:
                print(f"\n❌ Failed Files ({len(failed_files)} total):")
                print("-" * 50)
                
                # Categorize failures
                dns_failures = []
                network_failures = []
                http_failures = []
                other_failures = []
                
                for failed in failed_files:
                    error = failed['error']
                    if 'Failed to resolve' in error or 'nodename nor servname' in error:
                        dns_failures.append(failed)
                    elif 'IncompleteRead' in error or 'Connection broken' in error:
                        network_failures.append(failed)
                    elif 'HTTP' in error:
                        http_failures.append(failed)
                    else:
                        other_failures.append(failed)
                
                # Show DNS failures
                if dns_failures:
                    print(f"\n🌐 DNS Resolution Errors ({len(dns_failures)} files):")
                    print("   Cause: Temporary DNS issues")
                    print("   Action: Retry - these should work on second attempt\n")
                    for failed in dns_failures[:5]:  # Show first 5
                        # Show relative path from backup root for clarity
                        try:
                            rel_path = Path(failed['path']).relative_to(backup_root)
                            print(f"   • {rel_path}")
                        except:
                            print(f"   • {failed['name']}")
                    if len(dns_failures) > 5:
                        print(f"   ... and {len(dns_failures) - 5} more")
                
                # Show network failures  
                if network_failures:
                    print(f"\n🔌 Network Connection Errors ({len(network_failures)} files):")
                    print("   Cause: Download interrupted mid-transfer")
                    print("   Action: Retry - these should work on second attempt\n")
                    for failed in network_failures[:5]:
                        try:
                            rel_path = Path(failed['path']).relative_to(backup_root)
                            print(f"   • {rel_path}")
                        except:
                            print(f"   • {failed['name']}")
                        if len(failed['error']) < 100:  # Show short errors
                            print(f"     Error: {failed['error']}")
                    if len(network_failures) > 5:
                        print(f"   ... and {len(network_failures) - 5} more")
                
                # Show HTTP failures
                if http_failures:
                    print(f"\n⚠️  HTTP Errors ({len(http_failures)} files):")
                    print("   Cause: Server returned error")
                    print("   Action: May need manual intervention\n")
                    for failed in http_failures[:5]:
                        try:
                            rel_path = Path(failed['path']).relative_to(backup_root)
                            print(f"   • {rel_path} - {failed['error']}")
                        except:
                            print(f"   • {failed['name']} - {failed['error']}")
                    if len(http_failures) > 5:
                        print(f"   ... and {len(http_failures) - 5} more")
                
                # Show other failures
                if other_failures:
                    print(f"\n❓ Other Errors ({len(other_failures)} files):")
                    for failed in other_failures[:5]:
                        try:
                            rel_path = Path(failed['path']).relative_to(backup_root)
                            print(f"   • {rel_path}")
                        except:
                            print(f"   • {failed['name']}")
                        print(f"     Error: {failed['error'][:100]}")
                    if len(other_failures) > 5:
                        print(f"   ... and {len(other_failures) - 5} more")
                
                print(f"\n💡 To retry failed files, run the script again with the same settings.")
                print(f"   The script will skip successfully downloaded files and only retry the {len(failed_files)} that failed.")
            
            if self.verification_failures:
                print(f"\n⚠️  Verification Warnings ({len(self.verification_failures)} files):")
                for failed_file in self.verification_failures[:10]:
                    print(f"  - {failed_file}")
                if len(self.verification_failures) > 10:
                    print(f"  ... and {len(self.verification_failures) - 10} more")
                print("\nThese files downloaded but failed verification. They may be corrupt.")
                print("Consider re-downloading them or checking manually.")
            
            print(f"\n✅ Folder structure preserved exactly as in OneDrive!")
            
            # Clean up progress file on successful completion
            if self.progress_file.exists() and failed_count == 0:
                self.progress_file.unlink()
            
            return {'success': True, 'failed_count': failed_count, 'downloaded_count': downloaded_count}
            
        except KeyboardInterrupt:
            print("\n\n⏸️  Backup interrupted by user.")
            save_progress()
            print(f"Progress saved! Run the script again to resume from where you left off.")
            print(f"Downloaded so far: {downloaded_count} files")
            return {'success': False, 'failed_count': failed_count, 'downloaded_count': downloaded_count}
        except Exception as e:
            print(f"❌ Download error: {e}")
            save_progress()
            print(f"Progress saved. You can resume by running the script again.")
            return {'success': False, 'failed_count': failed_count, 'downloaded_count': downloaded_count}
    
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
    print("OneDrive Backup Tool - Enhanced Edition")
    print("="*50)
    print("\n🚀 Features:")
    print("  ✓ Multi-threaded downloads (3x faster)")
    print("  ✓ Disk space verification")
    print("  ✓ File integrity verification")
    print("  ✓ Incremental backups (skip unchanged files)")
    print("  ✓ Resume capability")
    
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
    
    destination_path = Path(destination)
    if not destination_path.exists():
        print(f"❌ Destination drive '{destination}' not found!")
        return
    
    # Check for existing backups and ask user BEFORE asking what to backup
    existing_backups = sorted([d for d in destination_path.glob("OneDrive_Backup_*") if d.is_dir()], 
                             key=lambda x: x.stat().st_mtime, reverse=True)
    
    resume_backup_path = None
    if existing_backups:
        print("\n📂 Found existing backup(s):")
        for i, backup_dir in enumerate(existing_backups[:5], 1):
            progress_file = backup_dir / ".progress.json"
            metadata_file = backup_dir / ".backup_metadata.json"
            
            if progress_file.exists():
                try:
                    with open(progress_file, 'r') as f:
                        progress_data = json.load(f)
                        file_count = len(progress_data.get('downloaded_files', {}))
                    print(f"  {i}. {backup_dir.name} ({file_count} files already downloaded) - INCOMPLETE")
                except:
                    print(f"  {i}. {backup_dir.name} (progress file exists)")
            elif metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                        file_count = len(metadata.get('files', {}))
                    print(f"  {i}. {backup_dir.name} ({file_count} files) - COMPLETE")
                except:
                    print(f"  {i}. {backup_dir.name}")
            else:
                print(f"  {i}. {backup_dir.name}")
        
        print(f"  {len(existing_backups) + 1}. Start a new backup")
        
        choice = input(f"\nResume which backup? (1-{len(existing_backups) + 1}): ").strip()
        try:
            choice_num = int(choice)
            if 1 <= choice_num <= len(existing_backups):
                resume_backup_path = existing_backups[choice_num - 1]
                print(f"\n✓ Will resume: {resume_backup_path.name}")
            else:
                print(f"\n✓ Will start a new backup")
        except (ValueError, IndexError):
            print(f"\n✓ Will start a new backup")
    else:
        print("\n✓ No existing backups found - will start new backup")
    
    # Ask what to backup
    print("\nWhat would you like to backup?")
    print("1. Documents only")
    print("2. Pictures only")
    print("3. Videos only")
    print("4. Documents and Pictures")
    print("5. Documents and Videos")
    print("6. Pictures and Videos")
    print("7. Documents, Pictures, and Videos")
    print("8. All Files (everything, including audio, web pages, etc.)")
    choice = input("Enter choice (1-8): ").strip()
    
    include_all = choice == '8'
    include_docs = choice in ['1', '4', '5', '7']
    include_pics = choice in ['2', '4', '6', '7']
    include_videos = choice in ['3', '5', '6', '7']
    
    print("\n🚀 Starting backup...")
    
    # Backup loop - allows retrying failed files
    while True:
        if backup.use_api:
            result = backup.download_from_api(destination, include_docs, include_pics, include_videos, include_all, resume_backup_path)
        else:
            result = backup.backup_files(destination, include_docs, include_pics)
            result = {'success': True, 'failed_count': 0, 'downloaded_count': 0}  # Local backup doesn't track failures the same way
        
        # Check if any files failed
        if isinstance(result, dict) and result.get('failed_count', 0) > 0:
            print(f"\n{'='*50}")
            print(f"⚠️  {result['failed_count']} files failed to download.")
            print(f"{'='*50}")
            retry = input(f"\n🔄 Retry failed files now? (y/n): ").strip().lower()
            
            if retry == 'y' or retry == 'yes':
                print(f"\n🔄 Retrying {result['failed_count']} failed files...")
                print(f"Note: Successfully downloaded files will be skipped.\n")
                # Keep the same resume_backup_path to continue in same folder
                continue
            else:
                print(f"\n💡 To retry later, run the script again and choose the same backup.")
                break
        else:
            # No failures or user cancelled
            break
    
    print("\n✅ Backup complete!")

if __name__ == "__main__":
    main()
