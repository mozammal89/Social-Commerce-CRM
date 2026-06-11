/**
 * Social Commerce CRM - Main JavaScript
 * Handles global functionality, HTMX extensions, and Alpine.js initialization
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Initialize popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });

    // Initialize all modals
    const modals = document.querySelectorAll('.modal');
    modals.forEach(function(modal) {
        modal.addEventListener('show.bs.modal', function() {
            // Get the modal body
            const modalBody = modal.querySelector('.modal-body');
            if (modalBody) {
                // Focus first input if exists
                const firstInput = modalBody.querySelector('input:not([type="hidden"]):not([readonly]), textarea:not([readonly])');
                if (firstInput) {
                    setTimeout(() => firstInput.focus(), 300);
                }
            }
        });
    });

    // Form validation
    const forms = document.querySelectorAll('.needs-validation');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // Sidebar toggle for mobile
    const sidebarToggle = document.getElementById('sidebarToggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function() {
            const sidebar = document.querySelector('.sidebar');
            const overlay = document.querySelector('.sidebar-overlay');
            
            if (sidebar && overlay) {
                sidebar.classList.toggle('show');
                overlay.style.display = sidebar.classList.contains('show') ? 'block' : 'none';
            }
        });
    }

    // Store switcher
    const storeSelector = document.getElementById('storeSelector');
    if (storeSelector) {
        storeSelector.addEventListener('change', function() {
            const storeId = this.value;
            if (storeId) {
                // Update the current store via AJAX
                fetch(`/api/v1/stores/${storeId}/switch/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    credentials: 'same-origin'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    }
                });
            }
        });
    }

    // Auto-dismiss messages
    const messages = document.querySelectorAll('.messages-container .alert');
    messages.forEach(function(message) {
        setTimeout(function() {
            message.classList.remove('show');
            setTimeout(function() {
                message.remove();
            }, 500);
        }, 5000);
    });

    // Confirm delete actions
    const deleteButtons = document.querySelectorAll('[data-confirm]');
    deleteButtons.forEach(function(button) {
        button.addEventListener('click', function(e) {
            const message = this.getAttribute('data-confirm') || 'Are you sure you want to continue?';
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });

    // Initialize Alpine.js components
    if (typeof Alpine !== 'undefined') {
        Alpine.start();
    }

    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });

    // HTMX event listeners
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        // Show loading indicator
        const target = evt.target.closest('[hx-target]') || evt.target;
        const indicator = document.createElement('div');
        indicator.className = 'htmx-indicator';
        indicator.innerHTML = '<span class="spinner-border spinner-border-sm text-primary" role="status"><span class="visually-hidden">Loading...</span></span>';
        indicator.style.position = 'absolute';
        indicator.style.top = '50%';
        indicator.style.left = '50%';
        indicator.style.transform = 'translate(-50%, -50%)';
        target.style.position = 'relative';
        target.appendChild(indicator);
        target.classList.add('htmx-request');
        target.dataset.htmxIndicator = indicator.outerHTML;
    });

    document.body.addEventListener('htmx:afterRequest', function(evt) {
        // Remove loading indicator
        const target = evt.target.closest('[hx-target]') || evt.target;
        const indicator = target.querySelector('.htmx-indicator');
        if (indicator) {
            indicator.remove();
            target.classList.remove('htmx-request');
        }
        target.removeAttribute('data-htmx-indicator');
    });

    document.body.addEventListener('htmx:responseError', function(evt) {
        // Handle HTMX errors
        console.error('HTMX error:', evt.detail);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'alert alert-danger';
        errorDiv.innerHTML = `<i class="bi bi-exclamation-triangle me-2"></i>An error occurred. Please try again.`;
        
        const messagesContainer = document.querySelector('.messages-container');
        if (messagesContainer) {
            messagesContainer.appendChild(errorDiv);
        }
    });

    // Search input debounce with HTMX
    const searchInputs = document.querySelectorAll('[data-search-url]');
    searchInputs.forEach(function(input) {
        let timeout;
        input.addEventListener('input', function() {
            clearTimeout(timeout);
            timeout = setTimeout(function() {
                const url = input.getAttribute('data-search-url');
                const query = input.value;
                if (query.length >= 2 || query.length === 0) {
                    const target = input.getAttribute('data-target');
                    fetch(`${url}?q=${encodeURIComponent(query)}`, {
                        headers: {
                            'HX-Request': 'true'
                        }
                    })
                    .then(response => response.text())
                    .then(html => {
                        document.querySelector(target).innerHTML = html;
                    });
                }
            }, 300);
        });
    });

    // Active navigation highlighting
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.sidebar .nav-link');
    navLinks.forEach(function(link) {
        const linkPath = new URL(link.href).pathname;
        if (linkPath === currentPath || (linkPath !== '/' && currentPath.startsWith(linkPath))) {
            link.classList.add('active');
        }
    });

    // Dynamic data attributes helpers
    window.addEventListener('htmx:afterSwap', function(evt) {
        // Re-initialize tooltips for new content
        const newTooltips = evt.detail.target.querySelectorAll('[data-bs-toggle="tooltip"]');
        newTooltips.forEach(function(tooltip) {
            new bootstrap.Tooltip(tooltip);
        });

        // Re-initialize popovers for new content
        const newPopovers = evt.detail.target.querySelectorAll('[data-bs-toggle="popover"]');
        newPopovers.forEach(function(popover) {
            new bootstrap.Popover(popover);
        });

        // Re-initialize modals for new content
        const newModals = evt.detail.target.querySelectorAll('.modal');
        newModals.forEach(function(modal) {
            new bootstrap.Modal(modal);
        });
    });
});

// Helper functions
function getCookie(name) {
    const cookieValue = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return cookieValue ? decodeURIComponent(cookieValue[2]) : null;
}

function showNotification(message, type = 'info') {
    const container = document.querySelector('.messages-container') || createMessagesContainer();
    
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    
    let icon = 'bi-info-circle';
    if (type === 'success') icon = 'bi-check-circle';
    if (type === 'error') icon = 'bi-exclamation-circle';
    if (type === 'warning') icon = 'bi-exclamation-triangle';
    
    alertDiv.innerHTML = `
        <i class="bi ${icon} me-2"></i>${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    container.appendChild(alertDiv);
    
    setTimeout(function() {
        alertDiv.classList.remove('show');
        setTimeout(function() {
            alertDiv.remove();
        }, 500);
    }, 5000);
}

function createMessagesContainer() {
    const container = document.createElement('div');
    container.className = 'messages-container position-fixed top-0 end-0 p-3';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
    return container;
}

function confirmDelete(message, callback) {
    if (confirm(message || 'Are you sure you want to delete this item?')) {
        if (typeof callback === 'function') {
            callback();
        }
        return true;
    }
    return false;
}

// Export for external use
window.showNotification = showNotification;
window.confirmDelete = confirmDelete;