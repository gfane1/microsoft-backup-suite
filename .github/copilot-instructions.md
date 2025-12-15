# GitHub Copilot Instructions for Microsoft Backup Suite

## Project Overview

This repository contains two Python tools for backing up Microsoft personal data:

1. **OneDrive Backup Tool** (`onedrive-backup/`) - Backs up OneDrive files to local storage
2. **OneNote Exporter** (`onenote-exporter/`) - Exports OneNote notebooks to Markdown/ENEX/HTML

Both tools use the Microsoft Graph API with OAuth 2.0 authentication for personal Microsoft accounts.

## Architecture

### OneNote Exporter (Primary Focus)

```
onenote_exporter.py      # Main entry point, CLI interface, orchestration
index_builder.py         # Builds navigable index.md and index.json
test_onenote_exporter.py # Unit tests for main exporter
test_index_builder.py    # Unit tests for index builder (81 tests)
```

**Key Classes:**
- `FileAndConsoleLogger` - Dual logging (file + console)
- `GraphClient` - Microsoft Graph API wrapper with retry logic
- `OneNoteExporter` - Main export orchestration
- `PageTreeBuilder` - Builds parent-child hierarchy from page levels
- `FilesystemLayoutPlanner` - Plans folder structure for export
- `IndexGenerator` - Generates index.md and index.json

### Key Technical Details

1. **Microsoft Graph API Pagination**
   - Always follow `@odata.nextLink` for complete data retrieval
   - Use `$select` to minimize payload size
   - Request `level,order` fields for page hierarchy

2. **Rate Limiting & Retry**
   - Handle 429 (Too Many Requests) with `Retry-After` header
   - Handle 503/504 with exponential backoff
   - Max 10 retries with jitter to prevent thundering herd

3. **Page Hierarchy**
   - OneNote API returns `level` (0=top, 1+=child) and `order` fields
   - Hierarchy inferred by scanning pages in order - no `parentPageId` in v1.0 API
   - Child pages stored in parent's folder

4. **Export Formats**
   - HTML: Primary format with embedded local image paths
   - Markdown: YAML front matter + converted content for Joplin/Obsidian
   - ENEX: Evernote XML format

5. **Image Handling**
   - Images downloaded to `{PageName}_attachments/` folder
   - HTML/Markdown updated to reference local paths
   - Supports base64 inline images and Graph API URLs

## Coding Standards

### Python Style
- Python 3.6+ compatible
- Type hints for function signatures
- Docstrings for classes and public methods
- Constants in SCREAMING_SNAKE_CASE
- Private methods prefixed with `_`

### Error Handling
- Log errors but don't crash on individual page failures
- Collect errors for summary report
- Use specific exception handling, not bare `except:`

### Testing
- Unit tests in `test_*.py` files
- Run with: `python -m unittest test_onenote_exporter test_index_builder -v`
- Mock external API calls in tests

### File Operations
- Use `pathlib.Path` for cross-platform paths
- UTF-8 encoding for all text files
- Sanitize filenames for Windows compatibility

## Common Tasks

### Adding a New Export Format
1. Add format option to `_get_export_format()` method
2. Create `_export_{format}()` method in `OneNoteExporter`
3. Update `_export_page()` to call new format
4. Update README documentation

### Improving HTML to Markdown Conversion
- Modify `_html_to_markdown()` method
- Add new regex patterns BEFORE the catch-all tag stripper
- Test with real OneNote HTML samples

### Adding New Graph API Fields
1. Update `$select` parameter in API calls
2. Add field handling in preflight/export methods
3. Include in metadata if relevant to export

## Build & Release

### Building Windows EXE
```bash
cd microsoft-backup-suite
python build_installer.py
```
Output: `dist/OneNote-Exporter.exe` (11.4 MB standalone)

### Testing Before Release
```bash
cd onenote-exporter
python -m unittest test_onenote_exporter test_index_builder -v
```

### Version Numbering
- Format: `MAJOR.MINOR.PATCH`
- Update `VERSION` constant in `onenote_exporter.py`
- Update CHANGELOG.md with changes

## Security Notes

- Client secrets are NEVER stored in settings.json
- Always prompt for client_secret at runtime
- Use `getpass.getpass()` for hidden input
- OAuth tokens are temporary (75 min access, 90 day refresh)

## Common Issues

1. **Child pages showing 0** - Check if Graph API returns `level` field (debug logging added)
2. **Images not displaying** - Ensure HTML/MD has local paths, not Graph URLs
3. **Index links broken** - Index builder must use same naming as exporter (.html, no order prefix)
4. **Rate limiting** - Exponential backoff handles this; check logs for 429s
