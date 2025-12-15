#!/usr/bin/env python3
"""
Unit tests for Index Builder Module.

Tests cover:
- Page tree building with parent-child relationships
- Orphan detection and handling
- Cycle detection in parent references
- Filesystem layout planning
- Index generation (Markdown and JSON)
- Slugification and path handling
- Windows path compatibility
"""

import unittest
import tempfile
import json
from pathlib import Path
from typing import List, Dict

from index_builder import (
    slugify,
    sanitize_path_name,
    safe_link_label,
    md_link_target,
    format_order_prefix,
    path_to_markdown_link,
    PageNode,
    SectionNode,
    NotebookNode,
    PageTreeBuilder,
    FilesystemLayoutPlanner,
    IndexGenerator,
    IndexBuilder,
    build_index,
    write_index_files,
    execute_filesystem_ops,
    validate_index_links,
)


class TestSlugify(unittest.TestCase):
    """Tests for slugify function."""
    
    def test_basic_text(self):
        """Should handle basic text."""
        self.assertEqual(slugify("Hello World"), "Hello World")
    
    def test_removes_forbidden_chars(self):
        """Should remove Windows-forbidden characters."""
        result = slugify('File<>:"/\\|?*Name')
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)
        self.assertNotIn(':', result)
        self.assertNotIn('"', result)
        self.assertNotIn('/', result)
        self.assertNotIn('\\', result)
        self.assertNotIn('|', result)
        self.assertNotIn('?', result)
        self.assertNotIn('*', result)
    
    def test_truncates_long_names(self):
        """Should truncate names over max_length."""
        long_name = 'a' * 200
        result = slugify(long_name, max_length=100)
        self.assertLessEqual(len(result), 100)
    
    def test_empty_string(self):
        """Should return 'untitled' for empty string."""
        self.assertEqual(slugify(""), "untitled")
        self.assertEqual(slugify("   "), "untitled")
        self.assertEqual(slugify("..."), "untitled")
    
    def test_strips_dots_and_spaces(self):
        """Should strip leading/trailing dots and spaces."""
        result = slugify("...  filename  ...")
        self.assertFalse(result.startswith('.'))
        self.assertFalse(result.startswith(' '))
        self.assertFalse(result.endswith('.'))
        self.assertFalse(result.endswith(' '))
    
    def test_unicode_handling(self):
        """Should handle unicode characters."""
        result = slugify("Café résumé naïve")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
    
    def test_multiple_spaces_preserved(self):
        """Should preserve spaces (matches sanitize_filename behavior)."""
        # Note: sanitize_filename does NOT collapse spaces
        result = slugify("Hello    World")
        # Spaces are preserved since sanitize_filename doesn't collapse them
        self.assertEqual(result, "Hello    World")


class TestFormatOrderPrefix(unittest.TestCase):
    """Tests for format_order_prefix function."""
    
    def test_single_digit(self):
        """Should use single digit for small totals."""
        self.assertEqual(format_order_prefix(1, 5), "1")
        self.assertEqual(format_order_prefix(5, 9), "5")
    
    def test_two_digits(self):
        """Should use two digits for medium totals."""
        self.assertEqual(format_order_prefix(1, 50), "01")
        self.assertEqual(format_order_prefix(50, 99), "50")
    
    def test_three_digits(self):
        """Should use three digits for large totals."""
        self.assertEqual(format_order_prefix(1, 500), "001")
        self.assertEqual(format_order_prefix(123, 999), "123")
    
    def test_four_digits(self):
        """Should use four digits for very large totals."""
        self.assertEqual(format_order_prefix(1, 5000), "0001")


class TestPathToMarkdownLink(unittest.TestCase):
    """Tests for path_to_markdown_link function."""
    
    def test_relative_path_forward_slashes(self):
        """Should convert to forward slashes."""
        base = Path("C:/export")
        target = Path("C:/export/notebook/section/page.md")
        result = path_to_markdown_link(target, base)
        self.assertEqual(result, "notebook/section/page.md")
        self.assertNotIn('\\', result)
    
    def test_windows_path_handling(self):
        """Should handle Windows-style paths."""
        base = Path(r"C:\export")
        target = Path(r"C:\export\notebook\section\page.md")
        result = path_to_markdown_link(target, base)
        self.assertNotIn('\\', result)
        self.assertIn('/', result)


class TestPageTreeBuilder(unittest.TestCase):
    """Tests for PageTreeBuilder class."""
    
    def test_flat_pages_no_hierarchy(self):
        """Should handle flat pages (all level 0)."""
        pages = [
            {'id': '1', 'title': 'Page 1', 'level': 0, 'order': 0},
            {'id': '2', 'title': 'Page 2', 'level': 0, 'order': 1},
            {'id': '3', 'title': 'Page 3', 'level': 0, 'order': 2},
        ]
        
        builder = PageTreeBuilder(pages)
        roots, orphans = builder.build()
        
        self.assertEqual(len(roots), 3)
        self.assertEqual(len(orphans), 0)
        for root in roots:
            self.assertEqual(len(root.children), 0)
    
    def test_simple_parent_child(self):
        """Should build parent-child relationships from levels."""
        pages = [
            {'id': 'p1', 'title': 'Parent 1', 'level': 0, 'order': 0},
            {'id': 'c1', 'title': 'Child 1', 'level': 1, 'order': 1},
            {'id': 'c2', 'title': 'Child 2', 'level': 1, 'order': 2},
            {'id': 'p2', 'title': 'Parent 2', 'level': 0, 'order': 3},
        ]
        
        builder = PageTreeBuilder(pages)
        roots, orphans = builder.build()
        
        self.assertEqual(len(roots), 2)
        self.assertEqual(len(orphans), 0)
        
        # First parent should have 2 children
        self.assertEqual(roots[0].title, 'Parent 1')
        self.assertEqual(len(roots[0].children), 2)
        
        # Second parent should have no children
        self.assertEqual(roots[1].title, 'Parent 2')
        self.assertEqual(len(roots[1].children), 0)
    
    def test_nested_hierarchy(self):
        """Should handle deeply nested hierarchy."""
        pages = [
            {'id': 'p', 'title': 'Parent', 'level': 0, 'order': 0},
            {'id': 'c1', 'title': 'Child L1', 'level': 1, 'order': 1},
            {'id': 'c2', 'title': 'Child L2', 'level': 2, 'order': 2},
            {'id': 'c3', 'title': 'Child L3', 'level': 3, 'order': 3},
        ]
        
        builder = PageTreeBuilder(pages)
        roots, orphans = builder.build()
        
        self.assertEqual(len(roots), 1)
        self.assertEqual(len(orphans), 0)
        
        # Check nested structure
        self.assertEqual(len(roots[0].children), 1)
        self.assertEqual(len(roots[0].children[0].children), 1)
        self.assertEqual(len(roots[0].children[0].children[0].children), 1)
    
    def test_orphan_missing_parent(self):
        """Should detect orphan when child has no parent."""
        pages = [
            # Child page at level 1 with no preceding parent
            {'id': 'orphan', 'title': 'Orphan Child', 'level': 1, 'order': 0},
            {'id': 'p1', 'title': 'Parent', 'level': 0, 'order': 1},
        ]
        
        builder = PageTreeBuilder(pages)
        roots, orphans = builder.build()
        
        self.assertEqual(len(orphans), 1)
        self.assertEqual(orphans[0].title, 'Orphan Child')
        self.assertTrue(orphans[0].is_orphan)
        self.assertIsNotNone(orphans[0].orphan_reason)
    
    def test_duplicate_titles(self):
        """Should handle pages with duplicate titles."""
        pages = [
            {'id': '1', 'title': 'Meeting Notes', 'level': 0, 'order': 0},
            {'id': '2', 'title': 'Meeting Notes', 'level': 0, 'order': 1},
            {'id': '3', 'title': 'Meeting Notes', 'level': 0, 'order': 2},
        ]
        
        builder = PageTreeBuilder(pages)
        roots, orphans = builder.build()
        
        # Should handle duplicates without crashing
        self.assertEqual(len(roots), 3)
        # Each should have unique ID
        ids = {r.id for r in roots}
        self.assertEqual(len(ids), 3)
    
    def test_empty_pages(self):
        """Should handle empty page list."""
        builder = PageTreeBuilder([])
        roots, orphans = builder.build()
        
        self.assertEqual(len(roots), 0)
        self.assertEqual(len(orphans), 0)
    
    def test_preserves_metadata(self):
        """Should preserve page metadata."""
        pages = [
            {
                'id': 'p1',
                'title': 'Test Page',
                'level': 0,
                'order': 0,
                'createdDateTime': '2024-01-01T00:00:00Z',
                'lastModifiedDateTime': '2024-01-02T00:00:00Z',
            }
        ]
        
        builder = PageTreeBuilder(pages)
        roots, _ = builder.build()
        
        self.assertEqual(roots[0].created_datetime, '2024-01-01T00:00:00Z')
        self.assertEqual(roots[0].last_modified_datetime, '2024-01-02T00:00:00Z')


class TestFilesystemLayoutPlanner(unittest.TestCase):
    """Tests for FilesystemLayoutPlanner class."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.export_root = Path(self.temp_dir)
        self.planner = FilesystemLayoutPlanner(self.export_root)
    
    def test_notebook_layout(self):
        """Should plan notebook folder correctly."""
        notebook = NotebookNode(id='nb1', name='My Notebook')
        path = self.planner.plan_notebook(notebook)
        
        self.assertEqual(notebook.resolved_path, path)
        self.assertTrue(str(path).endswith('My Notebook'))
    
    def test_section_layout(self):
        """Should plan section folder correctly."""
        notebook = NotebookNode(id='nb1', name='Notebook')
        nb_path = self.planner.plan_notebook(notebook)
        
        section = SectionNode(id='s1', name='My Section', 
                             notebook_id='nb1', notebook_name='Notebook')
        sec_path = self.planner.plan_section(section, nb_path)
        
        self.assertEqual(section.resolved_path, sec_path)
        self.assertIn('My Section', str(sec_path))
    
    def test_page_with_children_gets_folder(self):
        """Should create folder for pages with children."""
        section = SectionNode(id='s1', name='Section', 
                             notebook_id='nb1', notebook_name='Notebook')
        section.resolved_path = self.export_root / 'Notebook' / 'Section'
        
        parent = PageNode(id='p1', title='Parent Page', level=0, order=0)
        child = PageNode(id='c1', title='Child Page', level=1, order=1)
        parent.children = [child]
        
        section.root_pages = [parent]
        section.pages = [parent, child]
        section.orphan_pages = []
        
        self.planner.plan_pages(section)
        
        # Parent should have folder path
        self.assertIsNotNone(parent.resolved_path)
        # Parent content file should be inside folder with same name
        self.assertIn('Parent Page', str(parent.resolved_path))
        self.assertTrue(str(parent.resolved_path).endswith('.html'))
    
    def test_leaf_page_is_file(self):
        """Should create file for leaf pages (no children)."""
        section = SectionNode(id='s1', name='Section', 
                             notebook_id='nb1', notebook_name='Notebook')
        section.resolved_path = self.export_root / 'Notebook' / 'Section'
        
        leaf = PageNode(id='l1', title='Leaf Page', level=0, order=0)
        
        section.root_pages = [leaf]
        section.pages = [leaf]
        section.orphan_pages = []
        
        self.planner.plan_pages(section)
        
        # Leaf should be a .html file directly in section
        self.assertIsNotNone(leaf.resolved_path)
        self.assertTrue(str(leaf.resolved_path).endswith('.html'))
    
    def test_orphan_goes_to_section_folder(self):
        """Should put orphans in section folder (no __orphans__ folder)."""
        section = SectionNode(id='s1', name='Section', 
                             notebook_id='nb1', notebook_name='Notebook')
        section.resolved_path = self.export_root / 'Notebook' / 'Section'
        
        orphan = PageNode(id='o1', title='Orphan', level=1, order=0,
                         is_orphan=True, orphan_reason='No parent')
        
        section.root_pages = []
        section.pages = [orphan]
        section.orphan_pages = [orphan]
        
        self.planner.plan_pages(section)
        
        # Orphan should be in section folder (not special __orphans__)
        self.assertIn('Section', str(orphan.resolved_path))
        self.assertTrue(str(orphan.resolved_path).endswith('.html'))
    
    def test_id_to_path_mapping(self):
        """Should build ID to path mapping."""
        section = SectionNode(id='s1', name='Section', 
                             notebook_id='nb1', notebook_name='Notebook')
        section.resolved_path = self.export_root / 'Notebook' / 'Section'
        
        page = PageNode(id='unique-id-123', title='Test Page', level=0, order=0)
        
        section.root_pages = [page]
        section.pages = [page]
        section.orphan_pages = []
        
        self.planner.plan_pages(section)
        
        # ID should be in mapping
        self.assertIn('unique-id-123', self.planner.id_to_path)
        # Path should use forward slashes
        self.assertNotIn('\\', self.planner.id_to_path['unique-id-123'])


class TestIndexGenerator(unittest.TestCase):
    """Tests for IndexGenerator class."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.export_root = Path(self.temp_dir)
        self.generator = IndexGenerator(
            self.export_root,
            '2024-01-01T00:00:00Z',
            {'displayName': 'Test User', 'mail': 'test@example.com'},
            'consumers',
            'All notebooks'
        )
    
    def test_index_md_has_header(self):
        """Should include header information."""
        notebooks = []
        totals = {'notebooks': 0, 'sections': 0, 'pages': 0, 'orphans': 0, 'section_groups': 0}
        
        md = self.generator.generate_index_md(notebooks, totals)
        
        self.assertIn('# OneNote Export Index', md)
        self.assertIn('Test User', md)
        self.assertIn('test@example.com', md)
    
    def test_index_md_has_summary_table(self):
        """Should include summary table."""
        notebooks = []
        totals = {'notebooks': 5, 'sections': 10, 'pages': 100, 'orphans': 2, 'section_groups': 3}
        
        md = self.generator.generate_index_md(notebooks, totals)
        
        self.assertIn('| Notebooks | 5 |', md)
        self.assertIn('| Sections | 10 |', md)
        self.assertIn('| Pages | 100 |', md)
        self.assertIn('| Orphaned Pages | 2 |', md)
    
    def test_index_md_has_clickable_links(self):
        """Should include clickable Markdown links."""
        notebook = NotebookNode(id='nb1', name='Test Notebook')
        notebook.resolved_path = self.export_root / 'Test Notebook'
        
        section = SectionNode(id='s1', name='Test Section',
                             notebook_id='nb1', notebook_name='Test Notebook')
        section.resolved_path = self.export_root / 'Test Notebook' / 'Test Section'
        
        page = PageNode(id='p1', title='Test Page', level=0, order=0, order_prefix='1')
        page.resolved_path = self.export_root / 'Test Notebook' / 'Test Section' / '1 - Test Page.md'
        
        section.root_pages = [page]
        section.pages = [page]
        section.orphan_pages = []
        notebook.sections = [section]
        
        totals = {'notebooks': 1, 'sections': 1, 'pages': 1, 'orphans': 0, 'section_groups': 0}
        
        md = self.generator.generate_index_md([notebook], totals)
        
        # Should have markdown links
        self.assertIn('[Test Notebook]', md)
        self.assertIn('[Test Section]', md)
        self.assertIn('[Test Page]', md)
        # Links should use forward slashes
        self.assertNotIn('\\', md)
    
    def test_index_md_shows_orphans(self):
        """Should show orphan section when orphans exist."""
        notebook = NotebookNode(id='nb1', name='Notebook')
        notebook.resolved_path = self.export_root / 'Notebook'
        
        section = SectionNode(id='s1', name='Section',
                             notebook_id='nb1', notebook_name='Notebook')
        section.resolved_path = self.export_root / 'Notebook' / 'Section'
        
        orphan = PageNode(id='o1', title='Orphan Page', level=1, order=0,
                         is_orphan=True, orphan_reason='Missing parent',
                         order_prefix='1')
        orphan.resolved_path = self.export_root / 'Notebook' / 'Section' / '__orphans__' / '1 - Orphan Page.md'
        
        section.root_pages = []
        section.pages = [orphan]
        section.orphan_pages = [orphan]
        notebook.sections = [section]
        
        totals = {'notebooks': 1, 'sections': 1, 'pages': 1, 'orphans': 1, 'section_groups': 0}
        
        md = self.generator.generate_index_md([notebook], totals)
        
        self.assertIn('Orphaned Pages', md)
        self.assertIn('Orphan Page', md)
    
    def test_index_json_structure(self):
        """Should generate correct JSON structure."""
        notebook = NotebookNode(id='nb1', name='Notebook',
                               created_datetime='2024-01-01',
                               last_modified_datetime='2024-01-02')
        notebook.resolved_path = self.export_root / 'Notebook'
        notebook.sections = []
        
        totals = {'notebooks': 1, 'sections': 0, 'pages': 0, 'orphans': 0}
        id_to_path = {}
        
        data = self.generator.generate_index_json([notebook], id_to_path, totals)
        
        self.assertEqual(data['version'], '3.1')
        self.assertIn('notebooks', data)
        self.assertEqual(len(data['notebooks']), 1)
        self.assertEqual(data['notebooks'][0]['notebookId'], 'nb1')
        self.assertEqual(data['notebooks'][0]['name'], 'Notebook')
    
    def test_index_json_includes_hierarchy(self):
        """Should include page hierarchy in JSON."""
        notebook = NotebookNode(id='nb1', name='Notebook')
        notebook.resolved_path = self.export_root / 'Notebook'
        
        section = SectionNode(id='s1', name='Section',
                             notebook_id='nb1', notebook_name='Notebook')
        section.resolved_path = self.export_root / 'Notebook' / 'Section'
        
        parent = PageNode(id='p1', title='Parent', level=0, order=0)
        child = PageNode(id='c1', title='Child', level=1, order=1,
                        parent_page_id='p1')
        parent.children = [child]
        
        section.root_pages = [parent]
        section.pages = [parent, child]
        section.orphan_pages = []
        notebook.sections = [section]
        
        totals = {'notebooks': 1, 'sections': 1, 'pages': 2, 'orphans': 0}
        id_to_path = {'p1': 'path/to/parent', 'c1': 'path/to/child'}
        
        data = self.generator.generate_index_json([notebook], id_to_path, totals)
        
        # Check hierarchy is preserved
        section_data = data['notebooks'][0]['sections'][0]
        self.assertEqual(len(section_data['pages']), 1)  # One root
        self.assertEqual(len(section_data['pages'][0]['children']), 1)  # One child


class TestIndexBuilder(unittest.TestCase):
    """Tests for IndexBuilder class (integration)."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.export_root = Path(self.temp_dir)
    
    def test_build_simple_structure(self):
        """Should build index for simple notebook structure."""
        preflight_data = {
            'scan_timestamp': '2024-01-01T00:00:00Z',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Test Notebook',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Test Section',
                            'pages': [
                                {'id': 'p1', 'title': 'Page 1', 'level': 0, 'order': 0},
                                {'id': 'p2', 'title': 'Page 2', 'level': 0, 'order': 1},
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(
            self.export_root,
            preflight_data,
            {'displayName': 'User', 'mail': 'user@test.com'},
            'consumers',
            'All notebooks'
        )
        
        self.assertEqual(result.stats['notebooks'], 1)
        self.assertEqual(result.stats['sections'], 1)
        self.assertEqual(result.stats['pages'], 2)
        self.assertIn('p1', result.id_to_path_map)
        self.assertIn('p2', result.id_to_path_map)
    
    def test_build_with_hierarchy(self):
        """Should handle parent-child hierarchy."""
        preflight_data = {
            'scan_timestamp': '2024-01-01T00:00:00Z',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Notebook',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section',
                            'pages': [
                                {'id': 'p1', 'title': 'Parent', 'level': 0, 'order': 0},
                                {'id': 'c1', 'title': 'Child 1', 'level': 1, 'order': 1},
                                {'id': 'c2', 'title': 'Child 2', 'level': 1, 'order': 2},
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(
            self.export_root,
            preflight_data,
            {'displayName': 'User', 'mail': 'user@test.com'},
            'consumers',
            'Test'
        )
        
        self.assertEqual(result.stats['parent_pages'], 1)
        self.assertEqual(result.stats['child_pages'], 2)
    
    def test_write_index_files(self):
        """Should write index.md and index.json to disk."""
        preflight_data = {
            'scan_timestamp': '2024-01-01T00:00:00Z',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Notebook',
                    'sections': [],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(
            self.export_root,
            preflight_data,
            {'displayName': 'User', 'mail': 'user@test.com'},
            'consumers',
            'Test'
        )
        
        md_path, json_path = write_index_files(self.export_root, result)
        
        self.assertTrue(md_path.exists())
        self.assertTrue(json_path.exists())
        
        # Verify content
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        self.assertIn('OneNote Export Index', md_content)
        
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        self.assertEqual(json_data['version'], '3.1')
    
    def test_execute_filesystem_ops(self):
        """Should create planned directories."""
        ops = [
            ('mkdir', self.export_root / 'Notebook'),
            ('mkdir', self.export_root / 'Notebook' / 'Section'),
            ('mkdir', self.export_root / 'Notebook' / 'Section' / '__orphans__'),
        ]
        
        execute_filesystem_ops(ops)
        
        self.assertTrue((self.export_root / 'Notebook').exists())
        self.assertTrue((self.export_root / 'Notebook' / 'Section').exists())
        self.assertTrue((self.export_root / 'Notebook' / 'Section' / '__orphans__').exists())


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""
    
    def test_empty_notebook(self):
        """Should handle notebook with no sections."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {'id': 'nb1', 'name': 'Empty', 'sections': [], 'section_groups': []}
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        self.assertEqual(result.stats['notebooks'], 1)
        self.assertEqual(result.stats['sections'], 0)
    
    def test_section_with_no_pages(self):
        """Should handle section with no pages."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Notebook',
                    'sections': [
                        {'id': 's1', 'name': 'Empty Section', 'pages': []}
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        self.assertEqual(result.stats['sections'], 1)
        self.assertEqual(result.stats['pages'], 0)
    
    def test_deeply_nested_section_groups(self):
        """Should handle deeply nested section groups."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Notebook',
                    'sections': [],
                    'section_groups': [
                        {
                            'id': 'sg1',
                            'name': 'Level 1',
                            'sections': [],
                            'section_groups': [
                                {
                                    'id': 'sg2',
                                    'name': 'Level 2',
                                    'sections': [
                                        {'id': 's1', 'name': 'Deep Section', 'pages': [
                                            {'id': 'p1', 'title': 'Page', 'level': 0, 'order': 0}
                                        ]}
                                    ],
                                    'section_groups': []
                                }
                            ]
                        }
                    ]
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        self.assertEqual(result.stats['section_groups'], 2)
        self.assertEqual(result.stats['sections'], 1)
    
    def test_special_characters_in_names(self):
        """Should handle special characters in names."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'My <Special> "Notebook"',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section: With/Slashes\\And|Pipes',
                            'pages': [
                                {'id': 'p1', 'title': 'Page?With*Wildcards', 'level': 0, 'order': 0}
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        # Should complete without error
        self.assertEqual(result.stats['pages'], 1)
        # Paths should be filesystem-safe
        for path_str in result.id_to_path_map.values():
            self.assertNotIn('<', path_str)
            self.assertNotIn('>', path_str)
            self.assertNotIn(':', path_str)
            self.assertNotIn('|', path_str)
            self.assertNotIn('?', path_str)
            self.assertNotIn('*', path_str)


class TestSanitizePathName(unittest.TestCase):
    """Tests for sanitize_path_name function (must match onenote_exporter.sanitize_filename)."""
    
    def test_replaces_special_chars_with_underscore(self):
        """Should replace special chars with underscore like sanitize_filename."""
        # This matches what onenote_exporter.sanitize_filename does
        result = sanitize_path_name("Environment / Energy")
        self.assertEqual(result, "Environment _ Energy")
    
    def test_matches_sanitize_filename_colon(self):
        """Should replace colon with underscore."""
        result = sanitize_path_name("Time: 10:30 AM")
        self.assertEqual(result, "Time_ 10_30 AM")
    
    def test_matches_sanitize_filename_question(self):
        """Should replace question mark with underscore."""
        result = sanitize_path_name("What is this?")
        self.assertEqual(result, "What is this_")
    
    def test_preserves_underscores(self):
        """Should preserve existing underscores."""
        result = sanitize_path_name("File_Name_Test")
        self.assertEqual(result, "File_Name_Test")


class TestSafeLinkLabel(unittest.TestCase):
    """Tests for safe_link_label function."""
    
    def test_normal_title(self):
        """Should return stripped title."""
        self.assertEqual(safe_link_label("My Page"), "My Page")
        self.assertEqual(safe_link_label("  Padded Title  "), "Padded Title")
    
    def test_empty_title_returns_untitled(self):
        """Should return 'Untitled' for empty string."""
        self.assertEqual(safe_link_label(""), "Untitled")
    
    def test_whitespace_only_returns_untitled(self):
        """Should return 'Untitled' for whitespace-only string."""
        self.assertEqual(safe_link_label("   "), "Untitled")
        self.assertEqual(safe_link_label("\t\n"), "Untitled")
    
    def test_none_returns_untitled(self):
        """Should return 'Untitled' for None."""
        self.assertEqual(safe_link_label(None), "Untitled")


class TestMdLinkTarget(unittest.TestCase):
    """Tests for md_link_target function."""
    
    def test_encodes_spaces(self):
        """Should encode spaces as %20."""
        result = md_link_target("My Folder/My File.md")
        self.assertEqual(result, "My%20Folder/My%20File.md")
    
    def test_encodes_hash(self):
        """Should encode # as %23."""
        result = md_link_target("Page #1.md")
        self.assertEqual(result, "Page%20%231.md")
    
    def test_encodes_percent(self):
        """Should encode % as %25."""
        result = md_link_target("100% Done.md")
        self.assertEqual(result, "100%25%20Done.md")
    
    def test_encodes_question(self):
        """Should encode ? as %3F."""
        result = md_link_target("What?.md")
        self.assertEqual(result, "What%3F.md")
    
    def test_normalizes_backslashes(self):
        """Should convert backslashes to forward slashes."""
        result = md_link_target("Folder\\Subfolder\\File.md")
        self.assertEqual(result, "Folder/Subfolder/File.md")
    
    def test_preserves_forward_slashes(self):
        """Should preserve forward slashes (path separators)."""
        result = md_link_target("a/b/c.md")
        self.assertEqual(result, "a/b/c.md")


class TestDisplayVsFolderName(unittest.TestCase):
    """Tests ensuring display names differ from folder names when they should."""
    
    def test_index_md_uses_folder_name_for_link(self):
        """Notebook folder should use sanitized name, but display should be original."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        # Notebook with special chars: display shows "Environment / Energy"
        # but folder should be "Environment _ Energy"
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Environment / Energy',  # Has forward slash
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section One',
                            'pages': [
                                {'id': 'p1', 'title': 'Page 1', 'level': 0, 'order': 0}
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        # The resolved path should use sanitized folder name
        notebook = result.notebooks[0]
        # Path should have underscore, not slash
        self.assertIn('_', str(notebook.resolved_path))
        self.assertNotIn('/', notebook.resolved_path.name)  # No slash in folder name
        
        # But index.md should show original name in display
        self.assertIn('Environment / Energy', result.index_md_content)
        
        # Link target should point to sanitized folder
        self.assertIn('Environment%20_%20Energy', result.index_md_content)


class TestEmptyTitleHandling(unittest.TestCase):
    """Tests ensuring empty titles render as 'Untitled' in links."""
    
    def test_empty_title_shows_untitled_in_link(self):
        """Page with empty title should show [Untitled] not [] in link."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'My Notebook',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section',
                            'pages': [
                                {'id': 'p1', 'title': '', 'level': 0, 'order': 0},  # Empty title
                                {'id': 'p2', 'title': '   ', 'level': 0, 'order': 1},  # Whitespace
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        # Should NOT have empty link labels like "[]("
        self.assertNotIn('[](' , result.index_md_content)
        
        # Should have Untitled as link label
        self.assertIn('[Untitled]', result.index_md_content)
        
        # File path should still use "untitled" slug with .html extension
        self.assertIn('untitled.html', result.index_md_content.lower())


class TestSpacesInPathEncoding(unittest.TestCase):
    """Tests ensuring spaces in paths are URL encoded."""
    
    def test_spaces_encoded_in_links(self):
        """Spaces in paths should be encoded as %20."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'My Notebook',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section With Spaces',
                            'pages': [
                                {'id': 'p1', 'title': 'Page With Spaces', 'level': 0, 'order': 0}
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        # Links should have encoded spaces
        self.assertIn('%20', result.index_md_content)
        
        # Display text should have regular spaces (not encoded)
        self.assertIn('[Section With Spaces]', result.index_md_content)
        self.assertIn('[Page With Spaces]', result.index_md_content)


class TestValidateIndexLinks(unittest.TestCase):
    """Tests for validate_index_links function."""
    
    def test_detects_missing_links(self):
        """Should detect when link targets don't exist."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Notebook',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section',
                            'pages': [
                                {'id': 'p1', 'title': 'Page', 'level': 0, 'order': 0}
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        # Don't create the directories - they should be "missing"
        missing = validate_index_links(export_root, result)
        
        # Should detect missing notebook, section, and page
        self.assertGreater(len(missing), 0)
        
        # Should include context info
        has_notebook_missing = any(m.get('notebook_name') == 'Notebook' for m in missing)
        self.assertTrue(has_notebook_missing)
    
    def test_no_missing_when_dirs_exist(self):
        """Should return empty list when all paths exist."""
        temp_dir = tempfile.mkdtemp()
        export_root = Path(temp_dir)
        
        preflight_data = {
            'scan_timestamp': '2024-01-01',
            'notebooks': [
                {
                    'id': 'nb1',
                    'name': 'Notebook',
                    'sections': [
                        {
                            'id': 's1',
                            'name': 'Section',
                            'pages': [
                                {'id': 'p1', 'title': 'Page', 'level': 0, 'order': 0}
                            ]
                        }
                    ],
                    'section_groups': []
                }
            ],
            'errors': []
        }
        
        result = build_index(export_root, preflight_data, {}, 'consumers', 'Test')
        
        # Create all the expected paths
        execute_filesystem_ops(result.filesystem_ops)
        
        # Also create the page file
        for path_str in result.id_to_path_map.values():
            page_path = export_root / path_str
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.touch()
        
        missing = validate_index_links(export_root, result)
        
        # Should be no missing links
        self.assertEqual(len(missing), 0)


if __name__ == '__main__':
    unittest.main()
