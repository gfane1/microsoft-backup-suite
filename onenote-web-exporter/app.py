"""
OneNote Web Exporter - Flask Application
Local web UI for browsing and exporting OneNote notebooks.
"""

import os
import sys
import json
import logging
import webbrowser
import threading
import re
import base64
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, session
from flask_cors import CORS

from graph_client import GraphClient, NotebookCacheManager, load_settings, save_settings, get_settings_path
from exporter import OneNoteExporter, ExportProgress

# ============================================================================
# App Configuration
# ============================================================================
app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# Global state
graph_client = GraphClient()
cache_manager = NotebookCacheManager()
current_export = None
export_lock = threading.Lock()

# ============================================================================
# Helper Functions
# ============================================================================

def get_redirect_uri():
    """Get OAuth redirect URI based on current server."""
    # Use same redirect URI as CLI exporter (already registered in Azure)
    return "http://localhost:8080"


def init_from_settings():
    """Initialize graph client from settings file."""
    settings = load_settings()
    if settings:
        auth = settings.get('auth', {})
        if auth.get('client_id') and auth.get('client_secret'):
            graph_client.configure(
                auth.get('client_id'),
                auth.get('client_secret'),
                auth.get('tenant', 'consumers')
            )
            return settings.get('export', {}).get('output_root', '')
    return ''


# Initialize on startup
default_export_path = init_from_settings()


# ============================================================================
# Routes - Pages
# ============================================================================

@app.route('/')
def index():
    """Main dashboard page - also handles OAuth callback when redirect_uri is root."""
    # Check if this is an OAuth callback
    code = request.args.get('code')
    error = request.args.get('error')
    
    if code or error:
        # Handle OAuth callback
        if error:
            error_desc = request.args.get('error_description', 'Unknown error')
            return render_template('auth_result.html', 
                                  success=False, 
                                  message=f"Authentication failed: {error_desc}")
        
        if code:
            success = graph_client.exchange_code_for_token(code, get_redirect_uri())
            
            if success:
                user_info = graph_client.get_user_info()
                user_name = user_info.get('displayName', 'Unknown') if user_info else 'Unknown'
                user_email = user_info.get('mail') or user_info.get('userPrincipalName', '') if user_info else ''
                user_id = user_info.get('id', '') if user_info else ''
                
                # Set user in cache manager (clears cache if different user)
                if user_id:
                    cache_manager.set_user(user_id, user_email)
                
                return render_template('auth_result.html',
                                      success=True,
                                      message=f"Successfully signed in as {user_name}",
                                      user_email=user_email)
            else:
                return render_template('auth_result.html',
                                      success=False,
                                      message="Failed to exchange code for token")
    
    # Normal dashboard display
    settings = load_settings()
    has_settings = bool(settings.get('auth', {}).get('client_id'))
    is_authenticated = graph_client.is_authenticated
    export_folder = settings.get('export', {}).get('output_root', str(Path.home() / 'OneNote-Exports'))
    
    return render_template('index.html',
                          has_settings=has_settings,
                          is_authenticated=is_authenticated,
                          export_folder=export_folder)


@app.route('/settings')
def settings_page():
    """Settings configuration page."""
    settings = load_settings()
    return render_template('settings.html', settings=settings)


@app.route('/browse')
def browse_page():
    """Notebook browser page."""
    if not graph_client.is_authenticated:
        return redirect(url_for('index'))
    return render_template('browse.html')


@app.route('/export')
def export_page():
    """Export progress page."""
    return render_template('export.html')


# ============================================================================
# Routes - Authentication
# ============================================================================

@app.route('/auth/login')
def auth_login():
    """Start OAuth flow."""
    if not graph_client.client_id:
        return jsonify({'error': 'No client credentials configured'}), 400
    
    auth_url = graph_client.get_auth_url(get_redirect_uri())
    return redirect(auth_url)


@app.route('/auth/callback')
def auth_callback():
    """OAuth callback handler."""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        error_desc = request.args.get('error_description', 'Unknown error')
        return render_template('auth_result.html', 
                              success=False, 
                              message=f"Authentication failed: {error_desc}")
    
    if not code:
        return render_template('auth_result.html',
                              success=False,
                              message="No authorization code received")
    
    success = graph_client.exchange_code_for_token(code, get_redirect_uri())
    
    if success:
        # Get user info
        user_info = graph_client.get_user_info()
        user_name = user_info.get('displayName', 'Unknown') if user_info else 'Unknown'
        user_email = user_info.get('mail') or user_info.get('userPrincipalName', '') if user_info else ''
        
        return render_template('auth_result.html',
                              success=True,
                              message=f"Successfully signed in as {user_name}",
                              user_email=user_email)
    else:
        return render_template('auth_result.html',
                              success=False,
                              message="Failed to exchange code for token")


@app.route('/auth/status')
def auth_status():
    """Check authentication status."""
    if graph_client.is_authenticated:
        user_info = graph_client.get_user_info()
        return jsonify({
            'authenticated': True,
            'user': user_info
        })
    return jsonify({'authenticated': False})


@app.route('/auth/logout')
def auth_logout():
    """Clear authentication."""
    graph_client.access_token = None
    graph_client.refresh_token = None
    graph_client.token_expiry = None
    return redirect(url_for('index'))


# ============================================================================
# Routes - Settings API
# ============================================================================

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Get current settings (without sensitive data)."""
    settings = load_settings()
    # Mask client secret
    if settings.get('auth', {}).get('client_secret'):
        settings['auth']['client_secret'] = '********'
    return jsonify(settings)


@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    """Save settings."""
    data = request.json
    
    client_id = data.get('client_id', '')
    client_secret = data.get('client_secret', '')
    export_folder = data.get('export_folder', str(Path.home() / 'OneNote-Exports'))
    tenant = data.get('tenant', 'consumers')
    
    if not client_id or not client_secret:
        return jsonify({'error': 'Client ID and secret are required'}), 400
    
    # Save to file
    settings_path = get_settings_path()
    save_settings(settings_path, client_id, client_secret, export_folder, tenant)
    
    # Update graph client
    graph_client.configure(client_id, client_secret, tenant)
    
    return jsonify({'success': True, 'message': 'Settings saved successfully'})


# ============================================================================
# Routes - Notebook API (with caching)
# ============================================================================

@app.route('/api/notebooks')
def api_notebooks():
    """Get list of notebooks - uses cache if available, fetches from API otherwise.
    
    Query params:
        - force_refresh: Skip cache and fetch fresh data
        - use_cache: Only use cache, don't fetch (for fast startup)
    """
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
    use_cache_only = request.args.get('use_cache', 'false').lower() == 'true'
    
    # Try cache first (unless force refresh)
    if not force_refresh:
        cached = cache_manager.get_cached_notebooks()
        if cached:
            logger.info(f"Returning {len(cached)} notebooks from cache")
            return jsonify({
                'notebooks': cached,
                'from_cache': True,
                'cache_age': cache_manager._cache.get('last_full_refresh'),
                'errors': []
            })
    
    # If cache-only mode, return empty
    if use_cache_only:
        return jsonify({'notebooks': [], 'from_cache': True, 'errors': []})
    
    # Fetch from API
    notebooks, errors = graph_client.get_notebooks()
    
    result = []
    for nb in notebooks:
        nb_info = {
            'id': nb.get('id', ''),
            'name': nb.get('displayName', 'Untitled'),
            'created': nb.get('createdDateTime', ''),
            'modified': nb.get('lastModifiedDateTime', ''),
            'section_count': None,  # Will be fetched on-demand
            'page_count': None,     # Will be fetched on-demand
            'cached_at': None
        }
        result.append(nb_info)
    
    # Cache the notebooks (sections/pages fetched on-demand)
    cache_manager.cache_notebooks(notebooks)
    
    return jsonify({
        'notebooks': result,
        'from_cache': False,
        'errors': errors
    })


@app.route('/api/notebooks/<notebook_id>/sections')
def api_sections(notebook_id):
    """Get sections for a notebook - uses cache, fetches pages counts on-demand only."""
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
    
    # Try cache first
    if not force_refresh:
        cached = cache_manager.get_cached_sections(notebook_id)
        if cached:
            logger.info(f"Returning {len(cached)} sections from cache for notebook {notebook_id}")
            return jsonify({
                'sections': cached,
                'from_cache': True,
                'errors': []
            })
    
    # Fetch from API
    sections, errors = graph_client.get_sections(notebook_id)
    
    result = []
    for sec in sections:
        sec_info = {
            'id': sec.get('id', ''),
            'name': sec.get('displayName', 'Untitled'),
            'created': sec.get('createdDateTime', ''),
            'modified': sec.get('lastModifiedDateTime', ''),
            'page_count': None  # Fetched on-demand when section is expanded
        }
        result.append(sec_info)
    
    # Cache sections
    cache_manager.cache_sections(notebook_id, sections)
    
    return jsonify({
        'sections': result,
        'from_cache': False,
        'errors': errors
    })


@app.route('/api/sections/<section_id>/pages')
def api_pages(section_id):
    """Get pages for a section - caches results for future use."""
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'
    
    # Try cache first
    if not force_refresh:
        cached = cache_manager.get_cached_pages(section_id)
        if cached:
            logger.info(f"Returning {len(cached)} pages from cache for section {section_id}")
            return jsonify({
                'pages': cached,
                'from_cache': True,
                'errors': []
            })
    
    # Fetch from API
    pages, errors = graph_client.get_pages(section_id)
    
    result = []
    for pg in pages:
        result.append({
            'id': pg.get('id', ''),
            'title': pg.get('title', 'Untitled'),
            'created': pg.get('createdDateTime', ''),
            'modified': pg.get('lastModifiedDateTime', ''),
            'level': pg.get('level', 0),
            'order': pg.get('order', 0)
        })
    
    # Cache pages
    cache_manager.cache_pages(section_id, pages)
    
    return jsonify({
        'pages': result,
        'from_cache': False,
        'errors': errors
    })


@app.route('/api/pages/<page_id>/content')
def api_page_content(page_id):
    """Get page content as HTML for preview with proxied images."""
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    content = graph_client.get_page_content(page_id)
    if content:
        # Rewrite image URLs to use our proxy endpoint
        import re
        
        def rewrite_image_url(match):
            original_url = match.group(1)
            # Check if it's a Graph API URL that needs auth
            if 'graph.microsoft.com' in original_url or 'onenote.com' in original_url:
                # Encode the URL and proxy it through our endpoint
                import base64
                encoded_url = base64.urlsafe_b64encode(original_url.encode()).decode()
                return f'src="/api/image-proxy/{encoded_url}"'
            return match.group(0)
        
        # Rewrite src attributes for images
        content = re.sub(r'src="([^"]+)"', rewrite_image_url, content)
        
        return jsonify({'content': content})
    return jsonify({'error': 'Failed to get page content'}), 500


@app.route('/api/image-proxy/<encoded_url>')
def api_image_proxy(encoded_url):
    """Proxy images from Graph API with authentication."""
    if not graph_client.is_authenticated:
        return '', 401
    
    try:
        import base64
        url = base64.urlsafe_b64decode(encoded_url.encode()).decode()
        
        # Download the image through the authenticated graph client
        image_data = graph_client.download_resource(url)
        if image_data:
            # Detect content type from URL or default to png
            content_type = 'image/png'
            if '.jpg' in url or '.jpeg' in url:
                content_type = 'image/jpeg'
            elif '.gif' in url:
                content_type = 'image/gif'
            elif '.svg' in url:
                content_type = 'image/svg+xml'
            
            return Response(image_data, mimetype=content_type)
    except Exception as e:
        logger.error(f"Image proxy error: {e}")
    
    return '', 404


@app.route('/api/pages/<page_id>/preview')
def api_page_preview(page_id):
    """Get full page HTML for viewing in new tab."""
    if not graph_client.is_authenticated:
        return redirect(url_for('auth_login'))
    
    content = graph_client.get_page_content(page_id)
    if not content:
        return "Failed to load page content", 500
    
    # Rewrite image URLs to use our proxy endpoint
    import re
    import base64
    
    def rewrite_image_url(match):
        original_url = match.group(1)
        if 'graph.microsoft.com' in original_url or 'onenote.com' in original_url:
            encoded_url = base64.urlsafe_b64encode(original_url.encode()).decode()
            return f'src="/api/image-proxy/{encoded_url}"'
        return match.group(0)
    
    content = re.sub(r'src="([^"]+)"', rewrite_image_url, content)
    
    # Wrap in a proper HTML document with styling
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>OneNote Page Preview</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem;
            line-height: 1.6;
        }}
        img {{
            max-width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>
{content}
</body>
</html>"""
    
    return Response(html, mimetype='text/html')


# ============================================================================
# Routes - Cache API
# ============================================================================

@app.route('/api/cache')
def api_get_cache():
    """Get full cache data for display."""
    return jsonify(cache_manager.get_full_cache())


@app.route('/api/cache/clear', methods=['POST'])
def api_clear_cache():
    """Clear all cached data."""
    cache_manager.clear_cache()
    return jsonify({'success': True, 'message': 'Cache cleared'})


@app.route('/api/cache/export-history')
def api_export_history():
    """Get export history."""
    return jsonify({'history': cache_manager.get_export_history()})


@app.route('/api/cache/exported-pages')
def api_exported_pages():
    """Get map of page IDs to their exported file paths."""
    return jsonify({'exported_pages': cache_manager.get_exported_pages()})


@app.route('/api/cache/validate-exports', methods=['POST'])
def api_validate_exports():
    """Validate that exported files actually exist on filesystem."""
    data = request.json or {}
    exported_pages = data.get('exported_pages', {})
    
    valid_exports = {}
    removed_count = 0
    
    for page_id, file_path in exported_pages.items():
        if file_path and Path(file_path).exists():
            valid_exports[page_id] = file_path
        else:
            removed_count += 1
            # Remove from cache
            cache_manager.remove_exported_page(page_id)
    
    return jsonify({
        'valid_exports': valid_exports,
        'removed_count': removed_count
    })


@app.route('/api/cache/export-progress')
def api_export_progress_saved():
    """Get saved export progress for crash recovery."""
    progress = cache_manager.get_export_progress()
    return jsonify({'progress': progress})


# ============================================================================
# Routes - Folder Management API
# ============================================================================

def sanitize_filename(name):
    """Sanitize a filename for filesystem use."""
    # Replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Remove leading/trailing spaces and dots
    name = name.strip('. ')
    return name if name else 'Untitled'


@app.route('/api/folders/create-notebook-folders', methods=['POST'])
def api_create_notebook_folders():
    """Create folders in export directory for all cached notebooks."""
    settings = load_settings()
    export_root = settings.get('export', {}).get('output_root', '')
    
    if not export_root:
        return jsonify({'error': 'No export folder configured'}), 400
    
    # Get export root and ensure OneNote_Export subfolder exists
    export_path = Path(export_root) / 'OneNote_Export'
    export_path.mkdir(parents=True, exist_ok=True)
    
    # Get cached notebooks
    notebooks = cache_manager.get_cached_notebooks()
    if not notebooks:
        return jsonify({'error': 'No notebooks in cache'}), 400
    
    created_folders = []
    for nb in notebooks:
        nb_name = sanitize_filename(nb.get('displayName', nb.get('name', 'Untitled')))
        nb_folder = export_path / nb_name
        nb_folder.mkdir(exist_ok=True)
        created_folders.append({
            'name': nb_name,
            'path': str(nb_folder),
            'created': not nb_folder.exists() if not nb_folder.exists() else False
        })
        logger.info(f"Ensured notebook folder exists: {nb_folder}")
    
    return jsonify({
        'success': True,
        'export_root': str(export_path),
        'folders': created_folders
    })


@app.route('/api/folders/check-orphans', methods=['GET'])
def api_check_orphan_folders():
    """Check for orphaned folders that don't match notebook/section structure in cache."""
    settings = load_settings()
    export_root = settings.get('export', {}).get('output_root', '')
    
    if not export_root:
        return jsonify({'error': 'No export folder configured'}), 400
    
    export_path = Path(export_root) / 'OneNote_Export'
    
    if not export_path.exists():
        return jsonify({'orphans': [], 'message': 'Export directory does not exist'})
    
    # Get cached notebook names
    notebooks = cache_manager.get_cached_notebooks()
    valid_notebook_names = set()
    notebook_sections = {}  # notebook_name -> set of section names
    
    for nb in notebooks:
        nb_name = sanitize_filename(nb.get('displayName', nb.get('name', 'Untitled')))
        valid_notebook_names.add(nb_name)
        
        # Get sections for this notebook
        sections = cache_manager.get_cached_sections(nb.get('id', ''))
        if sections:
            section_names = set()
            for sec in sections:
                sec_name = sanitize_filename(sec.get('displayName', sec.get('name', 'Untitled')))
                section_names.add(sec_name)
            notebook_sections[nb_name] = section_names
    
    orphans = []
    
    # Check each folder in export directory
    for item in export_path.iterdir():
        if item.is_dir():
            folder_name = item.name
            
            if folder_name not in valid_notebook_names:
                # Orphan notebook folder
                orphans.append({
                    'type': 'notebook',
                    'name': folder_name,
                    'path': str(item),
                    'reason': 'Notebook not found in cache/account'
                })
            else:
                # Check sections within valid notebook
                expected_sections = notebook_sections.get(folder_name, set())
                for section_folder in item.iterdir():
                    if section_folder.is_dir():
                        section_name = section_folder.name
                        if section_name != '_attachments' and section_name not in expected_sections:
                            orphans.append({
                                'type': 'section',
                                'name': section_name,
                                'path': str(section_folder),
                                'parent': folder_name,
                                'reason': 'Section not found in notebook cache'
                            })
    
    return jsonify({
        'orphans': orphans,
        'valid_notebooks': list(valid_notebook_names),
        'export_root': str(export_path)
    })


@app.route('/api/folders/delete-orphan', methods=['POST'])
def api_delete_orphan_folder():
    """Delete an orphaned folder after user confirmation."""
    data = request.json or {}
    folder_path = data.get('path', '')
    
    if not folder_path:
        return jsonify({'error': 'No folder path provided'}), 400
    
    folder = Path(folder_path)
    
    # Safety checks
    settings = load_settings()
    export_root = settings.get('export', {}).get('output_root', '')
    export_path = Path(export_root) / 'OneNote_Export'
    
    # Ensure the folder is within the export directory
    try:
        folder.resolve().relative_to(export_path.resolve())
    except ValueError:
        return jsonify({'error': 'Folder is not within export directory'}), 403
    
    if not folder.exists():
        return jsonify({'error': 'Folder does not exist'}), 404
    
    # Count files that will be deleted
    file_count = sum(1 for _ in folder.rglob('*') if _.is_file())
    
    # Delete the folder
    import shutil
    try:
        shutil.rmtree(folder)
        logger.info(f"Deleted orphan folder: {folder}")
        
        # Also remove any exported page entries that pointed to files in this folder
        exported_pages = cache_manager.get_exported_pages()
        removed_pages = []
        for page_id, file_path in list(exported_pages.items()):
            if file_path and folder_path in file_path:
                cache_manager.remove_exported_page(page_id)
                removed_pages.append(page_id)
        
        return jsonify({
            'success': True,
            'deleted': str(folder),
            'files_deleted': file_count,
            'cache_entries_removed': len(removed_pages)
        })
    except Exception as e:
        logger.error(f"Failed to delete folder {folder}: {e}")
        return jsonify({'error': f'Failed to delete: {str(e)}'}), 500


@app.route('/api/folders/sync-status', methods=['GET'])
def api_folder_sync_status():
    """Get comprehensive sync status between cache and filesystem."""
    settings = load_settings()
    export_root = settings.get('export', {}).get('output_root', '')
    
    if not export_root:
        return jsonify({'error': 'No export folder configured'}), 400
    
    export_path = Path(export_root) / 'OneNote_Export'
    
    # Get cache state
    notebooks = cache_manager.get_cached_notebooks()
    exported_pages = cache_manager.get_exported_pages()
    
    status = {
        'export_root': str(export_path),
        'export_exists': export_path.exists(),
        'notebooks_in_cache': len(notebooks),
        'pages_exported': len(exported_pages),
        'folders_on_disk': 0,
        'missing_notebook_folders': [],
        'extra_notebook_folders': [],
        'sync_issues': []
    }
    
    if not export_path.exists():
        status['sync_issues'].append('Export directory does not exist')
        return jsonify(status)
    
    # Count folders on disk
    disk_folders = set()
    for item in export_path.iterdir():
        if item.is_dir():
            disk_folders.add(item.name)
            status['folders_on_disk'] += 1
    
    # Check expected vs actual
    cache_notebooks = set()
    for nb in notebooks:
        nb_name = sanitize_filename(nb.get('displayName', nb.get('name', 'Untitled')))
        cache_notebooks.add(nb_name)
        if nb_name not in disk_folders:
            status['missing_notebook_folders'].append(nb_name)
    
    status['extra_notebook_folders'] = list(disk_folders - cache_notebooks)
    
    # Check exported pages still exist
    missing_files = 0
    for page_id, file_path in exported_pages.items():
        if file_path and not Path(file_path).exists():
            missing_files += 1
    
    if missing_files > 0:
        status['sync_issues'].append(f'{missing_files} exported files no longer exist on disk')
    
    if status['extra_notebook_folders']:
        status['sync_issues'].append(f'{len(status["extra_notebook_folders"])} orphaned notebook folders found')
    
    return jsonify(status)


# ============================================================================
# Routes - Export API
# ============================================================================

@app.route('/api/export/start', methods=['POST'])
def api_start_export():
    """Start an export job."""
    global current_export
    
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    with export_lock:
        if current_export and current_export.get('running'):
            return jsonify({'error': 'Export already in progress'}), 400
        
        data = request.json or {}
        notebook_ids = data.get('notebook_ids', [])  # Empty = all notebooks
        section_ids = data.get('section_ids', [])    # Specific sections to export
        page_ids = data.get('page_ids', [])          # Specific pages to export
        export_folder = data.get('export_folder', '')
        
        if not export_folder:
            settings = load_settings()
            export_folder = settings.get('export', {}).get('output_root', 
                                         str(Path.home() / 'OneNote-Exports'))
        
        current_export = {
            'running': True,
            'started': datetime.now().isoformat(),
            'notebook_ids': notebook_ids,
            'section_ids': section_ids,
            'page_ids': page_ids,
            'export_folder': export_folder,
            'progress': [],
            'complete': False,
            'result': None
        }
        
        # Save progress for crash recovery
        cache_manager.set_export_progress({
            'notebook_ids': notebook_ids,
            'section_ids': section_ids,
            'page_ids': page_ids,
            'export_folder': export_folder,
            'started': datetime.now().isoformat()
        })
    
    # Start export in background thread
    def run_export():
        global current_export
        try:
            exporter = OneNoteExporter(graph_client, export_folder)
            
            for progress in exporter.export_notebooks(notebook_ids if notebook_ids else None):
                with export_lock:
                    if current_export:
                        current_export['progress'].append(progress.to_dict())
                        if progress.stage in ('complete', 'cancelled', 'error'):
                            current_export['complete'] = True
                            current_export['running'] = False
            
            # Get final result
            with export_lock:
                if current_export:
                    current_export['result'] = {
                        'stats': exporter.stats.to_dict(),
                        'errors': exporter.errors[:50],
                        'files': len(exporter.exported_files)
                    }
                    current_export['running'] = False
                    current_export['complete'] = True
                    
        except Exception as e:
            logger.error(f"Export error: {e}")
            with export_lock:
                if current_export:
                    current_export['running'] = False
                    current_export['complete'] = True
                    current_export['error'] = str(e)
    
    thread = threading.Thread(target=run_export, daemon=True)
    thread.start()
    
    return jsonify({'success': True, 'message': 'Export started'})


@app.route('/api/export/status')
def api_export_status():
    """Get current export status."""
    with export_lock:
        if not current_export:
            return jsonify({'running': False, 'progress': []})
        
        # Return recent progress entries
        return jsonify({
            'running': current_export.get('running', False),
            'started': current_export.get('started'),
            'complete': current_export.get('complete', False),
            'progress': current_export.get('progress', [])[-20:],  # Last 20 entries
            'result': current_export.get('result'),
            'error': current_export.get('error')
        })


@app.route('/api/export/stream')
def api_export_stream():
    """Server-Sent Events stream for export progress."""
    def generate():
        last_index = 0
        while True:
            with export_lock:
                if not current_export:
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break
                
                progress = current_export.get('progress', [])
                if len(progress) > last_index:
                    for item in progress[last_index:]:
                        yield f"data: {json.dumps(item)}\n\n"
                    last_index = len(progress)
                
                if current_export.get('complete'):
                    result = {
                        'done': True,
                        'result': current_export.get('result'),
                        'error': current_export.get('error')
                    }
                    yield f"data: {json.dumps(result)}\n\n"
                    break
            
            import time
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/export/cancel', methods=['POST'])
def api_cancel_export():
    """Cancel current export."""
    global current_export
    
    with export_lock:
        if current_export and current_export.get('running'):
            # Signal cancellation (exporter checks this flag)
            current_export['running'] = False
            current_export['complete'] = True
            current_export['progress'].append({
                'stage': 'cancelled',
                'message': 'Export cancelled by user'
            })
            return jsonify({'success': True, 'message': 'Export cancelled'})
    
    return jsonify({'error': 'No export in progress'}), 400


# Global for batch export state
batch_export_state = {
    'running': False,
    'cancelled': False,
    'job_id': None
}
batch_export_lock = threading.Lock()


@app.route('/api/export/batch/start', methods=['POST'])
def api_start_batch_export():
    """Start a batch export of selected pages with SSE progress streaming."""
    global batch_export_state
    
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json or {}
    pages = data.get('pages', [])  # List of {page_id, page_title, notebook_name, section_name, created, modified}
    resume_from = data.get('resume_from', None)  # Page ID to resume from
    
    if not pages:
        return jsonify({'error': 'No pages to export'}), 400
    
    with batch_export_lock:
        if batch_export_state['running']:
            return jsonify({'error': 'Export already in progress'}), 400
        
        job_id = str(uuid.uuid4())[:8]
        batch_export_state = {
            'running': True,
            'cancelled': False,
            'job_id': job_id
        }
    
    # Save export queue for crash recovery
    cache_manager.set_export_progress({
        'job_id': job_id,
        'pages': pages,
        'started': datetime.now().isoformat(),
        'total_pages': len(pages),
        'completed_pages': [],
        'current_index': 0,
        'resume_from': resume_from
    })
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'total_pages': len(pages),
        'message': 'Export job created. Connect to /api/export/batch/stream to start.'
    })


@app.route('/api/export/batch/stream')
def api_batch_export_stream():
    """SSE stream for batch export with detailed progress."""
    global batch_export_state
    
    def generate():
        import requests
        
        # Get export progress from cache
        progress_data = cache_manager.get_export_progress()
        if not progress_data:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No export job found'})}\n\n"
            return
        
        pages = progress_data.get('pages', [])
        job_id = progress_data.get('job_id')
        completed_ids = set(progress_data.get('completed_pages', []))
        resume_from = progress_data.get('resume_from')
        
        # Get settings
        settings = load_settings()
        output_root = settings.get('export', {}).get('output_root', 
                                   str(Path.home() / 'OneNote-Exports'))
        
        def sanitize(name):
            invalid = '<>:"/\\|?*'
            result = ''.join(c if c not in invalid else '_' for c in (name or 'Untitled'))
            return result[:100].strip() or 'Untitled'
        
        total_pages = len(pages)
        exported_count = 0
        error_count = 0
        skipped_count = 0
        current_index = 0
        
        # Skip to resume point if specified
        skip_until_found = resume_from is not None
        
        yield f"data: {json.dumps({'type': 'start', 'job_id': job_id, 'total_pages': total_pages})}\n\n"
        
        for i, page_info in enumerate(pages):
            # Check cancellation
            with batch_export_lock:
                if batch_export_state.get('cancelled') or not batch_export_state.get('running'):
                    yield f"data: {json.dumps({'type': 'cancelled', 'exported': exported_count, 'errors': error_count})}\n\n"
                    break
            
            page_id = page_info.get('page_id')
            page_title = page_info.get('page_title', 'Untitled')
            notebook_name = page_info.get('notebook_name', 'Unknown')
            section_name = page_info.get('section_name', 'Unknown')
            created_time = page_info.get('created')
            modified_time = page_info.get('modified')
            
            current_index = i + 1
            
            # Handle resume logic
            if skip_until_found:
                if page_id == resume_from:
                    skip_until_found = False
                else:
                    skipped_count += 1
                    continue
            
            # Skip already completed pages
            if page_id in completed_ids:
                skipped_count += 1
                yield f"data: {json.dumps({'type': 'skip', 'page_id': page_id, 'page_title': page_title, 'reason': 'Already exported', 'current': current_index, 'total': total_pages})}\n\n"
                continue
            
            # Log what we're about to do
            yield f"data: {json.dumps({'type': 'page_start', 'page_id': page_id, 'page_title': page_title, 'notebook': notebook_name, 'section': section_name, 'current': current_index, 'total': total_pages})}\n\n"
            
            try:
                # Fetch page content
                yield f"data: {json.dumps({'type': 'status', 'message': f'Fetching content for: {page_title}'})}\n\n"
                
                content_url = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
                headers = {'Authorization': f'Bearer {graph_client.access_token}'}
                
                response = requests.get(content_url, headers=headers, timeout=60)
                response.raise_for_status()
                html_content = response.text
                
                # Setup paths
                safe_notebook = sanitize(notebook_name)
                safe_section = sanitize(section_name)
                safe_page = sanitize(page_title)
                
                export_folder = Path(output_root) / 'OneNote_Export' / safe_notebook / safe_section
                export_folder.mkdir(parents=True, exist_ok=True)
                
                attachments_folder = export_folder / '_attachments'
                
                # Convert with image downloading - collect image events
                yield f"data: {json.dumps({'type': 'status', 'message': f'Processing images for: {page_title}'})}\n\n"
                
                # Use list to collect image events since we can't yield from callback
                image_events = []
                def collect_image_progress(index, total, success, error):
                    image_events.append({
                        'index': index,
                        'total': total,
                        'success': success,
                        'error': error
                    })
                
                md_content, image_results = html_to_markdown_with_images(
                    html_content, page_title, attachments_folder,
                    created_time=created_time, modified_time=modified_time,
                    progress_callback=collect_image_progress
                )
                
                # Emit individual image events
                for img_event in image_events:
                    yield f"data: {json.dumps({'type': 'image_complete', 'page_id': page_id, 'index': img_event['index'], 'total': img_event['total'], 'success': img_event['success'], 'error': img_event['error']})}\\n\\n"
                
                # Report image results summary
                successful_images = sum(1 for r in image_results if r['success'])
                failed_images = sum(1 for r in image_results if not r['success'])
                
                if image_results:
                    yield f"data: {json.dumps({'type': 'images', 'page_id': page_id, 'downloaded': successful_images, 'failed': failed_images, 'total': len(image_results)})}\n\n"
                
                # Write file
                output_file = export_folder / f"{safe_page}.md"
                counter = 1
                while output_file.exists():
                    output_file = export_folder / f"{safe_page}_{counter}.md"
                    counter += 1
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                
                # Record success
                cache_manager.mark_page_exported(page_id, str(output_file))
                cache_manager.add_export_history({
                    'page_id': page_id,
                    'page_title': page_title,
                    'notebook_name': notebook_name,
                    'section_name': section_name,
                    'output_file': str(output_file),
                    'images': len(image_results),
                    'image_errors': failed_images,
                    'exported_at': datetime.now().isoformat()
                })
                
                # Update progress in cache
                completed_ids.add(page_id)
                progress_data['completed_pages'] = list(completed_ids)
                progress_data['current_index'] = current_index
                cache_manager.set_export_progress(progress_data)
                
                exported_count += 1
                yield f"data: {json.dumps({'type': 'page_complete', 'page_id': page_id, 'page_title': page_title, 'output_file': str(output_file), 'images': len(image_results), 'exported': exported_count, 'current': current_index, 'total': total_pages})}\n\n"
                
            except requests.Timeout:
                error_count += 1
                error_msg = f"Timeout fetching page content"
                logger.error(f"Export error for {page_title}: {error_msg}")
                yield f"data: {json.dumps({'type': 'page_error', 'page_id': page_id, 'page_title': page_title, 'error': error_msg, 'current': current_index, 'total': total_pages})}\n\n"
                
            except requests.RequestException as e:
                error_count += 1
                error_msg = f"HTTP error: {str(e)[:100]}"
                logger.error(f"Export error for {page_title}: {error_msg}")
                yield f"data: {json.dumps({'type': 'page_error', 'page_id': page_id, 'page_title': page_title, 'error': error_msg, 'current': current_index, 'total': total_pages})}\n\n"
                
            except Exception as e:
                error_count += 1
                error_msg = str(e)[:200]
                logger.error(f"Export error for {page_title}: {error_msg}")
                yield f"data: {json.dumps({'type': 'page_error', 'page_id': page_id, 'page_title': page_title, 'error': error_msg, 'current': current_index, 'total': total_pages})}\n\n"
        
        # Complete
        with batch_export_lock:
            batch_export_state['running'] = False
        
        # Clear progress on success (but keep history)
        if error_count == 0 and not batch_export_state.get('cancelled'):
            cache_manager.clear_export_progress()
        
        yield f"data: {json.dumps({'type': 'complete', 'exported': exported_count, 'errors': error_count, 'skipped': skipped_count, 'total': total_pages})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/export/batch/cancel', methods=['POST'])
def api_cancel_batch_export():
    """Cancel the current batch export."""
    global batch_export_state
    
    with batch_export_lock:
        if batch_export_state.get('running'):
            batch_export_state['cancelled'] = True
            return jsonify({'success': True, 'message': 'Export cancellation requested'})
    
    return jsonify({'error': 'No export in progress'}), 400


@app.route('/api/export/recovery')
def api_get_export_recovery():
    """Check if there's an incomplete export that can be resumed."""
    progress = cache_manager.get_export_progress()
    
    if not progress:
        return jsonify({'has_incomplete': False})
    
    # Check if it was actually incomplete
    pages = progress.get('pages', [])
    completed = progress.get('completed_pages', [])
    
    if len(completed) >= len(pages):
        # All done, clear it
        cache_manager.clear_export_progress()
        return jsonify({'has_incomplete': False})
    
    return jsonify({
        'has_incomplete': True,
        'job_id': progress.get('job_id'),
        'started': progress.get('started'),
        'total_pages': len(pages),
        'completed_pages': len(completed),
        'remaining_pages': len(pages) - len(completed),
        'pages': pages,
        'completed_page_ids': completed
    })


@app.route('/api/export/recovery/clear', methods=['POST'])
def api_clear_export_recovery():
    """Clear incomplete export data (user chose not to resume)."""
    cache_manager.clear_export_progress()
    return jsonify({'success': True, 'message': 'Export recovery data cleared'})


@app.route('/api/export/page', methods=['POST'])
def api_export_page():
    """Export a single page to Markdown file."""
    if not graph_client.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json or {}
    page_id = data.get('page_id')
    page_title = data.get('page_title', 'Untitled')
    content = data.get('content', '')
    notebook_name = data.get('notebook_name', 'Unknown')
    section_name = data.get('section_name', 'Unknown')
    output_root = data.get('output_root', '')
    
    if not page_id:
        return jsonify({'error': 'page_id is required'}), 400
    
    if not content:
        return jsonify({'error': 'content is required'}), 400
    
    # Get output folder from settings if not provided
    if not output_root:
        settings = load_settings()
        output_root = settings.get('export', {}).get('output_root', 
                                   str(Path.home() / 'OneNote-Exports'))
    
    try:
        # Sanitize names for filesystem
        def sanitize(name):
            invalid = '<>:"/\\|?*'
            result = ''.join(c if c not in invalid else '_' for c in name)
            return result[:100].strip() or 'Untitled'
        
        safe_notebook = sanitize(notebook_name)
        safe_section = sanitize(section_name)
        safe_page = sanitize(page_title)
        
        # Create folder structure
        export_folder = Path(output_root) / 'OneNote_Export' / safe_notebook / safe_section
        export_folder.mkdir(parents=True, exist_ok=True)
        
        # Convert HTML to Markdown
        md_content = html_to_markdown(content, page_title)
        
        # Write file
        output_file = export_folder / f"{safe_page}.md"
        
        # Handle duplicate names
        counter = 1
        while output_file.exists():
            output_file = export_folder / f"{safe_page}_{counter}.md"
            counter += 1
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        # Record export in cache
        cache_manager.mark_page_exported(page_id, str(output_file))
        cache_manager.add_export_history({
            'page_id': page_id,
            'page_title': page_title,
            'output_file': str(output_file),
            'exported_at': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': True,
            'output_file': str(output_file),
            'message': f'Exported to {output_file.name}'
        })
        
    except Exception as e:
        logger.error(f"Export page error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Image Download Helpers
# ============================================================================

def download_image(url: str, attachments_folder: Path, timeout: int = 30) -> tuple:
    """Download an image from URL and save to attachments folder.
    
    Returns: (success, local_filename or error_message, was_base64)
    """
    import requests
    
    try:
        # Handle base64 data URIs
        if url.startswith('data:'):
            # Parse data URI: data:image/png;base64,....
            match = re.match(r'data:image/(\w+);base64,(.+)', url)
            if match:
                img_format = match.group(1)
                img_data = base64.b64decode(match.group(2))
                
                # Generate unique filename from content hash
                img_hash = hashlib.md5(img_data).hexdigest()[:12]
                filename = f"image_{img_hash}.{img_format}"
                filepath = attachments_folder / filename
                
                with open(filepath, 'wb') as f:
                    f.write(img_data)
                
                return (True, filename, True)
            return (False, "Invalid base64 data URI", True)
        
        # Handle Graph API URLs - need authentication
        headers = {}
        if 'graph.microsoft.com' in url or 'onenote.com' in url:
            if graph_client.access_token:
                headers['Authorization'] = f'Bearer {graph_client.access_token}'
        
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()
        
        # Determine file extension from content type or URL
        content_type = response.headers.get('Content-Type', '')
        ext = 'png'  # default
        if 'jpeg' in content_type or 'jpg' in content_type:
            ext = 'jpg'
        elif 'gif' in content_type:
            ext = 'gif'
        elif 'webp' in content_type:
            ext = 'webp'
        elif 'svg' in content_type:
            ext = 'svg'
        
        # Generate unique filename from URL hash
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = f"image_{url_hash}.{ext}"
        filepath = attachments_folder / filename
        
        # Download in chunks to handle large images
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return (True, filename, False)
        
    except requests.Timeout:
        return (False, f"Timeout downloading image", False)
    except requests.RequestException as e:
        return (False, f"HTTP error: {str(e)[:100]}", False)
    except Exception as e:
        return (False, f"Error: {str(e)[:100]}", False)


def extract_and_download_images(html_content: str, attachments_folder: Path, 
                                 progress_callback=None) -> tuple:
    """Extract images from HTML, download them, and return updated HTML.
    
    Args:
        html_content: The HTML containing images
        attachments_folder: Where to save downloaded images
        progress_callback: Optional callback(index, total, success, error) called per image
    
    Returns: (updated_html, list of {url, local_path, success, error, index, total})
    """
    # Find all image sources
    img_pattern = r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>'
    matches = list(re.finditer(img_pattern, html_content, re.I))
    
    if not matches:
        return (html_content, [])
    
    # Create attachments folder
    attachments_folder.mkdir(parents=True, exist_ok=True)
    
    image_results = []
    updated_html = html_content
    total_images = len(matches)
    
    for i, match in enumerate(matches):
        original_url = match.group(1)
        index = i + 1
        
        success, result, was_base64 = download_image(original_url, attachments_folder)
        
        if success:
            # Replace URL with relative local path
            local_path = f"_attachments/{result}"
            updated_html = updated_html.replace(original_url, local_path)
            image_results.append({
                'url': original_url[:100] + '...' if len(original_url) > 100 else original_url,
                'local_path': local_path,
                'success': True,
                'error': None,
                'index': index,
                'total': total_images
            })
            # Call progress callback after download completes
            if progress_callback:
                progress_callback(index, total_images, True, None)
        else:
            # Keep original URL but log the error
            image_results.append({
                'url': original_url[:100] + '...' if len(original_url) > 100 else original_url,
                'local_path': None,
                'success': False,
                'error': result,
                'index': index,
                'total': total_images
            })
            # Call progress callback with error
            if progress_callback:
                progress_callback(index, total_images, False, result)
    
    return (updated_html, image_results)


def html_to_markdown_with_images(html_content: str, title: str, attachments_folder: Path,
                                  created_time: str = None, modified_time: str = None,
                                  progress_callback=None) -> tuple:
    """Convert HTML to Joplin-compatible Markdown with local images.
    
    Returns: (markdown_content, image_results)
    """
    # First, extract and download images
    html_content, image_results = extract_and_download_images(
        html_content, attachments_folder, progress_callback
    )
    
    md = html_content
    
    # Remove HTML wrapper tags
    md = re.sub(r'<html[^>]*>|</html>|<head>[\s\S]*?</head>|<body[^>]*>|</body>', '', md, flags=re.I)
    
    # Convert headings
    md = re.sub(r'<h1[^>]*>([\s\S]*?)</h1>', r'# \1\n\n', md, flags=re.I)
    md = re.sub(r'<h2[^>]*>([\s\S]*?)</h2>', r'## \1\n\n', md, flags=re.I)
    md = re.sub(r'<h3[^>]*>([\s\S]*?)</h3>', r'### \1\n\n', md, flags=re.I)
    md = re.sub(r'<h4[^>]*>([\s\S]*?)</h4>', r'#### \1\n\n', md, flags=re.I)
    
    # Convert emphasis
    md = re.sub(r'<strong[^>]*>([\s\S]*?)</strong>', r'**\1**', md, flags=re.I)
    md = re.sub(r'<b[^>]*>([\s\S]*?)</b>', r'**\1**', md, flags=re.I)
    md = re.sub(r'<em[^>]*>([\s\S]*?)</em>', r'*\1*', md, flags=re.I)
    md = re.sub(r'<i[^>]*>([\s\S]*?)</i>', r'*\1*', md, flags=re.I)
    
    # Convert links
    md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>', r'[\2](\1)', md, flags=re.I)
    
    # Convert lists
    md = re.sub(r'<li[^>]*>([\s\S]*?)</li>', r'- \1\n', md, flags=re.I)
    md = re.sub(r'</?[ou]l[^>]*>', r'\n', md, flags=re.I)
    
    # Convert paragraphs and breaks
    md = re.sub(r'<p[^>]*>([\s\S]*?)</p>', r'\1\n\n', md, flags=re.I)
    md = re.sub(r'<br\s*/?>', r'\n', md, flags=re.I)
    md = re.sub(r'<div[^>]*>([\s\S]*?)</div>', r'\1\n', md, flags=re.I)
    
    # Convert images - now with local paths
    md = re.sub(r'<img[^>]*src="([^"]*)"[^>]*>', r'![image](\1)', md, flags=re.I)
    
    # Remove remaining HTML tags
    md = re.sub(r'<[^>]+>', '', md)
    
    # Clean up whitespace
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = md.strip()
    
    # Use original timestamps if available, otherwise use now
    now = datetime.now().isoformat()
    created = created_time or now
    updated = modified_time or now
    
    # Add YAML front matter for Joplin
    front_matter = f"""---
title: {title}
created: {created}
updated: {updated}
---

"""
    
    return (front_matter + md, image_results)


def html_to_markdown(html_content, title='Untitled'):
    """Convert HTML content to Joplin-compatible Markdown (legacy, no images)."""
    md = html_content
    
    # Remove HTML wrapper tags
    md = re.sub(r'<html[^>]*>|</html>|<head>[\s\S]*?</head>|<body[^>]*>|</body>', '', md, flags=re.I)
    
    # Convert headings
    md = re.sub(r'<h1[^>]*>([\s\S]*?)</h1>', r'# \1\n\n', md, flags=re.I)
    md = re.sub(r'<h2[^>]*>([\s\S]*?)</h2>', r'## \1\n\n', md, flags=re.I)
    md = re.sub(r'<h3[^>]*>([\s\S]*?)</h3>', r'### \1\n\n', md, flags=re.I)
    md = re.sub(r'<h4[^>]*>([\s\S]*?)</h4>', r'#### \1\n\n', md, flags=re.I)
    
    # Convert emphasis
    md = re.sub(r'<strong[^>]*>([\s\S]*?)</strong>', r'**\1**', md, flags=re.I)
    md = re.sub(r'<b[^>]*>([\s\S]*?)</b>', r'**\1**', md, flags=re.I)
    md = re.sub(r'<em[^>]*>([\s\S]*?)</em>', r'*\1*', md, flags=re.I)
    md = re.sub(r'<i[^>]*>([\s\S]*?)</i>', r'*\1*', md, flags=re.I)
    
    # Convert links
    md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>', r'[\2](\1)', md, flags=re.I)
    
    # Convert lists
    md = re.sub(r'<li[^>]*>([\s\S]*?)</li>', r'- \1\n', md, flags=re.I)
    md = re.sub(r'</?[ou]l[^>]*>', r'\n', md, flags=re.I)
    
    # Convert paragraphs and breaks
    md = re.sub(r'<p[^>]*>([\s\S]*?)</p>', r'\1\n\n', md, flags=re.I)
    md = re.sub(r'<br\s*/?>', r'\n', md, flags=re.I)
    md = re.sub(r'<div[^>]*>([\s\S]*?)</div>', r'\1\n', md, flags=re.I)
    
    # Convert images
    md = re.sub(r'<img[^>]*src="([^"]*)"[^>]*>', r'![image](\1)', md, flags=re.I)
    
    # Remove remaining HTML tags
    md = re.sub(r'<[^>]+>', '', md)
    
    # Clean up whitespace
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = md.strip()
    
    # Add YAML front matter for Joplin
    now = datetime.now().isoformat()
    front_matter = f"""---
title: {title}
created: {now}
updated: {now}
---

"""
    
    return front_matter + md


# ============================================================================
# Routes - File Browser API
# ============================================================================

@app.route('/api/exports')
def api_list_exports():
    """List previous exports."""
    settings = load_settings()
    export_folder = settings.get('export', {}).get('output_root', 
                                 str(Path.home() / 'OneNote-Exports'))
    
    export_path = Path(export_folder)
    if not export_path.exists():
        return jsonify({'exports': []})
    
    exports = []
    for item in sorted(export_path.iterdir(), reverse=True):
        if item.is_dir() and item.name.startswith('OneNote_Export_'):
            summary_path = item / 'export_summary.json'
            summary = {}
            if summary_path.exists():
                try:
                    with open(summary_path) as f:
                        summary = json.load(f)
                except:
                    pass
            
            exports.append({
                'name': item.name,
                'path': str(item),
                'created': datetime.fromtimestamp(item.stat().st_ctime).isoformat(),
                'stats': summary.get('stats', {}),
                'files': summary.get('files_exported', 0)
            })
    
    return jsonify({'exports': exports[:20]})  # Last 20 exports


# ============================================================================
# Main Entry Point
# ============================================================================

def open_browser(port):
    """Open browser after short delay."""
    import time
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{port}')


def main():
    """Run the web application."""
    port = 8080
    
    print("=" * 60)
    print("OneNote Web Exporter")
    print("=" * 60)
    print(f"Starting server on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    # Open browser in background
    browser_thread = threading.Thread(target=open_browser, args=(port,), daemon=True)
    browser_thread.start()
    
    # Check if running in production mode
    if os.environ.get('FLASK_ENV') == 'production':
        from waitress import serve
        serve(app, host='127.0.0.1', port=port)
    else:
        app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
