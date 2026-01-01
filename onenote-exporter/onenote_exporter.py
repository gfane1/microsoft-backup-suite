#!/usr/bin/env python3
"""
OneNote Export Tool v3.1
Exports OneNote notebooks with all attachments for import into Evernote, Joplin, etc.

Features:
- Interactive notebook/section selection
- Full pagination with @odata.nextLink support
- Robust retry with exponential backoff for 429/503/504/5xx
- File logging for diagnostics
- Page hierarchy support (parent/child pages)
- Navigable index.md with clickable links
- Hierarchical folder structure for parent/child pages
- Orphan detection and handling
- Settings file support (client_secret never stored)
"""

import os
import sys
import json
import argparse
import requests
import webbrowser
import getpass
import time
import random
import logging
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import base64
import html
import re
from typing import Dict, List, Optional, Any, Tuple
import mimetypes

# ============================================================================
# Constants
# ============================================================================
VERSION = "3.2.0"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_MAX_RETRIES = 10
DEFAULT_TIMEOUT = 60


# ============================================================================
# Logging Setup
# ============================================================================
class FileAndConsoleLogger:
    """Dual logger: detailed file logging + clean console output."""
    
    def __init__(self, log_path: Path = None):
        self.log_path = log_path
        self.file_handler = None
        self.console_logger = logging.getLogger('console')
        self.file_logger = logging.getLogger('file')
        
        # Console: INFO level, clean format
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        self.console_logger.addHandler(console_handler)
        self.console_logger.setLevel(logging.INFO)
        
    def set_log_file(self, log_path: Path):
        """Set up file logging."""
        self.log_path = log_path
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s'
        ))
        self.file_logger.addHandler(file_handler)
        self.file_logger.setLevel(logging.DEBUG)
        
    def info(self, msg: str):
        self.console_logger.info(msg)
        if self.log_path:
            self.file_logger.info(msg)
            
    def debug(self, msg: str):
        if self.log_path:
            self.file_logger.debug(msg)
            
    def warning(self, msg: str):
        self.console_logger.warning(f"⚠️  {msg}")
        if self.log_path:
            self.file_logger.warning(msg)
            
    def error(self, msg: str):
        self.console_logger.error(f"❌ {msg}")
        if self.log_path:
            self.file_logger.error(msg)
            
    def api_error(self, method: str, url: str, status: int, context: str, 
                  attempt: int, error_msg: str = None):
        """Log API error with full details to file."""
        # Redact tokens from URL
        safe_url = re.sub(r'access_token=[^&]+', 'access_token=REDACTED', url)
        safe_url = re.sub(r'Bearer [^\s]+', 'Bearer REDACTED', safe_url)
        
        log_entry = (
            f"API ERROR | {method} {safe_url} | "
            f"Status: {status} | Context: {context} | "
            f"Attempt: {attempt} | Error: {error_msg or 'N/A'}"
        )
        if self.log_path:
            self.file_logger.error(log_entry)


logger = FileAndConsoleLogger()


# ============================================================================
# Settings
# ============================================================================
def get_settings_path() -> Path:
    """Get settings.json path - checks multiple locations in order."""
    # When running as PyInstaller exe, sys.executable is the exe path
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        exe_settings = exe_dir / 'settings.json'
        if exe_settings.exists():
            return exe_settings
    
    # Check script directory first (onenote-exporter/)
    script_dir = Path(__file__).parent
    script_settings = script_dir / 'settings.json'
    if script_settings.exists():
        return script_settings
    
    # Check parent directory (project root)
    parent_settings = script_dir.parent / 'settings.json'
    if parent_settings.exists():
        return parent_settings
    
    # Default to script directory for new file creation
    return script_settings


def save_settings(settings_path: Path, client_id: str, client_secret: str, 
                  export_folder: str, tenant: str = 'consumers'):
    """Save settings to JSON file in flat format."""
    settings = {
        "application_client_id": client_id,
        "client_secret_value": client_secret,
        "export_folder": export_folder,
        "tenant": tenant
    }
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4)
    logger.info(f"✓ Settings saved to {settings_path}")


def load_settings(settings_path: Path) -> Dict[str, Any]:
    """Load settings from JSON file. Supports both flat and nested formats."""
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            raw_settings = json.load(f)
        
        # Check if using new flat format (application_client_id, client_secret_value, export_folder)
        if 'application_client_id' in raw_settings:
            # Convert flat format to nested format used internally
            settings = {
                'auth': {
                    'client_id': raw_settings.get('application_client_id'),
                    'client_secret': raw_settings.get('client_secret_value'),
                    'tenant': raw_settings.get('tenant', 'consumers')
                },
                'export': {
                    'output_root': raw_settings.get('export_folder'),
                    'format': raw_settings.get('format', 'joplin')
                }
            }
            return settings
        
        # Legacy nested format - still supported but client_secret not loaded for security
        if 'auth' in raw_settings and 'client_secret' in raw_settings.get('auth', {}):
            del raw_settings['auth']['client_secret']
        return raw_settings
    except Exception as e:
        logger.warning(f"Could not load settings.json: {e}")
        return {}


def save_json(filepath: Path, data: Any, indent: int = 2):
    """Save data to JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=str)


# ============================================================================
# Graph API Client with Robust Retry
# ============================================================================
class GraphClient:
    """Microsoft Graph API client with robust retry logic."""
    
    def __init__(self, max_retries: int = DEFAULT_MAX_RETRIES):
        self.access_token = None
        self.refresh_token = None
        self.client_id = None
        self.client_secret = None
        self.tenant_id = None
        self.max_retries = max_retries
        self.request_count = 0
        self.error_count = 0
        
    def make_request(self, url: str, context: str = "", method: str = 'GET',
                     timeout: int = DEFAULT_TIMEOUT) -> Optional[requests.Response]:
        """Make API request with retry logic for transient errors."""
        headers = {'Authorization': f'Bearer {self.access_token}'}
        
        for attempt in range(1, self.max_retries + 1):
            self.request_count += 1
            
            try:
                logger.debug(f"Request {self.request_count}: {method} {url[:100]}...")
                
                if method == 'GET':
                    response = requests.get(url, headers=headers, timeout=timeout)
                else:
                    response = requests.post(url, headers=headers, timeout=timeout)
                
                # Success
                if response.status_code == 200:
                    return response
                
                # Handle 401 - token expired
                if response.status_code == 401 and self.refresh_token:
                    logger.debug("Token expired, refreshing...")
                    if self._refresh_access_token():
                        headers['Authorization'] = f'Bearer {self.access_token}'
                        continue
                    else:
                        logger.error("Token refresh failed")
                        return None
                
                # Handle rate limiting (429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 10))
                    logger.warning(f"Rate limited (429), waiting {retry_after}s... [{context}]")
                    logger.api_error(method, url, 429, context, attempt, "Rate limited")
                    time.sleep(retry_after)
                    continue
                
                # Handle server errors (5xx)
                if response.status_code >= 500:
                    wait_time = min(60, (2 ** attempt) + random.uniform(0, 2))
                    error_snippet = response.text[:200] if response.text else "No response body"
                    logger.warning(f"Server error {response.status_code}, retry {attempt}/{self.max_retries} in {wait_time:.1f}s [{context}]")
                    logger.api_error(method, url, response.status_code, context, attempt, error_snippet)
                    self.error_count += 1
                    time.sleep(wait_time)
                    continue
                
                # Other errors - log and return
                logger.api_error(method, url, response.status_code, context, attempt, 
                               response.text[:200] if response.text else None)
                self.error_count += 1
                return response
                
            except requests.exceptions.Timeout:
                wait_time = min(60, (2 ** attempt) + random.uniform(0, 2))
                logger.warning(f"Timeout, retry {attempt}/{self.max_retries} in {wait_time:.1f}s [{context}]")
                logger.api_error(method, url, 0, context, attempt, "Timeout")
                self.error_count += 1
                time.sleep(wait_time)
                
            except requests.exceptions.ConnectionError as e:
                wait_time = min(60, (2 ** attempt) + random.uniform(0, 2))
                logger.warning(f"Connection error, retry {attempt}/{self.max_retries} [{context}]")
                logger.api_error(method, url, 0, context, attempt, str(e))
                self.error_count += 1
                time.sleep(wait_time)
                
            except Exception as e:
                logger.api_error(method, url, 0, context, attempt, str(e))
                logger.error(f"Unexpected error: {e} [{context}]")
                self.error_count += 1
                if attempt == self.max_retries:
                    return None
                time.sleep(1)
        
        logger.error(f"Max retries ({self.max_retries}) exceeded [{context}]")
        return None
    
    def _refresh_access_token(self) -> bool:
        """Refresh the access token."""
        if not self.refresh_token:
            return False
        
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=30)
            result = response.json()
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.refresh_token = result.get('refresh_token', self.refresh_token)
                logger.info("✅ Token refreshed")
                return True
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
        return False
    
    def get_all_pages(self, initial_url: str, context: str = "") -> Tuple[List[Dict], List[Dict]]:
        """
        Follow all @odata.nextLink pages and return (items, errors).
        Returns tuple of (all_items, error_list) to track pagination failures.
        """
        all_items = []
        errors = []
        url = initial_url
        page_num = 0
        
        while url:
            page_num += 1
            page_context = f"{context} [page {page_num}]"
            
            response = self.make_request(url, context=page_context)
            
            if not response:
                errors.append({
                    'url': url,
                    'context': page_context,
                    'page': page_num,
                    'error': 'No response after retries'
                })
                break
            
            if response.status_code != 200:
                errors.append({
                    'url': url,
                    'context': page_context,
                    'page': page_num,
                    'status': response.status_code,
                    'error': response.text[:200] if response.text else 'Unknown'
                })
                break
            
            try:
                data = response.json()
            except Exception as e:
                errors.append({
                    'url': url,
                    'context': page_context,
                    'page': page_num,
                    'error': f'JSON parse error: {e}'
                })
                break
            
            items = data.get('value', [])
            all_items.extend(items)
            
            # Check for nextLink (pagination)
            next_link = data.get('@odata.nextLink')
            if next_link:
                logger.debug(f"Following nextLink: page {page_num} -> {page_num + 1} ({len(items)} items) [{context}]")
                url = next_link
                time.sleep(0.1)  # Be nice to the API
            else:
                url = None
        
        return all_items, errors


# ============================================================================
# OneNote Exporter v3.0
# ============================================================================
class OneNoteExporter:
    """Main exporter class with interactive selection and robust handling."""
    
    def __init__(self, settings: Dict[str, Any] = None, settings_path: Path = None):
        self.settings = settings or {}
        self.settings_path = settings_path  # For saving new settings
        self.graph = GraphClient(
            max_retries=self.settings.get('export', {}).get('max_retries', DEFAULT_MAX_RETRIES)
        )
        self.export_root = None
        self.user_info = {}
        self.preflight_data = {}
        self.preflight_errors = []
        self.export_errors = []
        self.skipped_items = []
        self.index_result = None  # Result from index_builder
        
        self.stats = {
            'notebooks': 0,
            'section_groups': 0,
            'sections': 0,
            'pages': 0,
            'child_pages': 0,
            'attachments': 0,
            'images': 0,
            'errors': 0,
            'orphans': 0
        }
        
        # Track if settings were loaded from file
        self._settings_from_file = bool(settings)
        
        # Load settings
        auth_settings = self.settings.get('auth', {})
        self.graph.client_id = auth_settings.get('client_id')
        self.graph.client_secret = auth_settings.get('client_secret')  # From settings.json if present
        self.graph.tenant_id = auth_settings.get('tenant', 'consumers')
        
        export_settings = self.settings.get('export', {})
        self.output_root = export_settings.get('output_root')
        self.export_format = export_settings.get('format', 'joplin')
        self.preflight_mode = export_settings.get('preflight_mode', 'counts_only')
        
        # Selection state
        self.selected_notebook = None
        self.selected_section = None

    def authenticate(self) -> bool:
        """Authenticate with Microsoft Graph API."""
        print("\n" + "=" * 70)
        print(f"OneNote Export Tool v{VERSION} - Authentication")
        print("=" * 70)
        
        settings_changed = False
        
        # Check for client_id from settings
        if self.graph.client_id:
            logger.info(f"✓ Client ID loaded from settings.json")
        else:
            print("\n📋 You need a Microsoft App Registration to use this tool.")
            print("\nQuick Setup:")
            print("1. Go to: https://entra.microsoft.com/")
            print("2. App registrations → New registration")
            print("3. Redirect URI: Web → http://localhost:8080")
            print("4. Add API permissions: Notes.Read, Notes.Read.All, User.Read")
            print("=" * 70 + "\n")
            self.graph.client_id = input("Enter Application (client) ID: ").strip()
            settings_changed = True
        
        # Client secret - check settings first, then env var, then prompt
        if self.graph.client_secret:
            logger.info("✓ Client secret loaded from settings.json")
        else:
            self.graph.client_secret = os.environ.get('ONENOTE_CLIENT_SECRET')
            if self.graph.client_secret:
                logger.info("✓ Client secret loaded from ONENOTE_CLIENT_SECRET env var")
            else:
                print("\n🔐 Client secret required")
                self.graph.client_secret = getpass.getpass("Enter Client Secret (hidden): ")
                settings_changed = True
        
        if not self.graph.client_secret:
            logger.error("Client secret is required")
            return False
        
        # Tenant
        if not self.graph.tenant_id:
            self.graph.tenant_id = input("Enter Tenant ID [consumers]: ").strip() or 'consumers'
            settings_changed = True
        
        # Export folder - check if we need to prompt
        if not self.output_root:
            print("\n📁 Where would you like to save exports?")
            self.output_root = input("Enter export folder path (e.g., C:\\OneNote-Exports): ").strip()
            if not self.output_root:
                self.output_root = str(Path.home() / "OneNote-Exports")
                print(f"Using default: {self.output_root}")
            settings_changed = True
        else:
            logger.info(f"✓ Export folder: {self.output_root}")
        
        # Save settings if anything was entered manually
        if settings_changed and self.settings_path:
            save_choice = input("\n💾 Save these settings for next time? [Y/n]: ").strip().lower()
            if save_choice != 'n':
                save_settings(
                    self.settings_path,
                    self.graph.client_id,
                    self.graph.client_secret,
                    self.output_root,
                    self.graph.tenant_id
                )
        
        return self._delegated_auth_flow()
    
    def _capture_oauth_callback(self, auth_url: str, port: int = 8080, timeout: int = 120) -> Optional[str]:
        """
        Start a temporary local HTTP server to capture the OAuth callback.
        Returns the authorization code or None if capture failed.
        """
        captured_code = {'code': None, 'error': None}
        server_ready = threading.Event()
        
        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                """Handle the OAuth callback."""
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                
                if 'code' in params:
                    captured_code['code'] = params['code'][0]
                    # Send a nice success page
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    success_html = '''
                    <!DOCTYPE html>
                    <html>
                    <head><title>Authentication Successful</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1 style="color: #28a745;">✅ Authentication Successful!</h1>
                        <p>You can close this browser tab and return to the application.</p>
                    </body>
                    </html>
                    '''
                    self.wfile.write(success_html.encode())
                elif 'error' in params:
                    captured_code['error'] = params.get('error_description', params.get('error', ['Unknown error']))[0]
                    self.send_response(400)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    error_html = f'''
                    <!DOCTYPE html>
                    <html>
                    <head><title>Authentication Failed</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1 style="color: #dc3545;">❌ Authentication Failed</h1>
                        <p>{captured_code['error']}</p>
                    </body>
                    </html>
                    '''
                    self.wfile.write(error_html.encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def log_message(self, format, *args):
                # Suppress HTTP server logging
                pass
        
        def run_server():
            try:
                server = HTTPServer(('localhost', port), CallbackHandler)
                server.timeout = 1  # Check for shutdown every second
                server_ready.set()
                
                start_time = time.time()
                while time.time() - start_time < timeout:
                    server.handle_request()
                    if captured_code['code'] or captured_code['error']:
                        break
                server.server_close()
            except Exception as e:
                captured_code['error'] = str(e)
                server_ready.set()
        
        # Check if port is available
        try:
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(1)
            result = test_socket.connect_ex(('localhost', port))
            test_socket.close()
            if result == 0:
                # Port is in use
                logger.warning(f"Port {port} is in use. Falling back to manual URL paste.")
                return None
        except Exception:
            pass
        
        # Start server in background thread
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        
        # Wait for server to be ready
        if not server_ready.wait(timeout=5):
            logger.warning("Could not start callback server. Falling back to manual URL paste.")
            return None
        
        print(f"🌐 Listening on http://localhost:{port} for OAuth callback...")
        print("Opening browser for authentication...")
        webbrowser.open(auth_url)
        
        print(f"\n⏳ Waiting for authentication (timeout: {timeout}s)...")
        print("   Complete the sign-in in your browser.\n")
        
        # Wait for callback
        server_thread.join(timeout=timeout)
        
        if captured_code['error']:
            logger.error(f"OAuth error: {captured_code['error']}")
            return None
        
        if captured_code['code']:
            logger.info("✅ Authorization code captured automatically!")
            return captured_code['code']
        
        logger.warning("Timeout waiting for OAuth callback.")
        return None

    def _delegated_auth_flow(self) -> bool:
        """Interactive OAuth flow with automatic callback capture."""
        logger.info("\n🔐 Starting authentication...")
        
        redirect_uri = "http://localhost:8080"
        scope = "Notes.Read Notes.Read.All User.Read offline_access"
        auth_url = (
            f"https://login.microsoftonline.com/{self.graph.tenant_id}/oauth2/v2.0/authorize"
            f"?client_id={self.graph.client_id}"
            f"&response_type=code"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
        )
        
        # Try to start local server to capture callback automatically
        code = self._capture_oauth_callback(auth_url)
        
        if not code:
            # Fallback to manual paste if server failed
            print("\nAfter signing in, copy the full URL from your browser.")
            print("(It will show an error page, but that's normal)")
            redirect_response = input("\nPaste the redirect URL here: ").strip()
            
            try:
                parsed = urlparse(redirect_response)
                code = parse_qs(parsed.query)['code'][0]
            except Exception:
                logger.error("Could not extract authorization code from URL")
                return False
        
        token_url = f"https://login.microsoftonline.com/{self.graph.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.graph.client_id,
            'client_secret': self.graph.client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=30)
            result = response.json()
            
            if 'access_token' in result:
                self.graph.access_token = result['access_token']
                self.graph.refresh_token = result.get('refresh_token')
                logger.info("✅ Successfully authenticated!")
                self._fetch_user_info()
                return True
            else:
                logger.error(f"Auth failed: {result.get('error_description', 'Unknown')}")
                return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    def _fetch_user_info(self):
        """Get signed-in user info."""
        response = self.graph.make_request(f"{GRAPH_BASE}/me", "user info")
        if response and response.status_code == 200:
            data = response.json()
            self.user_info = {
                'displayName': data.get('displayName', 'Unknown'),
                'mail': data.get('mail') or data.get('userPrincipalName', 'Unknown'),
            }
            logger.info(f"   Signed in as: {self.user_info['displayName']} ({self.user_info['mail']})")
    
    # =========================================================================
    # Interactive Selection
    # =========================================================================
    
    def select_export_scope(self) -> bool:
        """Interactive notebook and section selection."""
        print("\n" + "=" * 70)
        print("📚 SELECT EXPORT SCOPE")
        print("=" * 70)
        
        # Get all notebooks
        logger.info("\nFetching notebooks...")
        notebooks, errors = self.graph.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/notebooks",
            "list notebooks"
        )
        
        if errors:
            for err in errors:
                logger.warning(f"Error fetching notebooks: {err}")
        
        if not notebooks:
            logger.error("No notebooks found!")
            return False
        
        # Notebook selection
        print(f"\nFound {len(notebooks)} notebook(s):\n")
        print("  0. Export ALL notebooks")
        for idx, nb in enumerate(notebooks, 1):
            print(f"  {idx}. {nb.get('displayName', 'Untitled')}")
        
        choice = input("\nSelect notebook [0]: ").strip()
        
        if choice == '' or choice == '0':
            self.selected_notebook = None  # Export all
            logger.info("Selected: ALL notebooks")
            return True
        
        try:
            nb_idx = int(choice) - 1
            if 0 <= nb_idx < len(notebooks):
                self.selected_notebook = notebooks[nb_idx]
                logger.info(f"Selected notebook: {self.selected_notebook['displayName']}")
            else:
                logger.error("Invalid selection")
                return False
        except ValueError:
            logger.error("Invalid input")
            return False
        
        # Section selection (only if single notebook selected)
        if self.selected_notebook:
            return self._select_section()
        
        return True
    
    def _select_section(self) -> bool:
        """Select a section within the selected notebook."""
        nb_id = self.selected_notebook['id']
        nb_name = self.selected_notebook['displayName']
        
        logger.info(f"\nFetching sections for '{nb_name}'...")
        
        # Get direct sections
        sections, errors = self.graph.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/notebooks/{nb_id}/sections",
            f"sections in {nb_name}"
        )
        
        # Get section groups and their sections
        section_groups, sg_errors = self.graph.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/notebooks/{nb_id}/sectionGroups",
            f"section groups in {nb_name}"
        )
        
        all_sections = []
        section_map = {}  # idx -> (section, parent_path)
        
        # Add direct sections
        for sec in sections:
            all_sections.append((sec, ""))
        
        # Add sections from section groups (recursive)
        def add_sections_from_group(sg, parent_path=""):
            path = f"{parent_path}/{sg['displayName']}" if parent_path else sg['displayName']
            
            # Get sections in this group
            sg_sections, _ = self.graph.get_all_pages(
                f"{GRAPH_BASE}/me/onenote/sectionGroups/{sg['id']}/sections",
                f"sections in group {path}"
            )
            for sec in sg_sections:
                all_sections.append((sec, path))
            
            # Get nested groups
            nested_groups, _ = self.graph.get_all_pages(
                f"{GRAPH_BASE}/me/onenote/sectionGroups/{sg['id']}/sectionGroups",
                f"nested groups in {path}"
            )
            for nested in nested_groups:
                add_sections_from_group(nested, path)
        
        for sg in section_groups:
            add_sections_from_group(sg)
        
        if not all_sections:
            logger.warning("No sections found in this notebook")
            return True
        
        print(f"\nFound {len(all_sections)} section(s):\n")
        print("  0. Export ALL sections")
        for idx, (sec, path) in enumerate(all_sections, 1):
            sec_name = sec.get('displayName', 'Untitled')
            display = f"{path}/{sec_name}" if path else sec_name
            print(f"  {idx}. {display}")
        
        choice = input("\nSelect section [0]: ").strip()
        
        if choice == '' or choice == '0':
            self.selected_section = None  # Export all sections
            logger.info("Selected: ALL sections")
            return True
        
        try:
            sec_idx = int(choice) - 1
            if 0 <= sec_idx < len(all_sections):
                self.selected_section = all_sections[sec_idx][0]
                logger.info(f"Selected section: {self.selected_section['displayName']}")
            else:
                logger.error("Invalid selection")
                return False
        except ValueError:
            logger.error("Invalid input")
            return False
        
        return True
    
    # =========================================================================
    # Preflight Scan
    # =========================================================================
    
    def run_preflight(self) -> Dict:
        """Perform preflight inventory scan."""
        print("\n" + "=" * 70)
        print("📋 PREFLIGHT INVENTORY SCAN")
        print("=" * 70)
        
        # Determine scope description
        if self.selected_notebook and self.selected_section:
            scope = f"Section: {self.selected_section['displayName']} in {self.selected_notebook['displayName']}"
        elif self.selected_notebook:
            scope = f"Notebook: {self.selected_notebook['displayName']}"
        else:
            scope = "All notebooks"
        
        logger.info(f"Scope: {scope}")
        logger.info(f"Account: {self.user_info.get('displayName', 'Unknown')}")
        logger.info(f"Tenant: {self.graph.tenant_id}")
        logger.info(f"Mode: {self.preflight_mode}")
        print()
        
        inventory = {
            'scan_timestamp': datetime.now().isoformat(),
            'account': self.user_info,
            'tenant': self.graph.tenant_id,
            'scope': scope,
            'preflight_mode': self.preflight_mode,
            'notebooks': [],
            'errors': [],
            'totals': {
                'notebooks': 0,
                'section_groups': 0,
                'sections': 0,
                'pages': 0
            }
        }
        
        # Get notebooks to scan
        if self.selected_notebook:
            notebooks = [self.selected_notebook]
        else:
            notebooks, errors = self.graph.get_all_pages(
                f"{GRAPH_BASE}/me/onenote/notebooks",
                "list notebooks"
            )
            inventory['errors'].extend(errors)
        
        inventory['totals']['notebooks'] = len(notebooks)
        logger.info(f"Scanning {len(notebooks)} notebook(s)...\n")
        
        for nb_idx, notebook in enumerate(notebooks, 1):
            nb_name = notebook.get('displayName', 'Untitled')
            logger.info(f"[{nb_idx}/{len(notebooks)}] 📓 {nb_name}")
            
            nb_data = {
                'id': notebook['id'],
                'name': nb_name,
                'createdDateTime': notebook.get('createdDateTime'),
                'lastModifiedDateTime': notebook.get('lastModifiedDateTime'),
                'section_groups': [],
                'sections': [],
                'page_count': 0,
                'errors': []
            }
            
            # If single section selected, only scan that
            if self.selected_section:
                sec_data = self._scan_section(self.selected_section, nb_name)
                nb_data['sections'].append(sec_data)
                nb_data['page_count'] = sec_data['page_count']
                inventory['totals']['sections'] += 1
                inventory['totals']['pages'] += sec_data['page_count']
            else:
                # Scan all sections and section groups
                nb_url = f"{GRAPH_BASE}/me/onenote/notebooks/{notebook['id']}"
                
                # Direct sections
                sections, errors = self.graph.get_all_pages(
                    f"{nb_url}/sections",
                    f"sections in {nb_name}"
                )
                nb_data['errors'].extend(errors)
                
                for section in sections:
                    sec_data = self._scan_section(section, nb_name)
                    nb_data['sections'].append(sec_data)
                    nb_data['page_count'] += sec_data['page_count']
                    inventory['totals']['sections'] += 1
                    inventory['totals']['pages'] += sec_data['page_count']
                
                # Section groups (recursive)
                section_groups = self._scan_section_groups_recursive(
                    nb_url, nb_name, inventory['totals']
                )
                nb_data['section_groups'] = section_groups
                
                for sg in section_groups:
                    nb_data['page_count'] += self._count_pages_in_section_group(sg)
            
            inventory['notebooks'].append(nb_data)
            logger.info(f"      Total: {nb_data['page_count']} pages")
        
        self.preflight_data = inventory
        self.preflight_errors = inventory['errors']
        
        print()
        print("=" * 70)
        print("📊 PREFLIGHT TOTALS")
        print("=" * 70)
        print(f"   Notebooks:      {inventory['totals']['notebooks']}")
        print(f"   Section Groups: {inventory['totals']['section_groups']}")
        print(f"   Sections:       {inventory['totals']['sections']}")
        print(f"   Pages:          {inventory['totals']['pages']}")
        if inventory['errors']:
            print(f"   ⚠️  Errors:      {len(inventory['errors'])}")
        print("=" * 70)
        
        return inventory
    
    def _scan_section(self, section: Dict, notebook_name: str) -> Dict:
        """Scan a section and enumerate pages."""
        sec_name = section.get('displayName', 'Untitled')
        sec_id = section['id']
        context = f"{notebook_name}/{sec_name}"
        
        # Get pages with pagination
        pages, errors = self.graph.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/sections/{sec_id}/pages?$select=id,title,createdDateTime,lastModifiedDateTime,level,order&$orderby=order",
            context
        )
        
        # Log if we got zero pages but expected more
        if not pages and errors:
            logger.warning(f"Section '{sec_name}' returned 0 pages with errors!")
            for err in errors:
                logger.warning(f"  Error: {err}")
        
        # Build page hierarchy
        page_list = []
        child_count = 0
        
        # Debug: log level values for first section with pages
        if pages:
            level_values = [p.get('level', 'NOT_PRESENT') for p in pages[:5]]
            logger.debug(f"Level values from API for '{sec_name}': {level_values}")
        
        for p in pages:
            level = p.get('level', 0)
            if level > 0:
                child_count += 1
            page_list.append({
                'id': p['id'],
                'title': p.get('title', 'Untitled'),
                'createdDateTime': p.get('createdDateTime'),
                'lastModifiedDateTime': p.get('lastModifiedDateTime'),
                'level': level,
                'order': p.get('order', 0)
            })
        
        page_info = f"{len(pages)} pages"
        if child_count > 0:
            page_info += f" ({child_count} child)"
        logger.info(f"      📑 {sec_name}: {page_info}")
        
        return {
            'id': sec_id,
            'name': sec_name,
            'page_count': len(pages),
            'child_page_count': child_count,
            'pages': page_list,
            'errors': errors
        }
    
    def _scan_section_groups_recursive(self, parent_url: str, parent_name: str, 
                                       totals: Dict, depth: int = 0) -> List[Dict]:
        """Recursively scan section groups."""
        section_groups, errors = self.graph.get_all_pages(
            f"{parent_url}/sectionGroups",
            f"section groups under {parent_name}"
        )
        
        result = []
        indent = "      " + "  " * depth
        
        for sg in section_groups:
            sg_name = sg.get('displayName', 'Untitled')
            logger.info(f"{indent}📁 {sg_name}")
            totals['section_groups'] += 1
            
            sg_data = {
                'id': sg['id'],
                'name': sg_name,
                'sections': [],
                'section_groups': [],
                'errors': errors
            }
            
            sg_url = f"{GRAPH_BASE}/me/onenote/sectionGroups/{sg['id']}"
            
            # Get sections in this group
            sections, sec_errors = self.graph.get_all_pages(
                f"{sg_url}/sections",
                f"sections in {parent_name}/{sg_name}"
            )
            sg_data['errors'].extend(sec_errors)
            
            for section in sections:
                sec_data = self._scan_section(section, f"{parent_name}/{sg_name}")
                sg_data['sections'].append(sec_data)
                totals['sections'] += 1
                totals['pages'] += sec_data['page_count']
            
            # Recurse into nested section groups
            nested = self._scan_section_groups_recursive(
                sg_url, f"{parent_name}/{sg_name}", totals, depth + 1
            )
            sg_data['section_groups'] = nested
            
            result.append(sg_data)
        
        return result
    
    def _count_pages_in_section_group(self, sg: Dict) -> int:
        """Count total pages in a section group including nested groups."""
        count = sum(s['page_count'] for s in sg.get('sections', []))
        for nested in sg.get('section_groups', []):
            count += self._count_pages_in_section_group(nested)
        return count
    
    # =========================================================================
    # Index File Generation (using index_builder module)
    # =========================================================================
    
    def write_index_files(self, output_path: Path):
        """Write navigable index.md and index.json using index_builder module."""
        if not self.preflight_data:
            return None
        
        try:
            from index_builder import (
                build_index, 
                write_index_files as write_idx, 
                execute_filesystem_ops
            )
            
            # Build the index with hierarchy resolution
            result = build_index(
                output_path,
                self.preflight_data,
                self.user_info,
                self.graph.tenant_id,
                self.preflight_data.get('scope', 'Unknown')
            )
            
            # Store the result for later use in export
            self.index_result = result
            
            # Execute filesystem operations (create folders)
            execute_filesystem_ops(result.filesystem_ops)
            
            # Write the index files
            md_path, json_path = write_idx(output_path, result)
            
            logger.info(f"✓ Wrote {md_path} (navigable with {result.stats['pages']} pages)")
            logger.info(f"✓ Wrote {json_path}")
            
            # Log hierarchy stats
            if result.stats.get('orphans', 0) > 0:
                logger.warning(f"   {result.stats['orphans']} orphaned pages detected")
                self.stats['orphans'] = result.stats['orphans']
            if result.stats.get('parent_pages', 0) > 0:
                logger.info(f"   {result.stats['parent_pages']} parent pages with {result.stats['child_pages']} children")
            
            return result
            
        except ImportError:
            # Fallback to legacy generation if index_builder not available
            logger.warning("index_builder module not found, using legacy index generation")
            return self._write_legacy_index_files(output_path)
    
    def _write_legacy_index_files(self, output_path: Path):
        """Legacy index generation (fallback)."""
        # Write JSON
        json_path = output_path / 'index.json'
        save_json(json_path, self.preflight_data)
        logger.info(f"✓ Wrote {json_path}")
        
        # Write Markdown
        md_path = output_path / 'index.md'
        md_content = self._generate_index_markdown()
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        logger.info(f"✓ Wrote {md_path}")
        return None
    
    def _generate_index_markdown(self) -> str:
        """Generate index.md content."""
        data = self.preflight_data
        lines = [
            "# OneNote Export Index",
            "",
            f"**Generated:** {data.get('scan_timestamp', 'Unknown')}",
            f"**Account:** {data.get('account', {}).get('displayName', 'Unknown')}",
            f"**Email:** {data.get('account', {}).get('mail', 'Unknown')}",
            f"**Tenant:** {data.get('tenant', 'Unknown')}",
            f"**Scope:** {data.get('scope', 'Unknown')}",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Notebooks | {data['totals']['notebooks']} |",
            f"| Section Groups | {data['totals']['section_groups']} |",
            f"| Sections | {data['totals']['sections']} |",
            f"| **Total Pages** | **{data['totals']['pages']}** |",
            ""
        ]
        
        # Errors section
        if data.get('errors'):
            lines.append("## ⚠️ Errors During Scan")
            lines.append("")
            for err in data['errors'][:20]:  # Limit to 20
                lines.append(f"- {err.get('context', 'Unknown')}: {err.get('error', 'Unknown error')}")
            if len(data['errors']) > 20:
                lines.append(f"- ... and {len(data['errors']) - 20} more errors")
            lines.append("")
        
        lines.append("## Notebooks")
        lines.append("")
        
        for nb in data.get('notebooks', []):
            lines.append(f"### 📓 {nb['name']}")
            lines.append(f"- Total Pages: {nb['page_count']}")
            lines.append(f"- Created: {nb.get('createdDateTime', 'Unknown')}")
            lines.append(f"- Modified: {nb.get('lastModifiedDateTime', 'Unknown')}")
            lines.append("")
            
            if nb.get('sections'):
                lines.append("#### Sections")
                lines.append("")
                for sec in nb['sections']:
                    child_info = f" ({sec.get('child_page_count', 0)} child)" if sec.get('child_page_count', 0) > 0 else ""
                    lines.append(f"- 📑 **{sec['name']}**: {sec['page_count']} pages{child_info}")
                lines.append("")
            
            if nb.get('section_groups'):
                lines.append("#### Section Groups")
                lines.append("")
                for sg in nb['section_groups']:
                    self._append_section_group_md(lines, sg, 0)
                lines.append("")
        
        return "\n".join(lines)
    
    def _append_section_group_md(self, lines: List[str], sg: Dict, depth: int):
        """Append section group to markdown lines."""
        indent = "  " * depth
        pages = self._count_pages_in_section_group(sg)
        lines.append(f"{indent}- 📁 **{sg['name']}** ({pages} pages)")
        
        for sec in sg.get('sections', []):
            child_info = f" ({sec.get('child_page_count', 0)} child)" if sec.get('child_page_count', 0) > 0 else ""
            lines.append(f"{indent}  - 📑 {sec['name']}: {sec['page_count']} pages{child_info}")
        
        for nested in sg.get('section_groups', []):
            self._append_section_group_md(lines, nested, depth + 1)
    
    # =========================================================================
    # Export Logic
    # =========================================================================
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem."""
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip('. ')
        return filename[:200] if filename else 'untitled'
    
    def export_all(self, destination_path: str) -> bool:
        """Export based on selection after preflight."""
        self.export_root = Path(destination_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.export_root = self.export_root / f"OneNote_Export_{timestamp}"
        self.export_root.mkdir(parents=True, exist_ok=True)
        
        # Set up file logging
        logger.set_log_file(self.export_root / 'run.log')
        logger.info(f"Export started at {datetime.now().isoformat()}")
        logger.info(f"Export destination: {self.export_root}")
        
        # Run preflight
        self.run_preflight()
        
        # Write index files BEFORE export
        self.write_index_files(self.export_root)
        
        print("\n" + "=" * 70)
        print("📤 STARTING EXPORT")
        print("=" * 70)
        
        notebooks = self.preflight_data.get('notebooks', [])
        total_notebooks = len(notebooks)
        
        for nb_idx, nb_data in enumerate(notebooks, 1):
            self._export_notebook(nb_data, nb_idx, total_notebooks)
        
        # Validate index links AFTER export completes
        self._validate_index_links()
        
        # Save summary
        self._save_export_summary()
        
        return True
    
    def _validate_index_links(self):
        """Validate that index.md links point to files that exist after export."""
        if not self.index_result:
            return
        
        try:
            from index_builder import validate_index_links
            
            print("\n" + "=" * 70)
            print("🔍 VALIDATING INDEX LINKS")
            print("=" * 70)
            
            missing_links = validate_index_links(self.export_root, self.index_result)
            
            if missing_links:
                logger.warning(f"⚠️ {len(missing_links)} link targets missing after export:")
                for link in missing_links[:10]:
                    logger.warning(f"   Missing: {link.get('relative_target')} ({link.get('context')})")
                if len(missing_links) > 10:
                    logger.warning(f"   ... and {len(missing_links) - 10} more")
            else:
                logger.info("✓ All index links verified - files exist on disk")
                
        except ImportError:
            pass  # index_builder not available
    
    def _export_notebook(self, nb_data: Dict, nb_idx: int, total: int):
        """Export a notebook with progress output."""
        nb_name = self.sanitize_filename(nb_data['name'])
        nb_folder = self.export_root / nb_name
        nb_folder.mkdir(exist_ok=True)
        
        logger.info(f"\n[{nb_idx}/{total}] 📓 {nb_data['name']} ({nb_data['page_count']} pages)")
        self.stats['notebooks'] += 1
        
        # Export direct sections
        for section in nb_data.get('sections', []):
            self._export_section(section, nb_folder, nb_data['name'])
        
        # Export section groups
        for sg in nb_data.get('section_groups', []):
            self._export_section_group(sg, nb_folder, nb_data['name'])
    
    def _export_section_group(self, sg_data: Dict, parent_folder: Path, parent_path: str):
        """Export a section group."""
        sg_name = self.sanitize_filename(sg_data['name'])
        sg_folder = parent_folder / sg_name
        sg_folder.mkdir(exist_ok=True)
        
        full_path = f"{parent_path}/{sg_data['name']}"
        logger.info(f"   📁 {sg_data['name']}")
        self.stats['section_groups'] += 1
        
        for section in sg_data.get('sections', []):
            self._export_section(section, sg_folder, full_path)
        
        for nested in sg_data.get('section_groups', []):
            self._export_section_group(nested, sg_folder, full_path)
    
    def _export_section(self, section_data: Dict, parent_folder: Path, parent_path: str):
        """Export a section with hierarchy support."""
        sec_name = self.sanitize_filename(section_data['name'])
        sec_folder = parent_folder / sec_name
        sec_folder.mkdir(exist_ok=True)
        
        pages = section_data.get('pages', [])
        total_pages = len(pages)
        child_count = section_data.get('child_page_count', 0)
        
        child_info = f" ({child_count} child)" if child_count > 0 else ""
        logger.info(f"      📑 {section_data['name']} ({total_pages} pages{child_info})")
        self.stats['sections'] += 1
        
        # Build page hierarchy map
        page_hierarchy = self._build_page_hierarchy(pages)
        
        for page_idx, page_info in enumerate(pages, 1):
            self._export_page(page_info, sec_folder, page_idx, total_pages, 
                            section_data['name'], page_hierarchy)
    
    def _build_page_hierarchy(self, pages: List[Dict]) -> Dict[str, List[Dict]]:
        """Build parent->children map based on page levels."""
        # Sort by order to maintain sequence
        sorted_pages = sorted(pages, key=lambda p: p.get('order', 0))
        
        hierarchy = {}
        parent_stack = []  # Stack of (page_id, level)
        
        for page in sorted_pages:
            level = page.get('level', 0)
            page_id = page['id']
            
            # Pop stack until we find appropriate parent
            while parent_stack and parent_stack[-1][1] >= level:
                parent_stack.pop()
            
            # If we have a parent, record the relationship
            if parent_stack and level > 0:
                parent_id = parent_stack[-1][0]
                if parent_id not in hierarchy:
                    hierarchy[parent_id] = []
                hierarchy[parent_id].append(page)
            
            # Push current page as potential parent
            parent_stack.append((page_id, level))
        
        return hierarchy
    
    def _export_page(self, page_info: Dict, section_folder: Path, idx: int, 
                    total: int, section_name: str, hierarchy: Dict):
        """Export a single page with hierarchy support."""
        page_title = page_info.get('title', 'Untitled')
        page_id = page_info['id']
        level = page_info.get('level', 0)
        
        # Progress output
        level_indicator = "  " * level if level > 0 else ""
        child_count = len(hierarchy.get(page_id, []))
        child_info = f" (+{child_count} children)" if child_count > 0 else ""
        
        sys.stdout.write(f"\r         [{idx}/{total}] {level_indicator}{page_title[:35]:<35}{child_info}")
        sys.stdout.flush()
        
        try:
            # Determine folder based on hierarchy
            if level > 0:
                self.stats['child_pages'] += 1
            
            # Create page folder for pages with children
            safe_title = self.sanitize_filename(page_title)
            if hierarchy.get(page_id):
                page_folder = section_folder / safe_title
                page_folder.mkdir(exist_ok=True)
                html_path = page_folder / f"{safe_title}.html"
            else:
                page_folder = section_folder
                html_path = section_folder / f"{safe_title}.html"
            
            # Get page content
            response = self.graph.make_request(
                f"{GRAPH_BASE}/me/onenote/pages/{page_id}/content",
                f"{section_name}/{page_title}",
                timeout=120
            )
            
            if not response or response.status_code != 200:
                error_msg = f"Failed to get content (status: {response.status_code if response else 'None'})"
                self.export_errors.append({
                    'type': 'page_content',
                    'page': page_title,
                    'section': section_name,
                    'error': error_msg
                })
                self.stats['errors'] += 1
                logger.debug(f"Error exporting page {page_title}: {error_msg}")
                return
            
            content = response.text
            
            # Extract attachments and get updated content with local image paths
            attachments, updated_content = self._extract_attachments(content, html_path)
            
            # Save HTML with local image paths
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            
            # Export to format
            metadata = {
                'created': page_info.get('createdDateTime', ''),
                'modified': page_info.get('lastModifiedDateTime', ''),
                'level': level,
                'title': page_title
            }
            
            if self.export_format in ('joplin', 'both'):
                self._export_joplin(page_folder, page_title, updated_content, metadata, attachments)
            
            if self.export_format in ('enex', 'both'):
                self._export_enex(page_folder, page_title, updated_content, attachments, metadata)
            
            self.stats['pages'] += 1
            
        except Exception as e:
            self.export_errors.append({
                'type': 'exception',
                'page': page_title,
                'section': section_name,
                'error': str(e)
            })
            self.stats['errors'] += 1
            logger.debug(f"Exception exporting {page_title}: {e}")
        
        # Clear progress line at end
        if idx == total:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()
    
    def _extract_attachments(self, html_content: str, page_path: Path) -> Tuple[List[str], str]:
        """
        Extract and download attachments, returning updated HTML with local paths.
        
        Returns:
            Tuple of (list of attachment filenames, updated HTML content)
        """
        attachments = []
        attachments_dir = page_path.parent / f"{page_path.stem}_attachments"
        updated_html = html_content
        
        # Find all images
        img_pattern = r'<img[^>]*src="([^"]+)"[^>]*>'
        img_count = 0
        
        for match in re.finditer(img_pattern, html_content):
            full_tag = match.group(0)
            src = match.group(1)
            img_count += 1
            
            filename = None
            
            if src.startswith('data:'):
                # Base64 encoded image
                if not attachments_dir.exists():
                    attachments_dir.mkdir()
                
                # Determine extension from mime type
                mime_match = re.match(r'data:image/(\w+)', src)
                ext = mime_match.group(1) if mime_match else 'png'
                filename = f"image_{img_count}.{ext}"
                
                if self._save_base64(src, attachments_dir / filename):
                    attachments.append(filename)
                    self.stats['images'] += 1
                    
            elif src.startswith('http'):
                # Remote URL (Graph API or external)
                if not attachments_dir.exists():
                    attachments_dir.mkdir()
                
                # Get extension from URL or data-src-type attribute
                ext = self._get_ext_from_url(src)
                if not ext:
                    # Try to get from data-src-type attribute
                    type_match = re.search(r'data-src-type="image/(\w+)"', full_tag)
                    ext = type_match.group(1) if type_match else 'png'
                
                filename = f"image_{img_count}.{ext}"
                
                if self._download_file(src, attachments_dir / filename):
                    attachments.append(filename)
                    self.stats['images'] += 1
                else:
                    logger.debug(f"Failed to download image: {src[:100]}...")
                    filename = None  # Keep original URL if download fails
            
            # Update HTML with local path
            if filename:
                local_path = f"{page_path.stem}_attachments/{filename}"
                new_tag = re.sub(r'src="[^"]+"', f'src="{local_path}"', full_tag)
                updated_html = updated_html.replace(full_tag, new_tag)
        
        return attachments, updated_html
    
    def _save_base64(self, data_url: str, filepath: Path) -> bool:
        """Save base64 data. Returns True on success."""
        try:
            match = re.match(r'data:([^;]+);base64,(.+)', data_url)
            if match:
                data = base64.b64decode(match.group(2))
                with open(filepath, 'wb') as f:
                    f.write(data)
                return True
        except Exception as e:
            logger.debug(f"Base64 save error: {e}")
        return False
    
    def _download_file(self, url: str, filepath: Path) -> bool:
        """Download file."""
        response = self.graph.make_request(url, "download attachment", timeout=120)
        if response and response.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return True
        return False
    
    def _get_ext_from_url(self, url: str) -> Optional[str]:
        """Get extension from URL."""
        path = urlparse(url).path
        ext = Path(path).suffix
        return ext.lstrip('.') if ext else None
    
    def _html_to_markdown(self, html_content: str, page_name: str = "") -> str:
        """
        Convert HTML to Markdown with proper image handling.
        
        Args:
            html_content: The HTML content to convert
            page_name: The page name (used for attachment folder reference)
        """
        md = html_content
        
        # Convert images FIRST (before stripping other tags)
        # Match: <img src="..." /> or <img src="...">
        # Extract alt text if present: alt="description"
        def replace_img(match):
            full_tag = match.group(0)
            src_match = re.search(r'src="([^"]+)"', full_tag)
            alt_match = re.search(r'alt="([^"]*)"', full_tag)
            
            if src_match:
                src = src_match.group(1)
                alt = alt_match.group(1) if alt_match else "image"
                return f'![{alt}]({src})'
            return ''
        
        md = re.sub(r'<img[^>]*/?>', replace_img, md, flags=re.IGNORECASE)
        
        # Convert headers
        md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', md, flags=re.DOTALL)
        md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', md, flags=re.DOTALL)
        md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', md, flags=re.DOTALL)
        md = re.sub(r'<h4[^>]*>(.*?)</h4>', r'#### \1\n', md, flags=re.DOTALL)
        
        # Convert text formatting
        md = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', md, flags=re.DOTALL)
        md = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', md, flags=re.DOTALL)
        md = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', md, flags=re.DOTALL)
        md = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', md, flags=re.DOTALL)
        md = re.sub(r'<u[^>]*>(.*?)</u>', r'<u>\1</u>', md, flags=re.DOTALL)
        md = re.sub(r'<s[^>]*>(.*?)</s>', r'~~\1~~', md, flags=re.DOTALL)
        md = re.sub(r'<strike[^>]*>(.*?)</strike>', r'~~\1~~', md, flags=re.DOTALL)
        
        # Convert links
        md = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.DOTALL)
        
        # Convert lists
        md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', md, flags=re.DOTALL)
        md = re.sub(r'<[ou]l[^>]*>', '', md)
        md = re.sub(r'</[ou]l>', '\n', md)
        
        # Convert line breaks and paragraphs
        md = re.sub(r'<br\s*/?>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', md, flags=re.DOTALL)
        md = re.sub(r'<div[^>]*>(.*?)</div>', r'\1\n', md, flags=re.DOTALL)
        
        # Convert code/pre blocks
        md = re.sub(r'<pre[^>]*>(.*?)</pre>', r'```\n\1\n```\n', md, flags=re.DOTALL)
        md = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', md, flags=re.DOTALL)
        
        # Convert blockquotes
        md = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1\n', md, flags=re.DOTALL)
        
        # Convert horizontal rules
        md = re.sub(r'<hr[^>]*/?>', '\n---\n', md, flags=re.IGNORECASE)
        
        # Strip remaining HTML tags (must be last)
        md = re.sub(r'<[^>]+>', '', md)
        
        # Clean up whitespace
        md = re.sub(r'\n\s*\n\s*\n', '\n\n', md)
        md = re.sub(r'[ \t]+\n', '\n', md)  # Trailing whitespace
        
        return html.unescape(md).strip()
    
    def _export_joplin(self, folder: Path, title: str, content: str, 
                       metadata: Dict, attachments: List[str] = None):
        """
        Export as Joplin/Obsidian compatible Markdown with YAML front matter.
        
        Creates a .md file with:
        - YAML front matter (title, created, modified dates)
        - Properly converted markdown content
        - Relative image paths that work in note apps
        """
        attachments = attachments or []
        safe_title = self.sanitize_filename(title)
        
        # Put markdown files alongside HTML (not in subfolder)
        # This makes it easier for note apps to import
        filepath = folder / f"{safe_title}.md"
        
        md_content = self._html_to_markdown(content, safe_title)
        
        # Format dates for YAML (ISO 8601 format works best)
        created = metadata.get('created', '')
        modified = metadata.get('modified', '')
        
        # Escape quotes in title for YAML
        escaped_title = title.replace('"', '\\"')
        
        # Build YAML front matter (compatible with Obsidian, Joplin, etc.)
        front_matter = f"""---
title: "{escaped_title}"
created: {created}
modified: {modified}
tags: [onenote-export]
---

"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(front_matter)
            f.write(md_content)
    
    def _export_enex(self, folder: Path, title: str, content: str, 
                    attachments: List, metadata: Dict):
        """Export as Evernote ENEX."""
        enex_dir = folder / 'evernote' if folder.name != self.sanitize_filename(title) else folder
        enex_dir.mkdir(exist_ok=True)
        
        filepath = enex_dir / f"{self.sanitize_filename(title)}.enex"
        escaped_content = html.escape(content)
        
        enex = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export3.dtd">
<en-export export-date="{datetime.now().strftime('%Y%m%dT%H%M%SZ')}" application="OneNote Exporter" version="{VERSION}">
  <note>
    <title>{html.escape(title)}</title>
    <content><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<en-note>{escaped_content}</en-note>]]></content>
    <created>{metadata['created']}</created>
    <updated>{metadata['modified']}</updated>
  </note>
</en-export>"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(enex)
    
    def _save_export_summary(self):
        """Save export_summary.json."""
        preflight = self.preflight_data.get('totals', {})
        
        summary = {
            'version': VERSION,
            'timestamp': datetime.now().isoformat(),
            'account': self.user_info,
            'tenant': self.graph.tenant_id,
            'scope': self.preflight_data.get('scope', 'Unknown'),
            'preflight_totals': preflight,
            'export_stats': self.stats,
            'export_path': str(self.export_root),
            'api_requests': self.graph.request_count,
            'api_errors': self.graph.error_count,
            'skipped_items': self.skipped_items,
            'export_errors': self.export_errors[:100]  # Limit size
        }
        
        save_json(self.export_root / 'export_summary.json', summary)
    
    def print_final_summary(self, no_pause: bool = False):
        """Print final summary and wait."""
        preflight = self.preflight_data.get('totals', {})
        
        print("\n" + "=" * 70)
        print("📊 EXPORT COMPLETE - FINAL SUMMARY")
        print("=" * 70)
        print(f"\n{'Metric':<25} {'Preflight':<15} {'Exported':<15}")
        print("-" * 55)
        print(f"{'Notebooks':<25} {preflight.get('notebooks', 0):<15} {self.stats['notebooks']:<15}")
        print(f"{'Section Groups':<25} {preflight.get('section_groups', 0):<15} {self.stats['section_groups']:<15}")
        print(f"{'Sections':<25} {preflight.get('sections', 0):<15} {self.stats['sections']:<15}")
        print(f"{'Pages':<25} {preflight.get('pages', 0):<15} {self.stats['pages']:<15}")
        print(f"{'  (Child Pages)':<25} {'-':<15} {self.stats['child_pages']:<15}")
        print("-" * 55)
        print(f"{'Images':<25} {'-':<15} {self.stats['images']:<15}")
        print(f"{'Errors':<25} {'-':<15} {self.stats['errors']:<15}")
        print(f"{'API Requests':<25} {'-':<15} {self.graph.request_count:<15}")
        
        # Match check
        pages_match = preflight.get('pages', 0) == self.stats['pages']
        if pages_match:
            print(f"\n✅ Export totals match preflight scan!")
        else:
            diff = preflight.get('pages', 0) - self.stats['pages']
            print(f"\n⚠️  Page count mismatch: expected {preflight.get('pages', 0)}, got {self.stats['pages']} (diff: {diff})")
        
        print(f"\n📂 Export location: {self.export_root}")
        print(f"📄 Files: index.md, index.json, export_summary.json, run.log")
        
        if self.export_errors:
            print(f"❌ {len(self.export_errors)} export errors - see export_summary.json")
        
        print("=" * 70)
        
        if not no_pause:
            input("\nPress Enter to exit...")


# ============================================================================
# Main Entry Point
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description=f'OneNote Export Tool v{VERSION}')
    parser.add_argument('--preflight-only', action='store_true',
                        help='Only run preflight scan, no export')
    parser.add_argument('--no-pause', action='store_true',
                        help='Exit immediately (no Press Enter prompt)')
    parser.add_argument('--settings', type=str, default='settings.json',
                        help='Settings file path')
    parser.add_argument('--output', type=str,
                        help='Output directory (overrides settings.json)')
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"OneNote Export Tool v{VERSION}")
    print("Interactive selection • Robust retry • Page hierarchy • File logging")
    print("=" * 70)
    
    # Load settings - check exe directory first (for distributed exe), then script dir, then parent
    if args.settings != 'settings.json':
        # User specified a custom path
        settings_path = Path(args.settings)
    else:
        # Use automatic detection
        settings_path = get_settings_path()
    
    settings = load_settings(settings_path)
    
    if settings:
        logger.info(f"✓ Loaded settings from {settings_path}")
    else:
        logger.info(f"ℹ️ No settings file found - will prompt for configuration")
    
    # Pass settings_path so exporter can save new settings if needed
    exporter = OneNoteExporter(settings, settings_path=settings_path)
    
    # Command-line output overrides settings
    if args.output:
        exporter.output_root = args.output
    
    # Authenticate (this will prompt for missing settings and offer to save)
    if not exporter.authenticate():
        logger.error("Authentication failed")
        if not args.no_pause:
            input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Interactive selection
    if not exporter.select_export_scope():
        logger.error("Selection failed")
        if not args.no_pause:
            input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Output path - should already be set from settings or authenticate()
    output_path = exporter.output_root
    
    # Preflight only
    if args.preflight_only:
        output_dir = Path(output_path) / f"OneNote_Preflight_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.set_log_file(output_dir / 'run.log')
        
        exporter.run_preflight()
        exporter.write_index_files(output_dir)
        
        logger.info(f"\n✅ Preflight complete!")
        logger.info(f"📂 Files: {output_dir}")
        
        if not args.no_pause:
            input("\nPress Enter to exit...")
        return
    
    # Format selection
    if not exporter.export_format:
        print("\n📝 Export format:")
        print("1. Joplin (Markdown)")
        print("2. Evernote (ENEX)")
        print("3. Both")
        print("4. Raw HTML only")
        choice = input("Enter choice [1]: ").strip() or '1'
        exporter.export_format = {'1': 'joplin', '2': 'enex', '3': 'both', '4': 'raw_html'}.get(choice, 'joplin')
    
    logger.info(f"\n🚀 Starting export (format: {exporter.export_format})...")
    exporter.export_all(output_path)
    exporter.print_final_summary(args.no_pause)


if __name__ == "__main__":
    main()
