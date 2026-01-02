/**
 * OneNote Web Exporter - Client-side JavaScript
 */

// Utility functions
const utils = {
    // Format dates nicely
    formatDate(dateStr) {
        if (!dateStr) return 'Unknown';
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    },

    // Format file sizes
    formatSize(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i];
    },

    // Get current time for log entries
    getLogTime() {
        const now = new Date();
        return now.toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    },

    // Escape HTML to prevent XSS
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // Show a temporary message
    showMessage(element, message, type = 'success') {
        element.className = `message ${type}`;
        element.textContent = message;
        element.classList.remove('hidden');
    }
};

// API wrapper
const api = {
    async get(url) {
        const response = await fetch(url);
        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: response.statusText }));
            throw new Error(error.error || 'Request failed');
        }
        return response.json();
    },

    async post(url, data) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: response.statusText }));
            throw new Error(error.error || 'Request failed');
        }
        return response.json();
    }
};

// Notebook browser functionality
const notebookBrowser = {
    notebooks: [],
    selectedNotebooks: new Set(),

    async load() {
        const container = document.getElementById('notebooks-container');
        if (!container) return;

        try {
            container.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><p>Loading notebooks...</p></div>';
            
            const response = await api.get('/api/notebooks');
            this.notebooks = response.notebooks || [];
            
            this.render();
        } catch (error) {
            container.innerHTML = `
                <div class="card error">
                    <h2>Error Loading Notebooks</h2>
                    <p>${utils.escapeHtml(error.message)}</p>
                    <p><a href="/auth/login" class="btn btn-primary">Sign In Again</a></p>
                </div>
            `;
        }
    },

    render() {
        const container = document.getElementById('notebooks-container');
        if (!container) return;

        if (this.notebooks.length === 0) {
            container.innerHTML = `
                <div class="card">
                    <h2>No Notebooks Found</h2>
                    <p>No OneNote notebooks were found in your account.</p>
                </div>
            `;
            return;
        }

        let html = '<div class="notebooks-grid">';
        
        for (const notebook of this.notebooks) {
            const sectionCount = notebook.sections?.length || 0;
            const pageCount = notebook.sections?.reduce((sum, s) => sum + (s.page_count || 0), 0) || 0;
            
            html += `
                <div class="card notebook-card" data-id="${notebook.id}">
                    <div class="notebook-header">
                        <h2>📓 ${utils.escapeHtml(notebook.name)}</h2>
                        <span class="badge">${sectionCount} sections</span>
                    </div>
                    <div class="notebook-meta">
                        <span>📄 ${pageCount} pages</span>
                    </div>
                    <div class="notebook-dates">
                        <span>Created: ${utils.formatDate(notebook.created)}</span>
                        <span>Modified: ${utils.formatDate(notebook.modified)}</span>
                    </div>
                    <div class="sections-list collapsed" id="sections-${notebook.id}">
                        ${this.renderSections(notebook.sections || [])}
                    </div>
                    <button class="btn btn-secondary btn-small toggle-sections" onclick="notebookBrowser.toggleSections('${notebook.id}')">
                        Show Sections
                    </button>
                </div>
            `;
        }
        
        html += '</div>';
        container.innerHTML = html;
    },

    renderSections(sections) {
        if (!sections || sections.length === 0) {
            return '<p class="empty">No sections</p>';
        }

        let html = '<ul class="section-tree">';
        for (const section of sections) {
            html += `
                <li class="section-item">
                    <span>📑</span>
                    <span class="section-name">${utils.escapeHtml(section.name)}</span>
                    <span class="section-pages">${section.page_count || 0} pages</span>
                </li>
            `;
        }
        html += '</ul>';
        return html;
    },

    toggleSections(notebookId) {
        const sectionsEl = document.getElementById(`sections-${notebookId}`);
        const cardEl = sectionsEl?.closest('.notebook-card');
        const button = cardEl?.querySelector('.toggle-sections');
        
        if (sectionsEl && button) {
            sectionsEl.classList.toggle('collapsed');
            button.textContent = sectionsEl.classList.contains('collapsed') ? 'Show Sections' : 'Hide Sections';
        }
    }
};

// Export manager functionality
const exportManager = {
    eventSource: null,
    isExporting: false,

    init() {
        // Check if we're on the export page
        const exportBtn = document.getElementById('start-export-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => this.start());
        }

        const cancelBtn = document.getElementById('cancel-export-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.cancel());
        }

        const selectAllCheckbox = document.getElementById('select-all');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', () => this.toggleSelectAll());
        }
    },

    toggleSelectAll() {
        const selectAll = document.getElementById('select-all');
        const checkboxes = document.querySelectorAll('.notebook-checkbox input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = selectAll.checked);
    },

    getSelectedNotebooks() {
        const checkboxes = document.querySelectorAll('.notebook-checkbox input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    },

    async start() {
        const selected = this.getSelectedNotebooks();
        if (selected.length === 0) {
            alert('Please select at least one notebook to export.');
            return;
        }

        this.isExporting = true;
        this.updateUI('exporting');
        this.clearLog();
        this.addLogEntry('Starting export...', 'exporting');

        try {
            // Start the export
            const result = await api.post('/api/export/start', {
                notebook_ids: selected
            });

            if (!result.success) {
                throw new Error(result.error || 'Failed to start export');
            }

            this.addLogEntry(`Export started: ${result.export_id}`, 'scanning');

            // Connect to SSE stream
            this.connectToStream(result.export_id);
        } catch (error) {
            this.addLogEntry(`Error: ${error.message}`, 'error');
            this.isExporting = false;
            this.updateUI('error');
        }
    },

    connectToStream(exportId) {
        if (this.eventSource) {
            this.eventSource.close();
        }

        this.eventSource = new EventSource(`/api/export/stream?export_id=${exportId}`);

        this.eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleProgress(data);
        };

        this.eventSource.onerror = (error) => {
            console.error('SSE Error:', error);
            if (this.isExporting) {
                this.addLogEntry('Connection lost. Export may still be running.', 'error');
            }
            this.eventSource.close();
        };
    },

    handleProgress(data) {
        // Update progress bar
        if (data.percent !== undefined) {
            this.updateProgress(data.percent);
        }

        // Update stats
        if (data.stats) {
            this.updateStats(data.stats);
        }

        // Add log entry
        if (data.message) {
            const type = data.status || 'exporting';
            this.addLogEntry(data.message, type);
        }

        // Handle completion
        if (data.status === 'complete') {
            this.isExporting = false;
            this.updateUI('complete');
            this.showSummary(data.stats);
            if (this.eventSource) {
                this.eventSource.close();
            }
        }

        // Handle errors
        if (data.status === 'error') {
            this.isExporting = false;
            this.updateUI('error');
            if (this.eventSource) {
                this.eventSource.close();
            }
        }
    },

    updateProgress(percent) {
        const fill = document.getElementById('progress-fill');
        const text = document.getElementById('progress-percent');
        
        if (fill) fill.style.width = `${percent}%`;
        if (text) text.textContent = `${Math.round(percent)}%`;
    },

    updateStats(stats) {
        const elements = {
            'stat-notebooks': stats.notebooks_exported,
            'stat-sections': stats.sections_exported,
            'stat-pages': stats.pages_exported,
            'stat-images': stats.images_downloaded,
            'stat-errors': stats.errors
        };

        for (const [id, value] of Object.entries(elements)) {
            const el = document.getElementById(id);
            if (el) el.textContent = value || 0;
        }
    },

    addLogEntry(message, type = 'exporting') {
        const log = document.getElementById('progress-log');
        if (!log) return;

        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        entry.innerHTML = `<span class="log-time">[${utils.getLogTime()}]</span> ${utils.escapeHtml(message)}`;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
    },

    clearLog() {
        const log = document.getElementById('progress-log');
        if (log) log.innerHTML = '';
    },

    updateUI(state) {
        const startBtn = document.getElementById('start-export-btn');
        const cancelBtn = document.getElementById('cancel-export-btn');
        const selectionArea = document.getElementById('selection-area');
        const progressArea = document.getElementById('progress-area');
        const summaryArea = document.getElementById('summary-area');

        switch (state) {
            case 'exporting':
                if (startBtn) startBtn.disabled = true;
                if (cancelBtn) cancelBtn.classList.remove('hidden');
                if (selectionArea) selectionArea.style.opacity = '0.5';
                if (progressArea) progressArea.classList.remove('hidden');
                if (summaryArea) summaryArea.classList.add('hidden');
                break;
            case 'complete':
                if (startBtn) startBtn.disabled = false;
                if (cancelBtn) cancelBtn.classList.add('hidden');
                if (selectionArea) selectionArea.style.opacity = '1';
                if (summaryArea) summaryArea.classList.remove('hidden');
                break;
            case 'error':
            case 'cancelled':
                if (startBtn) startBtn.disabled = false;
                if (cancelBtn) cancelBtn.classList.add('hidden');
                if (selectionArea) selectionArea.style.opacity = '1';
                break;
        }
    },

    showSummary(stats) {
        const summaryArea = document.getElementById('summary-area');
        if (!summaryArea) return;

        document.getElementById('summary-notebooks').textContent = stats.notebooks_exported || 0;
        document.getElementById('summary-sections').textContent = stats.sections_exported || 0;
        document.getElementById('summary-pages').textContent = stats.pages_exported || 0;
        document.getElementById('summary-images').textContent = stats.images_downloaded || 0;
        document.getElementById('summary-errors').textContent = stats.errors || 0;

        summaryArea.classList.remove('hidden');
    },

    cancel() {
        if (this.eventSource) {
            this.eventSource.close();
        }
        
        this.isExporting = false;
        this.addLogEntry('Export cancelled by user', 'cancelled');
        this.updateUI('cancelled');

        // TODO: Call cancel endpoint if implemented
    }
};

// Settings manager
const settingsManager = {
    async save(event) {
        event.preventDefault();
        
        const form = event.target;
        const messageEl = document.getElementById('settings-message');
        const submitBtn = form.querySelector('button[type="submit"]');
        
        const data = {
            client_id: form.client_id.value.trim(),
            client_secret: form.client_secret.value.trim(),
            export_directory: form.export_directory.value.trim()
        };

        if (!data.client_id) {
            utils.showMessage(messageEl, 'Client ID is required', 'error');
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving...';

        try {
            const result = await api.post('/api/settings', data);
            
            if (result.success) {
                utils.showMessage(messageEl, 'Settings saved successfully!', 'success');
            } else {
                throw new Error(result.error || 'Failed to save settings');
            }
        } catch (error) {
            utils.showMessage(messageEl, error.message, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save Settings';
        }
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize export manager on export page
    exportManager.init();
    
    // Initialize notebook browser on browse page
    if (document.getElementById('notebooks-container')) {
        notebookBrowser.load();
    }
    
    // Initialize settings form
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        settingsForm.addEventListener('submit', (e) => settingsManager.save(e));
    }
});

// Export utilities globally for inline handlers
window.notebookBrowser = notebookBrowser;
window.exportManager = exportManager;
window.utils = utils;
