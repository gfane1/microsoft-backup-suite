"""
Microsoft Graph API Client for OneNote Web Exporter
Handles OAuth 2.0 authentication and API requests with robust retry logic.
"""

import os
import sys
import json
import time
import random
import logging
import threading
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================================
# Constants
# ============================================================================
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_MAX_RETRIES = 10
DEFAULT_TIMEOUT = 60

logger = logging.getLogger(__name__)


# ============================================================================
# Settings Management
# ============================================================================

# List of possible settings.json locations to check (in priority order)
def _get_settings_search_paths() -> List[Path]:
    """Get list of paths to search for settings.json."""
    paths = []
    
    # If running as frozen exe
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        paths.append(exe_dir / 'settings.json')
    
    # Script directory (onenote-web-exporter/)
    script_dir = Path(__file__).parent
    paths.append(script_dir / 'settings.json')
    
    # Parent directory (microsoft-backup-suite/)
    paths.append(script_dir.parent / 'settings.json')
    
    # CLI exporter directory (onenote-exporter/)
    paths.append(script_dir.parent / 'onenote-exporter' / 'settings.json')
    
    # Dist directory (for built executables)
    paths.append(script_dir.parent / 'dist' / 'settings.json')
    
    return paths


def get_settings_path() -> Path:
    """Get settings.json path - checks multiple locations.
    
    Returns the first existing settings.json found, or the default
    location in the script directory if none exists.
    """
    for path in _get_settings_search_paths():
        if path.exists():
            logger.info(f"Found settings at: {path}")
            return path
    
    # Default to script directory for new settings
    script_dir = Path(__file__).parent
    return script_dir / 'settings.json'


def load_settings(settings_path: Path = None) -> Dict[str, Any]:
    """Load settings from JSON file.
    
    Searches multiple locations for settings.json and loads the first found.
    Supports both flat format (CLI exporter style) and nested format.
    """
    if settings_path is None:
        settings_path = get_settings_path()
    
    if not settings_path.exists():
        logger.info("No settings.json found - will use defaults")
        return {}
    
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            raw_settings = json.load(f)
        
        logger.info(f"Loaded settings from: {settings_path}")
        
        # Support flat format (CLI exporter style)
        if 'application_client_id' in raw_settings:
            return {
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
        return raw_settings
    except Exception as e:
        logger.warning(f"Could not load settings.json: {e}")
        return {}


def save_settings(settings_path: Path, client_id: str, client_secret: str,
                  export_folder: str, tenant: str = 'consumers'):
    """Save settings to JSON file.
    
    Uses flat format compatible with CLI exporter.
    """
    settings = {
        "application_client_id": client_id,
        "client_secret_value": client_secret,
        "export_folder": export_folder,
        "tenant": tenant
    }
    
    # Ensure directory exists
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4)
    
    logger.info(f"Settings saved to: {settings_path}")


# ============================================================================
# Graph API Client
# ============================================================================
class GraphClient:
    """Microsoft Graph API client with robust retry logic."""
    
    def __init__(self, max_retries: int = DEFAULT_MAX_RETRIES):
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.tenant_id: str = 'consumers'
        self.max_retries = max_retries
        self.request_count = 0
        self.error_count = 0
        self._lock = threading.Lock()
    
    @property
    def is_authenticated(self) -> bool:
        """Check if client has valid authentication."""
        return self.access_token is not None
    
    @property
    def token_needs_refresh(self) -> bool:
        """Check if token is expired or expiring soon."""
        if not self.token_expiry:
            return True
        # Refresh if less than 5 minutes remaining
        return datetime.now() > self.token_expiry - timedelta(minutes=5)
    
    def configure(self, client_id: str, client_secret: str, tenant: str = 'consumers'):
        """Configure OAuth credentials."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant
    
    def get_auth_url(self, redirect_uri: str = "http://localhost:8080") -> str:
        """Generate OAuth authorization URL."""
        scope = "Notes.Read Notes.Read.All User.Read offline_access"
        return (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
            f"?client_id={self.client_id}"
            f"&response_type=code"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
        )
    
    def exchange_code_for_token(self, code: str, 
                                 redirect_uri: str = "http://localhost:8080") -> bool:
        """Exchange authorization code for access token."""
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=30)
            result = response.json()
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.refresh_token = result.get('refresh_token')
                expires_in = result.get('expires_in', 3600)
                self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                logger.info("Successfully authenticated with Microsoft Graph")
                return True
            else:
                logger.error(f"Auth failed: {result.get('error_description', 'Unknown')}")
                return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    def refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token."""
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
                if 'refresh_token' in result:
                    self.refresh_token = result['refresh_token']
                expires_in = result.get('expires_in', 3600)
                self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                logger.info("Token refreshed successfully")
                return True
            else:
                logger.error(f"Token refresh failed: {result.get('error_description')}")
                return False
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False
    
    def make_request(self, url: str, method: str = 'GET', 
                     context: str = "", **kwargs) -> Optional[requests.Response]:
        """Make API request with retry logic."""
        if not url.startswith('http'):
            url = f"{GRAPH_BASE}{url}"
        
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {self.access_token}'
        
        with self._lock:
            self.request_count += 1
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Check if token needs refresh
                if self.token_needs_refresh and self.refresh_token:
                    self.refresh_access_token()
                    headers['Authorization'] = f'Bearer {self.access_token}'
                
                response = requests.request(
                    method, url, headers=headers, 
                    timeout=DEFAULT_TIMEOUT, **kwargs
                )
                
                if response.status_code == 200:
                    return response
                
                if response.status_code == 401:
                    # Token expired, try refresh
                    if self.refresh_access_token():
                        headers['Authorization'] = f'Bearer {self.access_token}'
                        continue
                    else:
                        with self._lock:
                            self.error_count += 1
                        return None
                
                if response.status_code == 429:
                    # Rate limited
                    retry_after = int(response.headers.get('Retry-After', 30))
                    logger.warning(f"Rate limited, waiting {retry_after}s [{context}]")
                    time.sleep(retry_after)
                    continue
                
                if response.status_code >= 500:
                    # Server error - exponential backoff
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 60)
                    logger.warning(f"Server error {response.status_code}, retry {attempt}/{self.max_retries} [{context}]")
                    time.sleep(wait_time)
                    continue
                
                # Other error
                logger.error(f"Request failed: {response.status_code} [{context}]")
                with self._lock:
                    self.error_count += 1
                return response
                
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout, retry {attempt}/{self.max_retries} [{context}]")
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Request error: {e} [{context}]")
                with self._lock:
                    self.error_count += 1
                return None
        
        logger.error(f"Max retries exceeded [{context}]")
        with self._lock:
            self.error_count += 1
        return None
    
    def get_all_pages(self, url: str, context: str = "") -> Tuple[List[Dict], List[Dict]]:
        """Fetch all pages following @odata.nextLink pagination."""
        all_items = []
        errors = []
        page_num = 1
        
        while url:
            page_context = f"{context} [page {page_num}]"
            response = self.make_request(url, context=page_context)
            
            if not response:
                errors.append({
                    'url': url,
                    'context': page_context,
                    'page': page_num,
                    'error': 'Request failed'
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
            
            next_link = data.get('@odata.nextLink')
            if next_link:
                logger.debug(f"Following nextLink: page {page_num} -> {page_num + 1}")
                url = next_link
                page_num += 1
                time.sleep(0.1)
            else:
                url = None
        
        return all_items, errors
    
    # ========================================================================
    # OneNote API Methods
    # ========================================================================
    
    def get_user_info(self) -> Optional[Dict]:
        """Get signed-in user information."""
        response = self.make_request('/me', context='get user info')
        if response and response.status_code == 200:
            return response.json()
        return None
    
    def get_notebooks(self) -> Tuple[List[Dict], List[Dict]]:
        """Get all notebooks."""
        return self.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/notebooks?$select=id,displayName,createdDateTime,lastModifiedDateTime",
            context='list notebooks'
        )
    
    def get_sections(self, notebook_id: str) -> Tuple[List[Dict], List[Dict]]:
        """Get all sections in a notebook."""
        return self.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/notebooks/{notebook_id}/sections?$select=id,displayName,createdDateTime,lastModifiedDateTime",
            context=f'list sections for notebook {notebook_id}'
        )
    
    def get_section_groups(self, notebook_id: str) -> Tuple[List[Dict], List[Dict]]:
        """Get section groups in a notebook."""
        return self.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/notebooks/{notebook_id}/sectionGroups?$select=id,displayName",
            context=f'list section groups for notebook {notebook_id}'
        )
    
    def get_sections_in_group(self, group_id: str) -> Tuple[List[Dict], List[Dict]]:
        """Get sections in a section group."""
        return self.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/sectionGroups/{group_id}/sections?$select=id,displayName,createdDateTime,lastModifiedDateTime",
            context=f'list sections in group {group_id}'
        )
    
    def get_nested_section_groups(self, group_id: str) -> Tuple[List[Dict], List[Dict]]:
        """Get nested section groups."""
        return self.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/sectionGroups/{group_id}/sectionGroups?$select=id,displayName",
            context=f'list nested groups in {group_id}'
        )
    
    def get_pages(self, section_id: str) -> Tuple[List[Dict], List[Dict]]:
        """Get all pages in a section with hierarchy info."""
        return self.get_all_pages(
            f"{GRAPH_BASE}/me/onenote/sections/{section_id}/pages?$select=id,title,createdDateTime,lastModifiedDateTime,level,order,contentUrl",
            context=f'list pages for section {section_id}'
        )
    
    def get_page_content(self, page_id: str) -> Optional[str]:
        """Get HTML content of a page."""
        response = self.make_request(
            f"{GRAPH_BASE}/me/onenote/pages/{page_id}/content",
            context=f'get content for page {page_id}'
        )
        if response and response.status_code == 200:
            return response.text
        return None
    
    def download_resource(self, url: str) -> Optional[bytes]:
        """Download a resource (image, attachment)."""
        response = self.make_request(url, context='download resource')
        if response and response.status_code == 200:
            return response.content
        return None


# ============================================================================
# Notebook Cache Manager
# ============================================================================

class NotebookCacheManager:
    """Manages persistent caching of notebook structure to settings.json.
    
    Stores notebooks, sections, and pages with timestamps for:
    - Fast startup (no API calls needed if cache exists)
    - Progress tracking for crash recovery
    - Export history with timestamps
    """
    
    def __init__(self):
        self.cache_file = self._get_cache_path()
        self._cache = self._load_cache()
    
    def _get_cache_path(self) -> Path:
        """Get path to cache file (separate from settings for clarity)."""
        script_dir = Path(__file__).parent
        return script_dir / 'notebook_cache.json'
    
    def _load_cache(self) -> Dict[str, Any]:
        """Load cache from file."""
        if not self.cache_file.exists():
            return self._empty_cache()
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            logger.info(f"Loaded notebook cache from: {self.cache_file}")
            return cache
        except Exception as e:
            logger.warning(f"Could not load cache: {e}")
            return self._empty_cache()
    
    def _empty_cache(self) -> Dict[str, Any]:
        """Return empty cache structure."""
        return {
            'version': 1,
            'user_id': None,
            'user_email': None,
            'last_full_refresh': None,
            'notebooks': {},
            'sections': {},
            'pages': {},
            'export_history': [],
            'export_progress': None
        }
    
    def _save_cache(self):
        """Save cache to file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, default=str)
            logger.debug("Cache saved")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    def set_user(self, user_id: str, user_email: str):
        """Set current user - clears cache if different user."""
        if self._cache.get('user_id') != user_id:
            logger.info(f"New user detected, clearing cache")
            self._cache = self._empty_cache()
            self._cache['user_id'] = user_id
            self._cache['user_email'] = user_email
            self._save_cache()
        elif self._cache.get('user_email') != user_email:
            self._cache['user_email'] = user_email
            self._save_cache()
    
    def get_cached_notebooks(self) -> Optional[List[Dict]]:
        """Get cached notebooks list."""
        notebooks = self._cache.get('notebooks', {})
        if not notebooks:
            return None
        return list(notebooks.values())
    
    def cache_notebooks(self, notebooks: List[Dict]):
        """Cache notebooks from API response."""
        self._cache['notebooks'] = {}
        for nb in notebooks:
            self._cache['notebooks'][nb['id']] = {
                'id': nb.get('id'),
                'name': nb.get('displayName'),
                'created': nb.get('createdDateTime'),
                'modified': nb.get('lastModifiedDateTime'),
                'cached_at': datetime.now().isoformat(),
                'section_count': None,
                'page_count': None
            }
        self._cache['last_full_refresh'] = datetime.now().isoformat()
        self._save_cache()
    
    def get_cached_sections(self, notebook_id: str) -> Optional[List[Dict]]:
        """Get cached sections for a notebook."""
        nb_sections = self._cache.get('sections', {}).get(notebook_id)
        if not nb_sections:
            return None
        return list(nb_sections.values())
    
    def cache_sections(self, notebook_id: str, sections: List[Dict]):
        """Cache sections for a notebook."""
        if 'sections' not in self._cache:
            self._cache['sections'] = {}
        
        self._cache['sections'][notebook_id] = {}
        for sec in sections:
            self._cache['sections'][notebook_id][sec['id']] = {
                'id': sec.get('id'),
                'name': sec.get('displayName'),
                'created': sec.get('createdDateTime'),
                'modified': sec.get('lastModifiedDateTime'),
                'notebook_id': notebook_id,
                'cached_at': datetime.now().isoformat(),
                'page_count': None
            }
        
        # Update notebook section count
        if notebook_id in self._cache.get('notebooks', {}):
            self._cache['notebooks'][notebook_id]['section_count'] = len(sections)
            self._cache['notebooks'][notebook_id]['sections_cached_at'] = datetime.now().isoformat()
        
        self._save_cache()
    
    def get_cached_pages(self, section_id: str) -> Optional[List[Dict]]:
        """Get cached pages for a section."""
        sec_pages = self._cache.get('pages', {}).get(section_id)
        if not sec_pages:
            return None
        return list(sec_pages.values())
    
    def cache_pages(self, section_id: str, pages: List[Dict], notebook_id: str = None):
        """Cache pages for a section."""
        if 'pages' not in self._cache:
            self._cache['pages'] = {}
        
        self._cache['pages'][section_id] = {}
        for pg in pages:
            self._cache['pages'][section_id][pg['id']] = {
                'id': pg.get('id'),
                'title': pg.get('title', 'Untitled'),
                'created': pg.get('createdDateTime'),
                'modified': pg.get('lastModifiedDateTime'),
                'level': pg.get('level', 0),
                'order': pg.get('order', 0),
                'section_id': section_id,
                'cached_at': datetime.now().isoformat(),
                'exported_at': None,
                'export_path': None
            }
        
        # Update section page count
        for nb_id, nb_sections in self._cache.get('sections', {}).items():
            if section_id in nb_sections:
                nb_sections[section_id]['page_count'] = len(pages)
                nb_sections[section_id]['pages_cached_at'] = datetime.now().isoformat()
                break
        
        self._save_cache()
    
    def get_section_page_count(self, section_id: str) -> Optional[int]:
        """Get cached page count for a section without loading all pages."""
        for nb_sections in self._cache.get('sections', {}).values():
            if section_id in nb_sections:
                return nb_sections[section_id].get('page_count')
        return None
    
    def mark_page_exported(self, page_id: str, export_path: str):
        """Mark a page as exported with timestamp and path."""
        for sec_pages in self._cache.get('pages', {}).values():
            if page_id in sec_pages:
                sec_pages[page_id]['exported_at'] = datetime.now().isoformat()
                sec_pages[page_id]['export_path'] = export_path
                self._save_cache()
                return
    
    def set_export_progress(self, progress: Dict):
        """Save current export progress for crash recovery."""
        self._cache['export_progress'] = {
            **progress,
            'updated_at': datetime.now().isoformat()
        }
        self._save_cache()
    
    def clear_export_progress(self):
        """Clear export progress after successful completion."""
        self._cache['export_progress'] = None
        self._save_cache()
    
    def get_export_progress(self) -> Optional[Dict]:
        """Get saved export progress for crash recovery."""
        return self._cache.get('export_progress')
    
    def add_export_history(self, export_info: Dict):
        """Add completed export to history."""
        if 'export_history' not in self._cache:
            self._cache['export_history'] = []
        
        export_record = {
            **export_info,
            'completed_at': datetime.now().isoformat()
        }
        self._cache['export_history'].insert(0, export_record)
        
        # Keep only last 50 exports
        self._cache['export_history'] = self._cache['export_history'][:50]
        self._save_cache()
    
    def get_export_history(self) -> List[Dict]:
        """Get export history."""
        return self._cache.get('export_history', [])
    
    def get_exported_pages(self) -> Dict[str, str]:
        """Get map of page IDs to their exported file paths."""
        exported = {}
        # Build map from export history
        for export in self._cache.get('export_history', []):
            page_id = export.get('page_id')
            output_file = export.get('output_file')
            if page_id and output_file:
                exported[page_id] = output_file
        
        # Also check pages cache for exported_at timestamps
        for sec_pages in self._cache.get('pages', {}).values():
            for page_id, page_data in sec_pages.items():
                if page_data.get('exported_at') and page_data.get('export_path'):
                    exported[page_id] = page_data['export_path']
        
        return exported
    
    def remove_exported_page(self, page_id: str):
        """Remove a page from export tracking (file no longer exists)."""
        # Remove from export history
        if 'export_history' in self._cache:
            self._cache['export_history'] = [
                e for e in self._cache['export_history'] 
                if e.get('page_id') != page_id
            ]
        
        # Remove exported_at from page data
        for sec_pages in self._cache.get('pages', {}).values():
            if page_id in sec_pages:
                page_data = sec_pages[page_id]
                if 'exported_at' in page_data:
                    del page_data['exported_at']
                if 'export_path' in page_data:
                    del page_data['export_path']
        
        self._save_cache()
    
    def get_full_cache(self) -> Dict:
        """Get full cache for debugging/display."""
        return self._cache
    
    def clear_cache(self):
        """Clear all cached data."""
        user_id = self._cache.get('user_id')
        user_email = self._cache.get('user_email')
        self._cache = self._empty_cache()
        self._cache['user_id'] = user_id
        self._cache['user_email'] = user_email
        self._save_cache()
    
    def needs_refresh(self, notebook_id: str = None) -> bool:
        """Check if cache needs refresh (older than 1 hour)."""
        if not self._cache.get('last_full_refresh'):
            return True
        
        try:
            last_refresh = datetime.fromisoformat(self._cache['last_full_refresh'])
            age = datetime.now() - last_refresh
            return age.total_seconds() > 3600  # 1 hour
        except:
            return True
