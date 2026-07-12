/**
 * Support & Help Pages JavaScript
 *
 * Handles:
 * - FAQ search functionality
 * - File upload previews
 * - Form validation
 * - Dynamic UI interactions
 */

(function() {
    'use strict';

    // ===== Namespace =====
    const Support = {
        // Configuration
        config: {
            searchMinLength: 3,
            searchDebounce: 300,
            maxFileSize: 5 * 1024 * 1024, // 5MB
            allowedFileTypes: ['image/png', 'image/jpeg', 'image/jpg', 'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        },

        // State
        state: {
            searchTimeout: null,
            isSearching: false
        },

        // ===== Initialization =====
        init() {
            this.initSearch();
            this.initFileUploads();
            this.initForms();
            this.initExpanders();
        },

        // ===== FAQ Search =====
        initSearch() {
            const searchInput = document.getElementById('faqSearchInput');
            const searchResults = document.getElementById('searchResults');
            const searchSpinner = document.getElementById('searchSpinner');

            if (!searchInput || !searchResults) return;

            let searchTimeout;

            searchInput.addEventListener('input', (e) => {
                const query = e.target.value.trim();

                // Clear previous timeout
                clearTimeout(searchTimeout);

                // Hide results if query is too short
                if (query.length < this.config.searchMinLength) {
                    searchResults.classList.add('d-none');
                    return;
                }

                // Show spinner
                if (searchSpinner) {
                    searchSpinner.classList.remove('d-none');
                }

                // Debounce search
                searchTimeout = setTimeout(() => {
                    this.performSearch(query);
                }, this.config.searchDebounce);
            });

            // Hide results when clicking outside
            document.addEventListener('click', (e) => {
                if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                    searchResults.classList.add('d-none');
                }
            });

            // Handle keyboard navigation
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    searchResults.classList.add('d-none');
                    searchInput.blur();
                }
            });
        },

        async performSearch(query) {
            const searchResults = document.getElementById('searchResults');
            const searchSpinner = document.getElementById('searchSpinner');

            try {
                const response = await fetch('/help/faq/search/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': this.getCsrfToken()
                    },
                    body: new URLSearchParams({ q: query })
                });

                const data = await response.json();

                // Hide spinner
                if (searchSpinner) {
                    searchSpinner.classList.add('d-none');
                }

                // Render results
                this.renderSearchResults(data.results);

            } catch (error) {
                console.error('Search failed:', error);
                if (searchSpinner) {
                    searchSpinner.classList.add('d-none');
                }
            }
        },

        renderSearchResults(results) {
            const searchResults = document.getElementById('searchResults');

            if (!results || results.length === 0) {
                searchResults.innerHTML = `
                    <div class="p-3 text-center text-muted">
                        <i class="bi bi-search"></i>
                        <p class="mb-0 mt-2">No results found</p>
                    </div>
                `;
            } else {
                searchResults.innerHTML = results.map(result => `
                    <a href="${result.url}" class="search-result-item">
                        <div class="fw-semibold">${this.escapeHtml(result.title)}</div>
                        <div class="search-result-category">${this.escapeHtml(result.category)}</div>
                    </a>
                `).join('');
            }

            searchResults.classList.remove('d-none');
        },

        // ===== File Uploads =====
        initFileUploads() {
            // Create ticket file upload
            this.initFileUpload('fileUploadArea', 'fileUploadContent', 'filePreview');

            // Reply attachment upload
            this.initReplyAttachment();
        },

        initFileUpload(uploadAreaId, contentId, previewId) {
            const uploadArea = document.getElementById(uploadAreaId);
            const content = document.getElementById(contentId);
            const preview = document.getElementById(previewId);

            if (!uploadArea || !content || !preview) return;

            const fileInput = uploadArea.querySelector('input[type="file"]');
            if (!fileInput) return;

            // Click to upload
            uploadArea.addEventListener('click', () => fileInput.click());

            // Drag and drop
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('drag-over');
            });

            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('drag-over');
            });

            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('drag-over');

                const file = e.dataTransfer.files[0];
                if (file) {
                    this.handleFileSelect(file, fileInput, content, preview);
                }
            });

            // File selection
            fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (file) {
                    this.handleFileSelect(file, fileInput, content, preview);
                }
            });
        },

        initReplyAttachment() {
            const fileInput = document.getElementById('replyAttachment');
            const fileNameDisplay = document.getElementById('replyFileName');

            if (!fileInput || !fileNameDisplay) return;

            fileInput.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (file) {
                    if (file.size > this.config.maxFileSize) {
                        alert('File size exceeds 5MB limit. Please choose a smaller file.');
                        fileInput.value = '';
                        fileNameDisplay.textContent = '';
                        return;
                    }

                    if (!this.config.allowedFileTypes.includes(file.type)) {
                        alert('Invalid file type. Please upload PNG, JPG, PDF, or DOC files.');
                        fileInput.value = '';
                        fileNameDisplay.textContent = '';
                        return;
                    }

                    fileNameDisplay.textContent = file.name;
                }
            });
        },

        handleFileSelect(file, fileInput, content, preview) {
            // Validate file size
            if (file.size > this.config.maxFileSize) {
                alert('File size exceeds 5MB limit. Please choose a smaller file.');
                fileInput.value = '';
                return;
            }

            // Validate file type
            if (!this.config.allowedFileTypes.includes(file.type)) {
                alert('Invalid file type. Please upload PNG, JPG, PDF, or DOC files.');
                fileInput.value = '';
                return;
            }

            // Update UI
            content.classList.add('d-none');
            preview.classList.remove('d-none');

            const fileName = document.getElementById('previewFileName');
            const fileSize = document.getElementById('previewFileSize');
            const icon = document.getElementById('previewIcon');

            if (fileName) fileName.textContent = file.name;
            if (fileSize) fileSize.textContent = this.formatFileSize(file.size);

            if (icon) {
                icon.className = 'bi ' + this.getFileIcon(file.type);
            }

            // Setup remove button
            const removeBtn = document.getElementById('removeFile');
            if (removeBtn) {
                removeBtn.onclick = (e) => {
                    e.stopPropagation();
                    fileInput.value = '';
                    content.classList.remove('d-none');
                    preview.classList.add('d-none');
                };
            }
        },

        formatFileSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        },

        getFileIcon(mimeType) {
            const iconMap = {
                'image/png': 'bi-file-image',
                'image/jpeg': 'bi-file-image',
                'image/jpg': 'bi-file-image',
                'application/pdf': 'bi-file-pdf',
                'application/msword': 'bi-file-word',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'bi-file-word'
            };
            return iconMap[mimeType] || 'bi-file-earmark';
        },

        // ===== Form Validation =====
        initForms() {
            const ticketForm = document.getElementById('ticketForm');
            if (ticketForm) {
                this.initTicketFormValidation(ticketForm);
            }
        },

        initTicketFormValidation(form) {
            const subjectInput = form.querySelector('[name="subject"]');
            const descriptionInput = form.querySelector('[name="description"]');
            let subjectTimeout, descriptionTimeout;

            if (subjectInput) {
                subjectInput.addEventListener('input', () => {
                    clearTimeout(subjectTimeout);
                    subjectTimeout = setTimeout(() => {
                        const value = subjectInput.value.trim();
                        if (value.length > 0 && value.length < 10) {
                            this.showFieldError(subjectInput, 'Subject must be at least 10 characters long.');
                        } else {
                            this.clearFieldError(subjectInput);
                        }
                    }, 300);
                });
            }

            if (descriptionInput) {
                descriptionInput.addEventListener('input', () => {
                    clearTimeout(descriptionTimeout);
                    descriptionTimeout = setTimeout(() => {
                        const value = descriptionInput.value.trim();
                        if (value.length > 0 && value.length < 50) {
                            this.showFieldError(descriptionInput, 'Description must be at least 50 characters long.');
                        } else {
                            this.clearFieldError(descriptionInput);
                        }
                    }, 300);
                });
            }
        },

        showFieldError(input, message) {
            const container = input.closest('.mb-4') || input.closest('.form-group');
            if (!container) return;

            let errorDiv = container.querySelector('.invalid-feedback.d-block');
            if (!errorDiv) {
                errorDiv = document.createElement('div');
                errorDiv.className = 'invalid-feedback d-block';
                container.appendChild(errorDiv);
            }
            errorDiv.textContent = message;
            input.classList.add('is-invalid');
        },

        clearFieldError(input) {
            const container = input.closest('.mb-4') || input.closest('.form-group');
            if (!container) return;

            const errorDiv = container.querySelector('.invalid-feedback.d-block');
            if (errorDiv) {
                errorDiv.remove();
            }
            input.classList.remove('is-invalid');
        },

        // ===== Expanders/Accordions =====
        initExpanders() {
            // FAQ category expanders
            const expanders = document.querySelectorAll('[data-expand]');
            expanders.forEach(expander => {
                expander.addEventListener('click', (e) => {
                    e.preventDefault();
                    const target = document.querySelector(expander.dataset.expand);
                    if (target) {
                        target.classList.toggle('d-none');
                        const icon = expander.querySelector('.bi-chevron-down, .bi-chevron-up');
                        if (icon) {
                            icon.classList.toggle('bi-chevron-down');
                            icon.classList.toggle('bi-chevron-up');
                        }
                    }
                });
            });
        },

        // ===== Utility Functions =====
        getCsrfToken() {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
            return csrfToken ? csrfToken.value : '';
        },

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    };

    // ===== Initialize on DOM ready =====
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => Support.init());
    } else {
        Support.init();
    }

    // ===== Export for external use =====
    window.Support = Support;
})();
