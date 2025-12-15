#!/usr/bin/env python3
"""
Index Builder Module for OneNote Exporter v3.1

Handles hierarchical page tree resolution, filesystem layout planning,
and generation of navigable index.md and index.json files.

Features:
- Parent-child page hierarchy resolution
- Cycle detection and orphan handling  
- Deterministic, filesystem-safe naming with order prefixes
- Navigable Markdown links in index.md
- Canonical structured inventory in index.json
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
import json


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PageNode:
    """Represents a page in the hierarchy tree."""
    id: str
    title: str
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    parent_page_id: Optional[str] = None
    level: int = 0
    order: int = 0
    
    # Resolved during tree building
    children: List['PageNode'] = field(default_factory=list)
    is_orphan: bool = False
    orphan_reason: Optional[str] = None
    resolved_path: Optional[Path] = None
    relative_path_from_root: Optional[str] = None
    depth: int = 0  # Depth in resolved tree
    order_prefix: str = ""  # e.g., "001"


@dataclass
class SectionNode:
    """Represents a section containing pages."""
    id: str
    name: str
    notebook_id: str
    notebook_name: str
    section_group_path: str = ""  # e.g., "GroupA/GroupB"
    pages: List[PageNode] = field(default_factory=list)
    root_pages: List[PageNode] = field(default_factory=list)  # Top-level pages
    orphan_pages: List[PageNode] = field(default_factory=list)
    resolved_path: Optional[Path] = None


@dataclass 
class NotebookNode:
    """Represents a notebook containing sections."""
    id: str
    name: str
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    sections: List[SectionNode] = field(default_factory=list)
    section_groups: List[Dict] = field(default_factory=list)
    resolved_path: Optional[Path] = None


@dataclass
class IndexBuildResult:
    """Result of index building operation."""
    notebooks: List[NotebookNode]
    index_md_content: str
    index_json_data: Dict[str, Any]
    id_to_path_map: Dict[str, str]  # pageId -> relative path
    filesystem_ops: List[Tuple[str, Path]]  # [(operation, path), ...]
    stats: Dict[str, int]
    errors: List[Dict[str, Any]]


# ============================================================================
# Utility Functions
# ============================================================================

def sanitize_path_name(text: str, max_length: int = 200) -> str:
    """
    Convert text to filesystem-safe name.
    MUST match onenote_exporter.sanitize_filename() exactly.
    
    This is the 'path name' used for creating folders and files.
    """
    if not text:
        return "untitled"
    
    # Replace forbidden characters with underscore (same as sanitize_filename)
    # Windows forbidden: < > : " / \ | ? *
    text = re.sub(r'[<>:"/\\|?*]', '_', text)
    
    # Strip leading/trailing dots and spaces
    text = text.strip('. ')
    
    # Truncate to max length
    if len(text) > max_length:
        text = text[:max_length].rstrip('. ')
    
    return text if text else "untitled"


# Keep slugify as alias for backwards compatibility in tests
def slugify(text: str, max_length: int = 200) -> str:
    """Alias for sanitize_path_name for backwards compatibility."""
    return sanitize_path_name(text, max_length)


def safe_link_label(title: str) -> str:
    """
    Return safe display text for Markdown link labels.
    
    If title is None, empty, or whitespace, returns 'Untitled'.
    Otherwise returns the stripped title.
    
    This is the 'display name' that appears in headings and link text.
    """
    if not title or not title.strip():
        return "Untitled"
    return title.strip()


def md_link_target(path: str) -> str:
    """
    Convert path to Markdown link target with proper encoding.
    
    - Normalizes path separators to forward slashes
    - URL encodes characters that can break Markdown links: space, #, %, ?
    - Does NOT encode slashes (they're path separators)
    """
    if not path:
        return ""
    
    # Convert backslashes to forward slashes
    path = path.replace('\\', '/')
    
    # URL encode problematic characters for Markdown links
    # Encode space, #, %, ? which can break Markdown links
    path = path.replace('%', '%25')  # Must encode % first
    path = path.replace(' ', '%20')
    path = path.replace('#', '%23')
    path = path.replace('?', '%3F')
    
    return path


def format_order_prefix(index: int, total: int) -> str:
    """Generate zero-padded order prefix based on total count (e.g., '01', '001')."""
    if total < 10:
        return f"{index:01d}"
    elif total < 100:
        return f"{index:02d}"
    elif total < 1000:
        return f"{index:03d}"
    else:
        return f"{index:04d}"


def path_to_markdown_link(path: Path, base_path: Path, encode: bool = False) -> str:
    """
    Convert filesystem path to relative Markdown link.
    Always uses forward slashes for Markdown compatibility.
    
    Args:
        path: The filesystem path to convert
        base_path: The base path to make relative to
        encode: If True, URL encode the result for Markdown links
        
    Returns:
        Relative path string with forward slashes
    """
    try:
        relative = path.relative_to(base_path)
        # Convert to forward slashes for Markdown
        result = str(relative).replace('\\', '/')
    except ValueError:
        result = str(path).replace('\\', '/')
    
    if encode:
        result = md_link_target(result)
    
    return result


# ============================================================================
# Tree Builder
# ============================================================================

class PageTreeBuilder:
    """
    Builds hierarchical page tree from flat page list.
    Handles parent-child relationships, cycles, and orphans.
    """
    
    def __init__(self, pages: List[Dict[str, Any]]):
        """
        Initialize with list of page metadata dicts.
        
        Expected page dict keys:
        - id: str
        - title: str
        - parentPageId: Optional[str] (from Graph API) OR inferred from level
        - level: int (0 = top level, 1+ = child)
        - order: int
        - createdDateTime: Optional[str]
        - lastModifiedDateTime: Optional[str]
        """
        self.raw_pages = pages
        self.nodes: Dict[str, PageNode] = {}
        self.root_nodes: List[PageNode] = []
        self.orphan_nodes: List[PageNode] = []
        
    def build(self) -> Tuple[List[PageNode], List[PageNode]]:
        """
        Build the page tree. Returns (root_nodes, orphan_nodes).
        
        Algorithm:
        1. Create PageNode for each page
        2. Build parent-child relationships based on level field
        3. Detect cycles via DFS
        4. Mark orphans (missing parent, cycle involvement)
        """
        if not self.raw_pages:
            return [], []
        
        # Step 1: Create nodes
        self._create_nodes()
        
        # Step 2: Build relationships based on level field
        self._build_relationships_from_levels()
        
        # Step 3: Detect cycles and mark orphans
        self._detect_cycles_and_orphans()
        
        # Step 4: Separate roots and orphans
        self._categorize_nodes()
        
        return self.root_nodes, self.orphan_nodes
    
    def _create_nodes(self):
        """Create PageNode objects from raw data."""
        for page in self.raw_pages:
            node = PageNode(
                id=page.get('id', ''),
                title=page.get('title', 'Untitled'),
                created_datetime=page.get('createdDateTime'),
                last_modified_datetime=page.get('lastModifiedDateTime'),
                parent_page_id=page.get('parentPageId'),
                level=page.get('level', 0),
                order=page.get('order', 0)
            )
            self.nodes[node.id] = node
    
    def _build_relationships_from_levels(self):
        """
        Build parent-child relationships from the level field.
        
        OneNote pages are ordered, and level indicates nesting depth.
        A page at level N is a child of the most recent page at level N-1.
        """
        # Sort by order to ensure correct sequencing
        sorted_nodes = sorted(self.nodes.values(), key=lambda n: n.order)
        
        # Stack tracks potential parents: [(node, level), ...]
        parent_stack: List[Tuple[PageNode, int]] = []
        
        for node in sorted_nodes:
            level = node.level
            
            # Pop stack until we find a valid parent level
            while parent_stack and parent_stack[-1][1] >= level:
                parent_stack.pop()
            
            # If level > 0 and we have a parent, establish relationship
            if level > 0 and parent_stack:
                parent_node = parent_stack[-1][0]
                node.parent_page_id = parent_node.id
                parent_node.children.append(node)
            elif level > 0:
                # Child page but no parent found - will be orphaned
                node.is_orphan = True
                node.orphan_reason = "No parent found at expected level"
            
            # Push current node as potential parent
            parent_stack.append((node, level))
    
    def _detect_cycles_and_orphans(self):
        """
        Detect cycles in the tree using DFS.
        Nodes involved in cycles are marked as orphans.
        """
        visited: Set[str] = set()
        in_stack: Set[str] = set()
        
        def dfs(node_id: str) -> bool:
            """Returns True if cycle detected."""
            if node_id in in_stack:
                return True  # Cycle detected
            if node_id in visited:
                return False
            
            visited.add(node_id)
            in_stack.add(node_id)
            
            node = self.nodes.get(node_id)
            if node:
                for child in node.children:
                    if dfs(child.id):
                        # Mark this node as involved in cycle
                        child.is_orphan = True
                        child.orphan_reason = "Involved in circular reference"
                        return True
            
            in_stack.remove(node_id)
            return False
        
        # Run DFS from each unvisited node
        for node_id in self.nodes:
            if node_id not in visited:
                dfs(node_id)
    
    def _categorize_nodes(self):
        """Separate root nodes from orphans."""
        for node in self.nodes.values():
            if node.is_orphan:
                self.orphan_nodes.append(node)
            elif node.level == 0 or not node.parent_page_id:
                self.root_nodes.append(node)
        
        # Sort roots by order
        self.root_nodes.sort(key=lambda n: n.order)
        self.orphan_nodes.sort(key=lambda n: n.order)


# ============================================================================
# Filesystem Layout Planner
# ============================================================================

class FilesystemLayoutPlanner:
    """
    Plans filesystem layout for exported pages.
    
    Layout rules:
    - Notebooks: <export_root>/<notebook_name>/
    - Section groups: <notebook>/<group_path>/
    - Sections: <section_group_or_notebook>/<section_name>/
    - Parent pages (with children): <section>/<NNN - Title>/
      - Parent content: <section>/<NNN - Title>/00 - <Title>.md
    - Leaf pages: <section>/<NNN - Title>.md
    - Orphans: <section>/__orphans__/<NNN - Title>.md
    """
    
    def __init__(self, export_root: Path):
        self.export_root = export_root
        self.id_to_path: Dict[str, str] = {}
        self.operations: List[Tuple[str, Path]] = []
        
    def plan_notebook(self, notebook: NotebookNode) -> Path:
        """Plan layout for a notebook."""
        nb_slug = slugify(notebook.name)
        nb_path = self.export_root / nb_slug
        notebook.resolved_path = nb_path
        self.operations.append(('mkdir', nb_path))
        return nb_path
    
    def plan_section(self, section: SectionNode, parent_path: Path) -> Path:
        """Plan layout for a section."""
        # Handle section group path
        if section.section_group_path:
            for group_name in section.section_group_path.split('/'):
                group_slug = slugify(group_name)
                parent_path = parent_path / group_slug
                self.operations.append(('mkdir', parent_path))
        
        sec_slug = slugify(section.name)
        sec_path = parent_path / sec_slug
        section.resolved_path = sec_path
        self.operations.append(('mkdir', sec_path))
        return sec_path
    
    def plan_pages(self, section: SectionNode):
        """
        Plan layout for all pages in a section.
        
        NOTE: Must match onenote_exporter actual structure:
        - No order prefixes in filenames
        - .html extension
        - No __orphans__ folder (exporter doesn't create one)
        """
        sec_path = section.resolved_path
        if not sec_path:
            return
        
        # Plan root pages (order prefix kept for display, not filename)
        total_roots = len(section.root_pages)
        for idx, page in enumerate(section.root_pages, start=1):
            prefix = format_order_prefix(idx, total_roots)
            self._plan_page_recursive(page, sec_path, prefix, depth=0)
        
        # Orphan pages - they still get exported to section folder
        # (no special __orphans__ folder in actual export)
        total_orphans = len(section.orphan_pages)
        for idx, page in enumerate(section.orphan_pages, start=1):
            prefix = format_order_prefix(idx, total_orphans)
            page.order_prefix = prefix
            page.depth = 0
            page_slug = slugify(page.title)
            content_file = sec_path / f"{page_slug}.html"
            page.resolved_path = content_file
            
            rel_path = path_to_markdown_link(content_file, self.export_root)
            page.relative_path_from_root = rel_path
            self.id_to_path[page.id] = rel_path
    
    def _plan_page_recursive(self, page: PageNode, parent_path: Path, 
                             prefix: str, depth: int):
        """
        Recursively plan page and its children.
        
        MUST match onenote_exporter._export_page naming exactly:
        - Folder for pages with children: {safe_title}/
        - File: {safe_title}.html (inside folder if has children, in section if not)
        """
        page.depth = depth
        page.order_prefix = prefix  # Keep for display purposes
        page_slug = slugify(page.title)
        
        if page.children:
            # Parent page: create folder named after page
            page_folder = parent_path / page_slug
            self.operations.append(('mkdir', page_folder))
            
            # Content file inside folder (same name as folder)
            content_file = page_folder / f"{page_slug}.html"
            page.resolved_path = content_file
            
            # Plan children (they go inside parent's folder)
            total_children = len(page.children)
            for idx, child in enumerate(page.children, start=1):
                child_prefix = format_order_prefix(idx, total_children)
                self._plan_page_recursive(child, page_folder, child_prefix, depth + 1)
        else:
            # Leaf page: just a file in parent folder
            content_file = parent_path / f"{page_slug}.html"
            page.resolved_path = content_file
        
        # Store path mapping
        if page.resolved_path:
            rel_path = path_to_markdown_link(page.resolved_path, self.export_root)
            page.relative_path_from_root = rel_path
            self.id_to_path[page.id] = rel_path
    
    def _plan_orphan_page(self, page: PageNode, orphan_path: Path, prefix: str):
        """Plan layout for an orphan page (matching exporter naming)."""
        page.depth = 0
        page.order_prefix = prefix
        page_slug = slugify(page.title)
        
        # Orphans get plain filename (no prefix in actual export)
        content_file = orphan_path / f"{page_slug}.html"
        page.resolved_path = content_file
        
        rel_path = path_to_markdown_link(content_file, self.export_root)
        page.relative_path_from_root = rel_path
        self.id_to_path[page.id] = rel_path


# ============================================================================
# Index Generator
# ============================================================================

class IndexGenerator:
    """Generates index.md and index.json from planned layout."""
    
    def __init__(self, export_root: Path, scan_timestamp: str,
                 account_info: Dict[str, Any], tenant: str, scope: str):
        self.export_root = export_root
        self.scan_timestamp = scan_timestamp
        self.account_info = account_info
        self.tenant = tenant
        self.scope = scope
        
    def generate_index_md(self, notebooks: List[NotebookNode], 
                          totals: Dict[str, int],
                          errors: List[Dict] = None) -> str:
        """Generate navigable index.md content."""
        lines = [
            "# OneNote Export Index",
            "",
            f"**Generated:** {self.scan_timestamp}",
            f"**Account:** {self.account_info.get('displayName', 'Unknown')}",
            f"**Email:** {self.account_info.get('mail', 'Unknown')}",
            f"**Tenant:** {self.tenant}",
            f"**Scope:** {self.scope}",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Notebooks | {totals.get('notebooks', 0)} |",
            f"| Section Groups | {totals.get('section_groups', 0)} |",
            f"| Sections | {totals.get('sections', 0)} |",
            f"| Pages | {totals.get('pages', 0)} |",
            f"| Orphaned Pages | {totals.get('orphans', 0)} |",
            ""
        ]
        
        # Errors section
        if errors:
            lines.append("## ⚠️ Errors During Scan")
            lines.append("")
            for err in errors[:20]:
                lines.append(f"- {err.get('context', 'Unknown')}: {err.get('error', 'Unknown')}")
            if len(errors) > 20:
                lines.append(f"- ... and {len(errors) - 20} more errors")
            lines.append("")
        
        # Table of Contents
        lines.append("## Table of Contents")
        lines.append("")
        
        for notebook in notebooks:
            self._append_notebook_toc(lines, notebook)
        
        return "\n".join(lines)
    
    def _append_notebook_toc(self, lines: List[str], notebook: NotebookNode):
        """Append notebook to table of contents."""
        nb_link = self._make_folder_link(notebook.resolved_path, notebook.name)
        lines.append(f"### 📓 {nb_link}")
        lines.append("")
        
        for section in notebook.sections:
            self._append_section_toc(lines, section)
        
        lines.append("")
    
    def _append_section_toc(self, lines: List[str], section: SectionNode):
        """Append section to table of contents."""
        sec_link = self._make_folder_link(section.resolved_path, section.name)
        
        # Include section group path if present
        if section.section_group_path:
            lines.append(f"#### 📁 {section.section_group_path}")
            lines.append("")
        
        page_count = len(section.pages)
        orphan_count = len(section.orphan_pages)
        
        summary = f"({page_count} pages"
        if orphan_count > 0:
            summary += f", {orphan_count} orphaned"
        summary += ")"
        
        lines.append(f"- 📑 {sec_link} {summary}")
        
        # Add page tree
        for page in section.root_pages:
            self._append_page_tree(lines, page, indent=1)
        
        # Add orphans section if any
        if section.orphan_pages:
            lines.append("")
            lines.append("  - **⚠️ Orphaned Pages**")
            for page in section.orphan_pages:
                self._append_page_link(lines, page, indent=2, is_orphan=True)
        
        lines.append("")
    
    def _append_page_tree(self, lines: List[str], page: PageNode, indent: int):
        """Recursively append page and children to TOC."""
        self._append_page_link(lines, page, indent)
        
        for child in page.children:
            self._append_page_tree(lines, child, indent + 1)
    
    def _append_page_link(self, lines: List[str], page: PageNode, 
                          indent: int, is_orphan: bool = False):
        """Append a single page link."""
        indent_str = "  " * indent
        
        if page.resolved_path:
            link = self._make_page_link(page.resolved_path, page.title)
        else:
            link = page.title
        
        prefix = f"{page.order_prefix}." if page.order_prefix else ""
        
        child_indicator = ""
        if page.children:
            child_indicator = f" (+{len(page.children)} children)"
        
        orphan_indicator = ""
        if is_orphan and page.orphan_reason:
            orphan_indicator = f" ⚠️ _{page.orphan_reason}_"
        
        lines.append(f"{indent_str}- {prefix} {link}{child_indicator}{orphan_indicator}")
    
    def _make_folder_link(self, path: Optional[Path], title: str) -> str:
        """
        Create Markdown link to folder.
        
        Uses safe_link_label for display text and md_link_target for encoded path.
        """
        display_name = safe_link_label(title)
        
        if not path:
            return f"**{display_name}**"
        
        # Get relative path from resolved folder, then encode for Markdown
        rel_path = path_to_markdown_link(path, self.export_root, encode=True)
        return f"[{display_name}]({rel_path}/)"
    
    def _make_page_link(self, path: Path, title: str) -> str:
        """
        Create Markdown link to page file.
        
        Uses safe_link_label for display text and md_link_target for encoded path.
        """
        display_name = safe_link_label(title)
        
        # Get relative path from resolved file, then encode for Markdown
        rel_path = path_to_markdown_link(path, self.export_root, encode=True)
        return f"[{display_name}]({rel_path})"
    
    def generate_index_json(self, notebooks: List[NotebookNode],
                            id_to_path: Dict[str, str],
                            totals: Dict[str, int],
                            errors: List[Dict] = None) -> Dict[str, Any]:
        """Generate canonical index.json structure."""
        data = {
            'version': '3.1',
            'scan_timestamp': self.scan_timestamp,
            'account': self.account_info,
            'tenant': self.tenant,
            'scope': self.scope,
            'totals': totals,
            'errors': errors or [],
            'id_to_path_map': id_to_path,
            'notebooks': []
        }
        
        for notebook in notebooks:
            nb_data = self._serialize_notebook(notebook)
            data['notebooks'].append(nb_data)
        
        return data
    
    def _serialize_notebook(self, notebook: NotebookNode) -> Dict[str, Any]:
        """Serialize notebook to JSON-compatible dict."""
        return {
            'notebookId': notebook.id,
            'name': notebook.name,
            'createdDateTime': notebook.created_datetime,
            'lastModifiedDateTime': notebook.last_modified_datetime,
            'resolvedPath': str(notebook.resolved_path) if notebook.resolved_path else None,
            'sections': [self._serialize_section(s) for s in notebook.sections],
            'sectionGroups': notebook.section_groups
        }
    
    def _serialize_section(self, section: SectionNode) -> Dict[str, Any]:
        """Serialize section to JSON-compatible dict."""
        return {
            'sectionId': section.id,
            'name': section.name,
            'notebookId': section.notebook_id,
            'sectionGroupPath': section.section_group_path,
            'resolvedPath': str(section.resolved_path) if section.resolved_path else None,
            'pageCount': len(section.pages),
            'orphanCount': len(section.orphan_pages),
            'pages': [self._serialize_page(p) for p in section.root_pages],
            'orphans': [self._serialize_page(p, is_orphan=True) for p in section.orphan_pages]
        }
    
    def _serialize_page(self, page: PageNode, is_orphan: bool = False) -> Dict[str, Any]:
        """Serialize page to JSON-compatible dict."""
        return {
            'pageId': page.id,
            'title': page.title,
            'createdDateTime': page.created_datetime,
            'lastModifiedDateTime': page.last_modified_datetime,
            'parentPageId': page.parent_page_id,
            'level': page.level,
            'order': page.order,
            'depth': page.depth,
            'orderPrefix': page.order_prefix,
            'resolvedPath': str(page.resolved_path) if page.resolved_path else None,
            'relativePathFromRoot': page.relative_path_from_root,
            'isOrphan': is_orphan or page.is_orphan,
            'orphanReason': page.orphan_reason,
            'children': [self._serialize_page(c) for c in page.children]
        }


# ============================================================================
# Main Index Builder
# ============================================================================

class IndexBuilder:
    """
    Main entry point for building index from preflight data.
    
    Usage:
        builder = IndexBuilder(export_root, preflight_data, account_info, tenant, scope)
        result = builder.build()
        # result.index_md_content - content for index.md
        # result.index_json_data - dict for index.json
        # result.filesystem_ops - list of operations to perform
        # result.id_to_path_map - page ID to relative path mapping
    """
    
    def __init__(self, export_root: Path, preflight_data: Dict[str, Any],
                 account_info: Dict[str, Any], tenant: str, scope: str):
        self.export_root = export_root
        self.preflight_data = preflight_data
        self.account_info = account_info
        self.tenant = tenant
        self.scope = scope
        self.scan_timestamp = preflight_data.get('scan_timestamp', datetime.now().isoformat())
        
        self.notebooks: List[NotebookNode] = []
        self.planner = FilesystemLayoutPlanner(export_root)
        self.stats = {
            'notebooks': 0,
            'section_groups': 0,
            'sections': 0,
            'pages': 0,
            'orphans': 0,
            'parent_pages': 0,
            'child_pages': 0
        }
        self.errors: List[Dict[str, Any]] = []
        
    def build(self) -> IndexBuildResult:
        """Build the complete index structure."""
        # Process notebooks from preflight data
        for nb_data in self.preflight_data.get('notebooks', []):
            notebook = self._process_notebook(nb_data)
            self.notebooks.append(notebook)
        
        # Collect errors from preflight
        self.errors = self.preflight_data.get('errors', [])
        
        # Generate index content
        generator = IndexGenerator(
            self.export_root,
            self.scan_timestamp,
            self.account_info,
            self.tenant,
            self.scope
        )
        
        index_md = generator.generate_index_md(
            self.notebooks, self.stats, self.errors
        )
        
        index_json = generator.generate_index_json(
            self.notebooks, self.planner.id_to_path, self.stats, self.errors
        )
        
        return IndexBuildResult(
            notebooks=self.notebooks,
            index_md_content=index_md,
            index_json_data=index_json,
            id_to_path_map=self.planner.id_to_path,
            filesystem_ops=self.planner.operations,
            stats=self.stats,
            errors=self.errors
        )
    
    def _process_notebook(self, nb_data: Dict[str, Any]) -> NotebookNode:
        """Process a notebook from preflight data."""
        notebook = NotebookNode(
            id=nb_data.get('id', ''),
            name=nb_data.get('name', 'Untitled'),
            created_datetime=nb_data.get('createdDateTime'),
            last_modified_datetime=nb_data.get('lastModifiedDateTime'),
            section_groups=nb_data.get('section_groups', [])
        )
        
        # Plan notebook folder
        nb_path = self.planner.plan_notebook(notebook)
        self.stats['notebooks'] += 1
        
        # Process direct sections
        for sec_data in nb_data.get('sections', []):
            section = self._process_section(sec_data, notebook, nb_path, "")
            notebook.sections.append(section)
        
        # Process section groups recursively
        self._process_section_groups(
            nb_data.get('section_groups', []),
            notebook,
            nb_path,
            ""
        )
        
        return notebook
    
    def _process_section_groups(self, section_groups: List[Dict], 
                                 notebook: NotebookNode,
                                 parent_path: Path,
                                 group_path: str):
        """Recursively process section groups."""
        for sg_data in section_groups:
            sg_name = sg_data.get('name', 'Untitled')
            new_group_path = f"{group_path}/{sg_name}" if group_path else sg_name
            
            self.stats['section_groups'] += 1
            
            # Process sections in this group
            for sec_data in sg_data.get('sections', []):
                section = self._process_section(
                    sec_data, notebook, parent_path, new_group_path
                )
                notebook.sections.append(section)
            
            # Recurse into nested groups
            self._process_section_groups(
                sg_data.get('section_groups', []),
                notebook,
                parent_path,
                new_group_path
            )
    
    def _process_section(self, sec_data: Dict[str, Any],
                         notebook: NotebookNode,
                         parent_path: Path,
                         section_group_path: str) -> SectionNode:
        """Process a section and its pages."""
        section = SectionNode(
            id=sec_data.get('id', ''),
            name=sec_data.get('name', 'Untitled'),
            notebook_id=notebook.id,
            notebook_name=notebook.name,
            section_group_path=section_group_path
        )
        
        # Plan section folder
        self.planner.plan_section(section, parent_path)
        self.stats['sections'] += 1
        
        # Build page tree
        raw_pages = sec_data.get('pages', [])
        tree_builder = PageTreeBuilder(raw_pages)
        root_pages, orphan_pages = tree_builder.build()
        
        # Store all pages for reference
        section.pages = list(tree_builder.nodes.values())
        section.root_pages = root_pages
        section.orphan_pages = orphan_pages
        
        # Update stats
        self.stats['pages'] += len(section.pages)
        self.stats['orphans'] += len(orphan_pages)
        
        # Count parent and child pages
        def count_hierarchy(pages: List[PageNode]):
            for p in pages:
                if p.children:
                    self.stats['parent_pages'] += 1
                    self.stats['child_pages'] += len(p.children)
                count_hierarchy(p.children)
        count_hierarchy(root_pages)
        
        # Plan filesystem layout for pages
        self.planner.plan_pages(section)
        
        # Collect section errors
        if sec_data.get('errors'):
            self.errors.extend(sec_data['errors'])
        
        return section


# ============================================================================
# Convenience Functions
# ============================================================================

def build_index(export_root: Path, preflight_data: Dict[str, Any],
                account_info: Dict[str, Any], tenant: str, 
                scope: str) -> IndexBuildResult:
    """
    Convenience function to build index from preflight data.
    
    Args:
        export_root: Root directory for export
        preflight_data: Data from preflight scan
        account_info: User account info dict
        tenant: Microsoft tenant ID
        scope: Export scope description
        
    Returns:
        IndexBuildResult with all generated content
    """
    builder = IndexBuilder(export_root, preflight_data, account_info, tenant, scope)
    return builder.build()


def write_index_files(export_root: Path, result: IndexBuildResult):
    """
    Write index.md and index.json files to disk.
    
    Args:
        export_root: Root directory for export
        result: IndexBuildResult from build_index()
    """
    # Write index.md
    index_md_path = export_root / 'index.md'
    with open(index_md_path, 'w', encoding='utf-8') as f:
        f.write(result.index_md_content)
    
    # Write index.json
    index_json_path = export_root / 'index.json'
    with open(index_json_path, 'w', encoding='utf-8') as f:
        json.dump(result.index_json_data, f, indent=2, ensure_ascii=False, default=str)
    
    return index_md_path, index_json_path


def execute_filesystem_ops(operations: List[Tuple[str, Path]]):
    """
    Execute planned filesystem operations.
    
    Args:
        operations: List of (operation, path) tuples from IndexBuildResult
    """
    for op, path in operations:
        if op == 'mkdir':
            path.mkdir(parents=True, exist_ok=True)


def validate_index_links(export_root: Path, result: IndexBuildResult, 
                         log_func: callable = None) -> List[Dict[str, Any]]:
    """
    Validate that all link targets in index.md exist on disk.
    
    Args:
        export_root: Root directory for export
        result: IndexBuildResult containing notebooks with resolved paths
        log_func: Optional function to log warnings (signature: log_func(message))
        
    Returns:
        List of missing link records with target, notebook_id, section_id, page_id
    """
    missing_links = []
    
    def check_path(path: Optional[Path], context: Dict[str, str]):
        """Check if path exists and record if missing."""
        if not path:
            return
        
        if not path.exists():
            record = {
                'target': str(path),
                'relative_target': str(path.relative_to(export_root)) if path.is_relative_to(export_root) else str(path),
                **context
            }
            missing_links.append(record)
            
            if log_func:
                log_func(f"⚠️ Missing link target: {record['relative_target']} "
                        f"({context.get('context', 'unknown')})")
    
    # Check notebook folders
    for notebook in result.notebooks:
        nb_context = {
            'notebook_id': notebook.id,
            'notebook_name': notebook.name,
            'section_id': None,
            'page_id': None,
            'context': f"notebook '{notebook.name}'"
        }
        check_path(notebook.resolved_path, nb_context)
        
        # Check section folders
        for section in notebook.sections:
            sec_context = {
                'notebook_id': notebook.id,
                'notebook_name': notebook.name,
                'section_id': section.id,
                'section_name': section.name,
                'page_id': None,
                'context': f"section '{section.name}' in notebook '{notebook.name}'"
            }
            check_path(section.resolved_path, sec_context)
            
            # Check page files
            def check_pages(pages: List[PageNode], parent_context: str):
                for page in pages:
                    page_context = {
                        'notebook_id': notebook.id,
                        'notebook_name': notebook.name,
                        'section_id': section.id,
                        'section_name': section.name,
                        'page_id': page.id,
                        'page_title': page.title,
                        'context': f"page '{page.title}' in {parent_context}"
                    }
                    check_path(page.resolved_path, page_context)
                    
                    # Recurse into children
                    if page.children:
                        check_pages(page.children, f"page '{page.title}'")
            
            check_pages(section.root_pages, f"section '{section.name}'")
            check_pages(section.orphan_pages, f"orphans in section '{section.name}'")
    
    return missing_links
