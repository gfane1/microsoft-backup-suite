# Pandoc Cleanup Tool for Joplin Exports (Future Tool)

## Overview

This document describes a future tool idea: `pandoc-from-joplin-cleanup`, which would provide enhanced post-processing for OneNote exports destined for Joplin.

## Problem Statement

When exporting OneNote content to Joplin format (Markdown), several issues arise:

1. **HTML remnants** - OneNote's HTML contains proprietary tags and attributes that don't convert cleanly
2. **Image path issues** - Embedded images may have broken references
3. **Table formatting** - Complex tables often lose structure
4. **List nesting** - Deeply nested lists may not render correctly
5. **Metadata cleanup** - OneNote-specific metadata clutters the markdown

## Proposed Solution

A post-processing tool that:

### 1. Uses Pandoc for Better Conversion
Instead of regex-based HTML-to-Markdown, leverage Pandoc's robust parser:
```bash
pandoc -f html -t markdown-smart --wrap=none input.html -o output.md
```

### 2. Cleans Up Common Issues
- Strip OneNote-specific data attributes
- Fix image paths to Joplin resource format
- Normalize table structures
- Fix heading hierarchy
- Clean up excessive whitespace

### 3. Preserves Attachments
- Map attachment references to Joplin resource IDs
- Generate proper Joplin-compatible links: `![image](:/resourceId)`

### 4. Handles Special Content
- Convert OneNote ink/handwriting markers to placeholders
- Preserve audio/video embeds with proper markdown links
- Handle code blocks with syntax detection

## Proposed Usage

```bash
# Process a single export directory
python pandoc_joplin_cleanup.py --input ./OneNote_Export_20241215/ --output ./JoplinReady/

# Process with Pandoc options
python pandoc_joplin_cleanup.py --input ./export/ --pandoc-opts="--wrap=preserve"

# Dry run to see what would change
python pandoc_joplin_cleanup.py --input ./export/ --dry-run

# Generate Joplin import-ready structure
python pandoc_joplin_cleanup.py --input ./export/ --joplin-import
```

## Implementation Notes

### Dependencies
- Python 3.8+
- Pandoc installed and in PATH
- `pypandoc` Python wrapper (optional)

### File Structure Output
```
JoplinReady/
├── notebooks/
│   ├── Notebook1/
│   │   ├── note1.md
│   │   ├── note2.md
│   │   └── resources/
│   │       ├── image1.png
│   │       └── audio1.m4a
│   └── Notebook2/
└── import_manifest.json
```

### Key Functions
1. `convert_html_to_md(html_path)` - Pandoc conversion
2. `fix_resource_links(md_content, resources_map)` - Update paths
3. `clean_onenote_artifacts(md_content)` - Remove cruft
4. `generate_joplin_manifest(export_dir)` - Create import metadata

## Why Not Build This Now?

This milestone focuses on:
1. **Correct enumeration** - Getting ALL pages from Graph API
2. **Preflight inventory** - Knowing what Graph can see
3. **Settings file support** - Easier repeated runs

The Pandoc cleanup is a **nice-to-have enhancement** that can be added after the core export is reliable. Users can still use the raw HTML exports or the basic Markdown conversion.

## Future Milestone

When implemented, this tool would be in:
- `onenote-exporter/pandoc_joplin_cleanup.py`
- `onenote-exporter/README_PANDOC.md` - Usage documentation

## Related Tools

- [Pandoc](https://pandoc.org/) - Universal document converter
- [Joplin](https://joplinapp.org/) - Note-taking app
- [html2text](https://github.com/Alir3z4/html2text) - Python HTML to Markdown

---

*This is a placeholder document. The tool described here is NOT YET IMPLEMENTED.*
