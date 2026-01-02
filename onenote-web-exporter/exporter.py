"""
OneNote Exporter - Export Logic with Progress Callbacks
Handles exporting notebooks, sections, and pages to Joplin-compatible Markdown.
"""

import os
import re
import html
import json
import base64
import mimetypes
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Generator
from dataclasses import dataclass, field

from graph_client import GraphClient

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class ExportProgress:
    """Progress update for streaming to UI."""
    stage: str  # 'scanning', 'exporting', 'complete', 'error'
    message: str
    current: int = 0
    total: int = 0
    notebook: str = ""
    section: str = ""
    page: str = ""
    percent: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'stage': self.stage,
            'message': self.message,
            'current': self.current,
            'total': self.total,
            'notebook': self.notebook,
            'section': self.section,
            'page': self.page,
            'percent': self.percent
        }


@dataclass
class ExportStats:
    """Export statistics."""
    notebooks: int = 0
    section_groups: int = 0
    sections: int = 0
    pages: int = 0
    child_pages: int = 0
    images: int = 0
    attachments: int = 0
    errors: int = 0
    skipped: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'notebooks': self.notebooks,
            'section_groups': self.section_groups,
            'sections': self.sections,
            'pages': self.pages,
            'child_pages': self.child_pages,
            'images': self.images,
            'attachments': self.attachments,
            'errors': self.errors,
            'skipped': self.skipped
        }


@dataclass 
class PageNode:
    """Page with hierarchy information."""
    id: str
    title: str
    level: int
    order: int
    created: str = ""
    modified: str = ""
    content_url: str = ""
    children: List['PageNode'] = field(default_factory=list)
    is_orphan: bool = False


@dataclass
class NotebookInfo:
    """Notebook information for UI display."""
    id: str
    name: str
    created: str
    modified: str
    section_count: int = 0
    page_count: int = 0
    sections: List[Dict] = field(default_factory=list)
    section_groups: List[Dict] = field(default_factory=list)


# ============================================================================
# OneNote Exporter
# ============================================================================
class OneNoteExporter:
    """Export OneNote content to Joplin-compatible Markdown."""
    
    def __init__(self, graph_client: GraphClient, export_root: str):
        self.graph = graph_client
        self.export_root = Path(export_root)
        self.stats = ExportStats()
        self.errors: List[Dict] = []
        self.exported_files: List[Dict] = []
        self._cancel_requested = False
    
    def cancel_export(self):
        """Request cancellation of current export."""
        self._cancel_requested = True
    
    def sanitize_filename(self, name: str, max_length: int = 200) -> str:
        """Sanitize filename for filesystem compatibility."""
        # Remove/replace invalid characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()
        sanitized = sanitized.strip('.')
        
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length].rsplit(' ', 1)[0]
        
        return sanitized or 'Untitled'
    
    # ========================================================================
    # Scanning Methods
    # ========================================================================
    
    def scan_notebooks(self) -> Generator[ExportProgress, None, List[NotebookInfo]]:
        """Scan all notebooks and return info. Yields progress updates."""
        yield ExportProgress('scanning', 'Fetching notebooks...')
        
        notebooks, errors = self.graph.get_notebooks()
        if errors:
            self.errors.extend(errors)
        
        result = []
        total = len(notebooks)
        
        for i, nb in enumerate(notebooks):
            if self._cancel_requested:
                yield ExportProgress('cancelled', 'Scan cancelled')
                return result
            
            yield ExportProgress(
                'scanning', 
                f'Scanning notebook: {nb.get("displayName", "Unknown")}',
                current=i + 1,
                total=total,
                notebook=nb.get('displayName', ''),
                percent=(i + 1) / total * 100 if total > 0 else 0
            )
            
            info = NotebookInfo(
                id=nb.get('id', ''),
                name=nb.get('displayName', 'Untitled'),
                created=nb.get('createdDateTime', ''),
                modified=nb.get('lastModifiedDateTime', ''),
            )
            
            # Get sections
            sections, sec_errors = self.graph.get_sections(info.id)
            if sec_errors:
                self.errors.extend(sec_errors)
            
            info.section_count = len(sections)
            
            # Count pages per section
            page_count = 0
            for sec in sections:
                sec_info = {
                    'id': sec.get('id', ''),
                    'name': sec.get('displayName', 'Untitled'),
                    'created': sec.get('createdDateTime', ''),
                    'modified': sec.get('lastModifiedDateTime', ''),
                    'page_count': 0
                }
                
                pages, pg_errors = self.graph.get_pages(sec_info['id'])
                if pg_errors:
                    self.errors.extend(pg_errors)
                
                sec_info['page_count'] = len(pages)
                page_count += len(pages)
                info.sections.append(sec_info)
            
            # Get section groups
            groups, grp_errors = self.graph.get_section_groups(info.id)
            if grp_errors:
                self.errors.extend(grp_errors)
            
            for grp in groups:
                grp_info = self._scan_section_group(grp)
                info.section_groups.append(grp_info)
                page_count += grp_info.get('page_count', 0)
            
            info.page_count = page_count
            result.append(info)
        
        yield ExportProgress('complete', f'Scan complete: {len(result)} notebooks')
        return result
    
    def _scan_section_group(self, group: Dict) -> Dict:
        """Recursively scan a section group."""
        grp_info = {
            'id': group.get('id', ''),
            'name': group.get('displayName', 'Untitled'),
            'sections': [],
            'section_groups': [],
            'page_count': 0
        }
        
        # Get sections in group
        sections, errors = self.graph.get_sections_in_group(grp_info['id'])
        if errors:
            self.errors.extend(errors)
        
        for sec in sections:
            sec_info = {
                'id': sec.get('id', ''),
                'name': sec.get('displayName', 'Untitled'),
                'page_count': 0
            }
            pages, pg_errors = self.graph.get_pages(sec_info['id'])
            if pg_errors:
                self.errors.extend(pg_errors)
            sec_info['page_count'] = len(pages)
            grp_info['page_count'] += len(pages)
            grp_info['sections'].append(sec_info)
        
        # Get nested groups
        nested, nested_errors = self.graph.get_nested_section_groups(grp_info['id'])
        if nested_errors:
            self.errors.extend(nested_errors)
        
        for nested_grp in nested:
            nested_info = self._scan_section_group(nested_grp)
            grp_info['section_groups'].append(nested_info)
            grp_info['page_count'] += nested_info.get('page_count', 0)
        
        return grp_info
    
    # ========================================================================
    # Export Methods
    # ========================================================================
    
    def export_notebooks(self, notebook_ids: List[str] = None) -> Generator[ExportProgress, None, Dict]:
        """
        Export selected notebooks (or all if None).
        Yields progress updates, returns final summary.
        """
        self._cancel_requested = False
        self.stats = ExportStats()
        self.errors = []
        self.exported_files = []
        
        # Create export directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        export_dir = self.export_root / f"OneNote_Export_{timestamp}"
        export_dir.mkdir(parents=True, exist_ok=True)
        
        yield ExportProgress('scanning', 'Fetching notebook list...')
        
        notebooks, errors = self.graph.get_notebooks()
        if errors:
            self.errors.extend(errors)
        
        # Filter if specific notebooks selected
        if notebook_ids:
            notebooks = [nb for nb in notebooks if nb.get('id') in notebook_ids]
        
        total_notebooks = len(notebooks)
        self.stats.notebooks = total_notebooks
        
        # First pass: count total pages for progress
        total_pages = 0
        notebook_pages = {}
        
        for nb in notebooks:
            nb_id = nb.get('id', '')
            pages_in_nb = 0
            
            sections, _ = self.graph.get_sections(nb_id)
            for sec in sections:
                pages, _ = self.graph.get_pages(sec.get('id', ''))
                pages_in_nb += len(pages)
            
            # Include section groups
            groups, _ = self.graph.get_section_groups(nb_id)
            for grp in groups:
                pages_in_nb += self._count_pages_in_group(grp.get('id', ''))
            
            notebook_pages[nb_id] = pages_in_nb
            total_pages += pages_in_nb
        
        # Export each notebook
        pages_exported = 0
        
        for nb_idx, notebook in enumerate(notebooks):
            if self._cancel_requested:
                yield ExportProgress('cancelled', 'Export cancelled by user')
                break
            
            nb_name = notebook.get('displayName', 'Untitled')
            nb_id = notebook.get('id', '')
            
            yield ExportProgress(
                'exporting',
                f'Exporting notebook: {nb_name}',
                current=nb_idx + 1,
                total=total_notebooks,
                notebook=nb_name,
                percent=pages_exported / total_pages * 100 if total_pages > 0 else 0
            )
            
            nb_dir = export_dir / self.sanitize_filename(nb_name)
            nb_dir.mkdir(exist_ok=True)
            
            # Export sections
            sections, sec_errors = self.graph.get_sections(nb_id)
            if sec_errors:
                self.errors.extend(sec_errors)
            
            self.stats.sections += len(sections)
            
            for section in sections:
                if self._cancel_requested:
                    break
                
                sec_name = section.get('displayName', 'Untitled')
                yield ExportProgress(
                    'exporting',
                    f'Exporting section: {sec_name}',
                    current=pages_exported,
                    total=total_pages,
                    notebook=nb_name,
                    section=sec_name,
                    percent=pages_exported / total_pages * 100 if total_pages > 0 else 0
                )
                
                exported = yield from self._export_section(
                    section, nb_dir, nb_name, total_pages, pages_exported
                )
                pages_exported += exported
            
            # Export section groups
            groups, grp_errors = self.graph.get_section_groups(nb_id)
            if grp_errors:
                self.errors.extend(grp_errors)
            
            for group in groups:
                if self._cancel_requested:
                    break
                
                exported = yield from self._export_section_group(
                    group, nb_dir, nb_name, total_pages, pages_exported
                )
                pages_exported += exported
        
        # Generate index
        yield ExportProgress('exporting', 'Generating index files...')
        self._generate_index(export_dir)
        
        # Save summary
        summary = {
            'export_time': datetime.now().isoformat(),
            'export_directory': str(export_dir),
            'stats': self.stats.to_dict(),
            'errors': self.errors[:100],  # Limit errors in summary
            'error_count': len(self.errors),
            'files_exported': len(self.exported_files)
        }
        
        summary_path = export_dir / 'export_summary.json'
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)
        
        yield ExportProgress(
            'complete',
            f'Export complete! {self.stats.pages} pages exported to {export_dir}',
            current=total_pages,
            total=total_pages,
            percent=100
        )
        
        return summary
    
    def _count_pages_in_group(self, group_id: str) -> int:
        """Count total pages in a section group recursively."""
        count = 0
        
        sections, _ = self.graph.get_sections_in_group(group_id)
        for sec in sections:
            pages, _ = self.graph.get_pages(sec.get('id', ''))
            count += len(pages)
        
        nested, _ = self.graph.get_nested_section_groups(group_id)
        for grp in nested:
            count += self._count_pages_in_group(grp.get('id', ''))
        
        return count
    
    def _export_section_group(self, group: Dict, parent_dir: Path, 
                               notebook_name: str, total_pages: int,
                               pages_exported: int) -> Generator[ExportProgress, None, int]:
        """Export a section group recursively. Returns pages exported."""
        grp_name = group.get('displayName', 'Untitled')
        grp_id = group.get('id', '')
        grp_dir = parent_dir / self.sanitize_filename(grp_name)
        grp_dir.mkdir(exist_ok=True)
        
        self.stats.section_groups += 1
        exported = 0
        
        # Export sections
        sections, errors = self.graph.get_sections_in_group(grp_id)
        if errors:
            self.errors.extend(errors)
        
        self.stats.sections += len(sections)
        
        for section in sections:
            if self._cancel_requested:
                break
            
            sec_exported = yield from self._export_section(
                section, grp_dir, notebook_name, total_pages, pages_exported + exported
            )
            exported += sec_exported
        
        # Export nested groups
        nested, nested_errors = self.graph.get_nested_section_groups(grp_id)
        if nested_errors:
            self.errors.extend(nested_errors)
        
        for nested_grp in nested:
            if self._cancel_requested:
                break
            
            nested_exported = yield from self._export_section_group(
                nested_grp, grp_dir, notebook_name, total_pages, pages_exported + exported
            )
            exported += nested_exported
        
        return exported
    
    def _export_section(self, section: Dict, parent_dir: Path,
                        notebook_name: str, total_pages: int,
                        pages_exported: int) -> Generator[ExportProgress, None, int]:
        """Export a section. Returns number of pages exported."""
        sec_name = section.get('displayName', 'Untitled')
        sec_id = section.get('id', '')
        sec_dir = parent_dir / self.sanitize_filename(sec_name)
        sec_dir.mkdir(exist_ok=True)
        
        # Get pages
        pages, errors = self.graph.get_pages(sec_id)
        if errors:
            self.errors.extend(errors)
        
        # Build page hierarchy
        page_tree = self._build_page_tree(pages)
        
        exported = 0
        for page_node in page_tree:
            if self._cancel_requested:
                break
            
            yield ExportProgress(
                'exporting',
                f'Exporting: {page_node.title}',
                current=pages_exported + exported,
                total=total_pages,
                notebook=notebook_name,
                section=sec_name,
                page=page_node.title,
                percent=(pages_exported + exported) / total_pages * 100 if total_pages > 0 else 0
            )
            
            page_exported = self._export_page_tree(page_node, sec_dir)
            exported += page_exported
        
        return exported
    
    def _build_page_tree(self, pages: List[Dict]) -> List[PageNode]:
        """Build hierarchical page tree from flat list using level field."""
        nodes = []
        for p in pages:
            nodes.append(PageNode(
                id=p.get('id', ''),
                title=p.get('title', 'Untitled'),
                level=p.get('level', 0),
                order=p.get('order', 0),
                created=p.get('createdDateTime', ''),
                modified=p.get('lastModifiedDateTime', ''),
                content_url=p.get('contentUrl', '')
            ))
        
        # Sort by order
        nodes.sort(key=lambda x: x.order)
        
        # Build tree
        root_pages = []
        parent_stack = []  # Stack of (level, PageNode)
        
        for node in nodes:
            # Pop parents that are at same or higher level
            while parent_stack and parent_stack[-1][0] >= node.level:
                parent_stack.pop()
            
            if parent_stack:
                # This is a child page
                parent_stack[-1][1].children.append(node)
            else:
                # This is a root page
                root_pages.append(node)
            
            # Push this node as potential parent
            parent_stack.append((node.level, node))
        
        return root_pages
    
    def _export_page_tree(self, node: PageNode, parent_dir: Path, depth: int = 0) -> int:
        """Export a page and its children. Returns count of pages exported."""
        exported = 0
        safe_title = self.sanitize_filename(node.title)
        
        # If page has children, create folder
        if node.children:
            page_dir = parent_dir / safe_title
            page_dir.mkdir(exist_ok=True)
            
            # Export parent page as index in folder
            self._export_page(node, page_dir / f"{safe_title}.md", page_dir)
            exported += 1
            self.stats.pages += 1
            
            # Export children
            for child in node.children:
                child_exported = self._export_page_tree(child, page_dir, depth + 1)
                exported += child_exported
                self.stats.child_pages += child_exported
        else:
            # Simple page, no children
            self._export_page(node, parent_dir / f"{safe_title}.md", parent_dir)
            exported += 1
            self.stats.pages += 1
        
        return exported
    
    def _export_page(self, node: PageNode, md_path: Path, attachments_dir: Path):
        """Export a single page to Markdown with attachments."""
        try:
            # Get page content
            html_content = self.graph.get_page_content(node.id)
            if not html_content:
                self.errors.append({
                    'page_id': node.id,
                    'title': node.title,
                    'error': 'Failed to get page content'
                })
                self.stats.errors += 1
                return
            
            # Extract and download images
            html_content, images = self._extract_images(html_content, node.title, attachments_dir)
            self.stats.images += images
            
            # Convert to Markdown
            md_content = self._html_to_markdown(html_content)
            
            # Build YAML front matter
            escaped_title = node.title.replace('"', '\\"')
            front_matter = f"""---
title: "{escaped_title}"
created: {node.created}
modified: {node.modified}
tags: [onenote-export]
---

"""
            
            # Write file
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(front_matter)
                f.write(md_content)
            
            self.exported_files.append({
                'path': str(md_path),
                'title': node.title,
                'type': 'page'
            })
            
        except Exception as e:
            self.errors.append({
                'page_id': node.id,
                'title': node.title,
                'error': str(e)
            })
            self.stats.errors += 1
    
    def _extract_images(self, html_content: str, page_title: str, 
                        base_dir: Path) -> tuple[str, int]:
        """Extract and download images, update HTML with local paths."""
        image_count = 0
        safe_title = self.sanitize_filename(page_title)
        attachments_dir = base_dir / f"{safe_title}_attachments"
        
        # Find base64 images
        base64_pattern = r'<img[^>]+src="data:image/([^;]+);base64,([^"]+)"[^>]*>'
        
        def replace_base64(match):
            nonlocal image_count
            img_type = match.group(1)
            img_data = match.group(2)
            
            attachments_dir.mkdir(exist_ok=True)
            image_count += 1
            filename = f"image_{image_count}.{img_type}"
            filepath = attachments_dir / filename
            
            try:
                with open(filepath, 'wb') as f:
                    f.write(base64.b64decode(img_data))
                
                rel_path = f"{safe_title}_attachments/{filename}"
                return f'<img src="{rel_path}">'
            except Exception as e:
                logger.warning(f"Failed to save base64 image: {e}")
                return match.group(0)
        
        html_content = re.sub(base64_pattern, replace_base64, html_content)
        
        # Find Graph API image URLs
        graph_pattern = r'<img[^>]+src="(https://graph\.microsoft\.com[^"]+)"[^>]*>'
        
        def replace_graph_url(match):
            nonlocal image_count
            url = match.group(1)
            
            attachments_dir.mkdir(exist_ok=True)
            image_count += 1
            
            # Try to get extension from URL
            ext = 'png'
            if '.jpg' in url or '.jpeg' in url:
                ext = 'jpg'
            elif '.gif' in url:
                ext = 'gif'
            
            filename = f"image_{image_count}.{ext}"
            filepath = attachments_dir / filename
            
            try:
                data = self.graph.download_resource(url)
                if data:
                    with open(filepath, 'wb') as f:
                        f.write(data)
                    
                    rel_path = f"{safe_title}_attachments/{filename}"
                    return f'<img src="{rel_path}">'
            except Exception as e:
                logger.warning(f"Failed to download image: {e}")
            
            return match.group(0)
        
        html_content = re.sub(graph_pattern, replace_graph_url, html_content)
        
        return html_content, image_count
    
    def _html_to_markdown(self, html_content: str) -> str:
        """Convert HTML to Markdown."""
        md = html_content
        
        # Remove head section
        md = re.sub(r'<head>.*?</head>', '', md, flags=re.DOTALL | re.IGNORECASE)
        
        # Headers
        md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<h4[^>]*>(.*?)</h4>', r'#### \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<h5[^>]*>(.*?)</h5>', r'##### \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<h6[^>]*>(.*?)</h6>', r'###### \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        
        # Bold and italic
        md = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', md, flags=re.IGNORECASE | re.DOTALL)
        
        # Links
        md = re.sub(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.IGNORECASE | re.DOTALL)
        
        # Images - convert to markdown
        md = re.sub(r'<img[^>]+src="([^"]*)"[^>]*/?>', r'![](\1)', md, flags=re.IGNORECASE)
        
        # Lists
        md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<[ou]l[^>]*>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'</[ou]l>', '\n', md, flags=re.IGNORECASE)
        
        # Paragraphs and line breaks
        md = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<br\s*/?>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<div[^>]*>(.*?)</div>', r'\1\n', md, flags=re.IGNORECASE | re.DOTALL)
        
        # Code blocks
        md = re.sub(r'<pre[^>]*>(.*?)</pre>', r'```\n\1\n```\n', md, flags=re.IGNORECASE | re.DOTALL)
        md = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', md, flags=re.IGNORECASE | re.DOTALL)
        
        # Horizontal rule
        md = re.sub(r'<hr[^>]*/?>', '\n---\n', md, flags=re.IGNORECASE)
        
        # Tables (basic conversion)
        md = re.sub(r'<table[^>]*>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'</table>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<tr[^>]*>', '', md, flags=re.IGNORECASE)
        md = re.sub(r'</tr>', '\n', md, flags=re.IGNORECASE)
        md = re.sub(r'<t[dh][^>]*>(.*?)</t[dh]>', r'| \1 ', md, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove remaining HTML tags
        md = re.sub(r'<[^>]+>', '', md)
        
        # Unescape HTML entities
        md = html.unescape(md)
        
        # Clean up whitespace
        md = re.sub(r'\n{3,}', '\n\n', md)
        md = md.strip()
        
        return md
    
    def _generate_index(self, export_dir: Path):
        """Generate index.md for the export."""
        index_content = f"""# OneNote Export Index

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Statistics

- **Notebooks**: {self.stats.notebooks}
- **Sections**: {self.stats.sections}
- **Pages**: {self.stats.pages}
- **Images**: {self.stats.images}

## Contents

"""
        
        # Walk directory and build index
        for notebook_dir in sorted(export_dir.iterdir()):
            if notebook_dir.is_dir() and not notebook_dir.name.startswith('.'):
                index_content += f"\n### 📓 {notebook_dir.name}\n\n"
                index_content += self._index_directory(notebook_dir, 1)
        
        with open(export_dir / 'index.md', 'w', encoding='utf-8') as f:
            f.write(index_content)
    
    def _index_directory(self, directory: Path, depth: int) -> str:
        """Recursively index a directory."""
        content = ""
        indent = "  " * depth
        
        items = sorted(directory.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        
        for item in items:
            if item.name.startswith('.') or item.name.endswith('_attachments'):
                continue
            
            if item.is_dir():
                content += f"{indent}- 📁 **{item.name}**/\n"
                content += self._index_directory(item, depth + 1)
            elif item.suffix == '.md':
                rel_path = item.relative_to(directory.parent.parent)
                content += f"{indent}- [{item.stem}]({rel_path})\n"
        
        return content
