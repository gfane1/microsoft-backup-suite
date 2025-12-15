#!/usr/bin/env python3
"""
Unit tests for OneNote Exporter v3.0
Tests pagination logic, settings loading, and robust retry.
"""

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import requests

# Import the module under test
from onenote_exporter import load_settings, GraphClient, OneNoteExporter


class TestLoadSettings(unittest.TestCase):
    """Tests for settings.json loading."""
    
    def test_load_settings_file_not_exists(self):
        """Should return empty dict if file doesn't exist."""
        result = load_settings(Path("/nonexistent/path/settings.json"))
        self.assertEqual(result, {})
    
    def test_load_settings_valid_file(self):
        """Should load valid settings from file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "auth": {
                    "client_id": "test-client-id",
                    "tenant": "consumers"
                },
                "export": {
                    "output_root": "/tmp/export",
                    "format": "joplin"
                }
            }, f)
            temp_path = f.name
        
        try:
            result = load_settings(Path(temp_path))
            
            self.assertEqual(result['auth']['client_id'], 'test-client-id')
            self.assertEqual(result['auth']['tenant'], 'consumers')
            self.assertEqual(result['export']['format'], 'joplin')
        finally:
            try:
                Path(temp_path).unlink()
            except PermissionError:
                pass  # Windows file locking - ignore
    
    def test_load_settings_removes_client_secret(self):
        """Should NEVER load client_secret from file - security requirement."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "auth": {
                    "client_id": "test-client-id",
                    "client_secret": "SUPER_SECRET_VALUE",
                    "tenant": "consumers"
                }
            }, f)
            temp_path = f.name
        
        try:
            result = load_settings(Path(temp_path))
            
            # client_secret should be stripped
            self.assertNotIn('client_secret', result.get('auth', {}))
            # client_id should remain
            self.assertEqual(result['auth']['client_id'], 'test-client-id')
        finally:
            try:
                Path(temp_path).unlink()
            except PermissionError:
                pass  # Windows file locking - ignore
    
    def test_load_settings_invalid_json(self):
        """Should return empty dict for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name
        
        try:
            result = load_settings(Path(temp_path))
            self.assertEqual(result, {})
        finally:
            try:
                Path(temp_path).unlink()
            except PermissionError:
                pass  # Windows file locking - ignore


class TestGraphClient(unittest.TestCase):
    """Tests for GraphClient API class."""
    
    def test_init_default_max_retries(self):
        """Should initialize with default max_retries of 10."""
        client = GraphClient()
        self.assertEqual(client.max_retries, 10)
    
    def test_init_custom_max_retries(self):
        """Should accept custom max_retries."""
        client = GraphClient(max_retries=5)
        self.assertEqual(client.max_retries, 5)
    
    @patch('onenote_exporter.requests.get')
    def test_make_request_success(self, mock_get):
        """Should return response on success."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        client = GraphClient()
        client.access_token = 'test-token'
        
        result = client.make_request("https://example.com/api", "test")
        
        self.assertEqual(result, mock_response)
        mock_get.assert_called_once()
    
    @patch('onenote_exporter.requests.get')
    @patch('onenote_exporter.time.sleep')
    def test_make_request_retries_on_500(self, mock_sleep, mock_get):
        """Should retry on 500 server errors."""
        mock_error = Mock()
        mock_error.status_code = 500
        mock_error.text = "Internal Server Error"
        
        mock_success = Mock()
        mock_success.status_code = 200
        
        mock_get.side_effect = [mock_error, mock_error, mock_success]
        
        client = GraphClient(max_retries=5)
        client.access_token = 'test-token'
        
        result = client.make_request("https://example.com/api", "test")
        
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_get.call_count, 3)
    
    @patch('onenote_exporter.requests.get')
    @patch('onenote_exporter.time.sleep')
    def test_make_request_handles_429_with_retry_after(self, mock_sleep, mock_get):
        """Should respect Retry-After header on 429."""
        mock_429 = Mock()
        mock_429.status_code = 429
        mock_429.headers = {'Retry-After': '5'}
        mock_429.text = "Rate Limited"
        
        mock_success = Mock()
        mock_success.status_code = 200
        
        mock_get.side_effect = [mock_429, mock_success]
        
        client = GraphClient(max_retries=5)
        client.access_token = 'test-token'
        
        result = client.make_request("https://example.com/api", "test")
        
        self.assertEqual(result.status_code, 200)
        mock_sleep.assert_called_with(5)
    
    @patch('onenote_exporter.requests.get')
    @patch('onenote_exporter.time.sleep')
    def test_get_all_pages_single_page(self, mock_sleep, mock_get):
        """Should return items from single page when no nextLink."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'value': [{'id': '1'}, {'id': '2'}]
        }
        mock_get.return_value = mock_response
        
        client = GraphClient()
        client.access_token = 'test-token'
        
        items, errors = client.get_all_pages("https://example.com/api")
        
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['id'], '1')
        self.assertEqual(len(errors), 0)
    
    @patch('onenote_exporter.requests.get')
    @patch('onenote_exporter.time.sleep')
    def test_get_all_pages_follows_next_link(self, mock_sleep, mock_get):
        """Should follow @odata.nextLink to get all pages."""
        page1_response = Mock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            'value': [{'id': '1'}, {'id': '2'}],
            '@odata.nextLink': 'https://example.com/api?page=2'
        }
        
        page2_response = Mock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            'value': [{'id': '3'}, {'id': '4'}]
        }
        
        mock_get.side_effect = [page1_response, page2_response]
        
        client = GraphClient()
        client.access_token = 'test-token'
        
        items, errors = client.get_all_pages("https://example.com/api")
        
        self.assertEqual(len(items), 4)
        self.assertEqual([r['id'] for r in items], ['1', '2', '3', '4'])
        self.assertEqual(len(errors), 0)
    
    @patch('onenote_exporter.requests.get')
    @patch('onenote_exporter.time.sleep')
    def test_get_all_pages_returns_errors(self, mock_sleep, mock_get):
        """Should return errors list when pagination fails."""
        mock_error = Mock()
        mock_error.status_code = 500
        mock_error.text = "Server Error"
        mock_get.return_value = mock_error
        
        client = GraphClient(max_retries=2)
        client.access_token = 'test-token'
        
        items, errors = client.get_all_pages("https://example.com/api", "test context")
        
        self.assertEqual(len(items), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn('error', errors[0])


class TestOneNoteExporterInit(unittest.TestCase):
    """Tests for OneNoteExporter initialization."""
    
    def test_init_with_empty_settings(self):
        """Should initialize with defaults when no settings."""
        exporter = OneNoteExporter({})
        
        self.assertIsNone(exporter.graph.client_id)
        self.assertEqual(exporter.graph.tenant_id, 'consumers')
        self.assertEqual(exporter.export_format, 'joplin')
    
    def test_init_with_settings(self):
        """Should load values from settings."""
        settings = {
            'auth': {
                'client_id': 'my-client-id',
                'tenant': 'my-tenant'
            },
            'export': {
                'output_root': '/exports',
                'format': 'both',
                'max_retries': 5
            }
        }
        
        exporter = OneNoteExporter(settings)
        
        self.assertEqual(exporter.graph.client_id, 'my-client-id')
        self.assertEqual(exporter.graph.tenant_id, 'my-tenant')
        self.assertEqual(exporter.export_format, 'both')
        self.assertEqual(exporter.graph.max_retries, 5)
    
    def test_client_secret_not_in_init(self):
        """Should never have client_secret from settings."""
        settings = {
            'auth': {
                'client_id': 'my-client-id',
                'client_secret': 'should-not-be-here'
            }
        }
        
        exporter = OneNoteExporter(settings)
        
        # client_secret should be None (never loaded from settings)
        self.assertIsNone(exporter.graph.client_secret)


class TestSanitizeFilename(unittest.TestCase):
    """Tests for filename sanitization."""
    
    def test_removes_invalid_characters(self):
        """Should remove invalid filesystem characters."""
        exporter = OneNoteExporter({})
        
        result = exporter.sanitize_filename('file<>:"/\\|?*name')
        
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
        """Should truncate filenames over 200 characters."""
        exporter = OneNoteExporter({})
        
        long_name = 'a' * 300
        result = exporter.sanitize_filename(long_name)
        
        self.assertLessEqual(len(result), 200)
    
    def test_handles_empty_string(self):
        """Should return 'untitled' for empty string."""
        exporter = OneNoteExporter({})
        
        result = exporter.sanitize_filename('')
        
        self.assertEqual(result, 'untitled')
    
    def test_strips_dots_and_spaces(self):
        """Should strip leading/trailing dots and spaces."""
        exporter = OneNoteExporter({})
        
        result = exporter.sanitize_filename('...  filename  ...')
        
        self.assertFalse(result.startswith('.'))
        self.assertFalse(result.startswith(' '))
        self.assertFalse(result.endswith('.'))
        self.assertFalse(result.endswith(' '))


class TestPageHierarchy(unittest.TestCase):
    """Tests for page hierarchy building."""
    
    def test_build_hierarchy_flat_pages(self):
        """Should handle flat pages (no children)."""
        exporter = OneNoteExporter({})
        
        pages = [
            {'id': '1', 'level': 0, 'order': 0},
            {'id': '2', 'level': 0, 'order': 1},
            {'id': '3', 'level': 0, 'order': 2}
        ]
        
        hierarchy = exporter._build_page_hierarchy(pages)
        
        # No parent-child relationships
        self.assertEqual(len(hierarchy), 0)
    
    def test_build_hierarchy_with_children(self):
        """Should build correct parent-child map."""
        exporter = OneNoteExporter({})
        
        pages = [
            {'id': 'parent1', 'level': 0, 'order': 0, 'title': 'Parent 1'},
            {'id': 'child1', 'level': 1, 'order': 1, 'title': 'Child 1'},
            {'id': 'child2', 'level': 1, 'order': 2, 'title': 'Child 2'},
            {'id': 'parent2', 'level': 0, 'order': 3, 'title': 'Parent 2'}
        ]
        
        hierarchy = exporter._build_page_hierarchy(pages)
        
        self.assertIn('parent1', hierarchy)
        self.assertEqual(len(hierarchy['parent1']), 2)
        self.assertNotIn('parent2', hierarchy)
    
    def test_build_hierarchy_nested_children(self):
        """Should handle nested levels."""
        exporter = OneNoteExporter({})
        
        pages = [
            {'id': 'p', 'level': 0, 'order': 0},
            {'id': 'c1', 'level': 1, 'order': 1},
            {'id': 'c2', 'level': 2, 'order': 2},  # Child of c1
        ]
        
        hierarchy = exporter._build_page_hierarchy(pages)
        
        self.assertIn('p', hierarchy)
        self.assertEqual(len(hierarchy['p']), 1)  # c1 is child of p
        self.assertIn('c1', hierarchy)
        self.assertEqual(len(hierarchy['c1']), 1)  # c2 is child of c1


if __name__ == '__main__':
    unittest.main()
