// ========================================
// DASHBOARD JAVASCRIPT
// Enhanced Dashboard Functionality
// ========================================

document.addEventListener('DOMContentLoaded', function() {
    // ========================================
    // SIDEBAR FUNCTIONALITY
    // ========================================
    
    // State variables
    let isSidebarOpen = window.innerWidth > 991;
    
    // DOM Elements
    const sidebar = document.querySelector('.sidebar');
    const sidebarToggle = document.querySelector('[data-sidebar-toggle]');
    const sidebarOverlay = document.querySelector('.sidebar-overlay');
    const dashboardPage = document.querySelector('.dashboard-page') || document.body;
    
    // Sidebar Overlay functionality
    function closeSidebar() {
        if (window.innerWidth < 992) {
            isSidebarOpen = false;
            updateSidebarState();
        }
    }
    
    // Initialize sidebar state
    function initializeSidebar() {
        isSidebarOpen = window.innerWidth > 991;
        updateSidebarState();
    }
    
    // Update sidebar state
    function updateSidebarState() {
        if (sidebar && dashboardPage) {
            if (window.innerWidth < 992) {
                // Mobile: controlled by state
                if (isSidebarOpen) {
                    sidebar.style.transform = 'translateX(0)';
                    dashboardPage.classList.add('sidebar-open');
                    if (sidebarOverlay) {
                        sidebarOverlay.style.display = 'block';
                    }
                } else {
                    sidebar.style.transform = 'translateX(-100%)';
                    dashboardPage.classList.remove('sidebar-open');
                    if (sidebarOverlay) {
                        sidebarOverlay.style.display = 'none';
                    }
                }
            } else {
                // Desktop: sidebar always visible, no overlay
                sidebar.style.transform = 'translateX(0)';
                dashboardPage.classList.remove('sidebar-open');
                if (sidebarOverlay) {
                    sidebarOverlay.style.display = 'none';
                }
            }
        }
    }
    
    // Toggle sidebar function
    function toggleSidebar(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        
        isSidebarOpen = !isSidebarOpen;
        updateSidebarState();
        
        return false;
    }
    
    // Set up toggle button
    if (sidebarToggle) {
        // Remove existing listeners to avoid duplicates
        sidebarToggle.replaceWith(sidebarToggle.cloneNode(true));
        const newToggle = document.querySelector('[data-sidebar-toggle]');
        
        if (newToggle) {
            newToggle.addEventListener('click', toggleSidebar);
        }
    }
    
    // Set up overlay click handler
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeSidebar);
    }
    
    // Handle window resize
    let resizeTimeout;
    window.addEventListener('resize', function() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(function() {
            const newIsOpen = window.innerWidth > 991;
            if (newIsOpen !== isSidebarOpen) {
                isSidebarOpen = newIsOpen;
                updateSidebarState();
            }
        }, 250);
    });
    
    // Handle escape key to close sidebar on mobile
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && isSidebarOpen && window.innerWidth < 992) {
            closeSidebar();
        }
    });
    
    // Initialize on page load
    initializeSidebar();
    
    // ========================================
    // DROPDOWN FUNCTIONALITY
    // ========================================

    // Bootstrap 5 automatically handles dropdowns via data-bs-toggle="dropdown"
    // No manual initialization needed - it's handled by Bootstrap's data API
    // Just ensure dropdown menus have proper z-index and positioning
    
    // ========================================
    // NOTIFICATION FUNCTIONALITY
    // ========================================
    
    // Auto-dismiss notification badges
    function updateNotificationBadge() {
        fetch('/api/v1/notifications/unseen-count/')
            .then(response => response.json())
            .then(data => {
                const badge = document.querySelector('.notification-badge');
                if (badge && data.count > 0) {
                    badge.textContent = data.count > 9 ? '9+' : data.count;
                    badge.classList.remove('d-none');
                } else if (badge) {
                    badge.classList.add('d-none');
                }
            })
            .catch(error => console.error('Error fetching notifications:', error));
    }
    
    // Update notification count every 30 seconds
    if (document.querySelector('.notification-badge')) {
        updateNotificationBadge();
        setInterval(updateNotificationBadge, 30000);
    }
    
    // ========================================
    // SEARCH FUNCTIONALITY
    // ========================================
    
    // Search input handling
    const searchInput = document.querySelector('[data-search]');
    const searchResults = document.querySelector('[data-search-results]');
    
    if (searchInput) {
        let searchTimeout;
        
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            const query = this.value.trim();
            
            if (query.length >= 2) {
                searchTimeout = setTimeout(function() {
                    performSearch(query);
                }, 300);
            } else {
                if (searchResults) {
                    searchResults.innerHTML = '';
                    searchResults.classList.add('d-none');
                }
            }
        });
    }
    
    function performSearch(query) {
        if (!query) return;
        
        fetch(`/api/v1/search/?q=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                if (searchResults) {
                    if (data.results && data.results.length > 0) {
                        searchResults.innerHTML = renderSearchResults(data.results);
                        searchResults.classList.remove('d-none');
                    } else {
                        searchResults.innerHTML = '<div class="p-3 text-muted">No results found</div>';
                        searchResults.classList.remove('d-none');
                    }
                }
            })
            .catch(error => {
                console.error('Search error:', error);
            });
    }
    
    function renderSearchResults(results) {
        if (!results || results.length === 0) {
            return '<div class="p-3 text-muted">No results found</div>';
        }

        return results.map(result => {
            const icon = result.icon || 'search';
            const title = result.title || 'Unknown';
            const description = result.description || '';
            const url = result.url || '#';

            return `
                <a href="${url}" class="dropdown-item d-flex align-items-center py-2">
                    <i class="bi bi-${icon} me-2 text-muted"></i>
                    <div>
                        <div class="fw-bold">${title}</div>
                        <small class="text-muted">${description}</small>
                    </div>
                </a>
            `;
        }).join('');
    }

    // ========================================
    // MOBILE SEARCH PANEL FUNCTIONALITY
    // ========================================

    const mobileSearchToggle = document.querySelector('[data-mobile-search-toggle]');
    const mobileSearchClose = document.querySelector('[data-mobile-search-close]');
    const mobileSearchPanel = document.querySelector('.navbar-search-mobile-panel');

    // Toggle mobile search panel
    function toggleMobileSearch(show) {
        if (mobileSearchPanel) {
            if (show) {
                mobileSearchPanel.classList.add('show');
                // Focus on search input when opened
                const searchInput = mobileSearchPanel.querySelector('input');
                if (searchInput) {
                    setTimeout(() => searchInput.focus(), 300);
                }
            } else {
                mobileSearchPanel.classList.remove('show');
            }
        }
    }

    // Set up mobile search toggle button
    if (mobileSearchToggle) {
        mobileSearchToggle.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            toggleMobileSearch(true);
        });
    }

    // Set up mobile search close button
    if (mobileSearchClose) {
        mobileSearchClose.addEventListener('click', function(e) {
            e.preventDefault();
            toggleMobileSearch(false);
        });
    }

    // Close mobile search when clicking outside
    document.addEventListener('click', function(e) {
        if (mobileSearchPanel && mobileSearchPanel.classList.contains('show')) {
            if (!mobileSearchPanel.contains(e.target) && !mobileSearchToggle?.contains(e.target)) {
                toggleMobileSearch(false);
            }
        }
    });

    // Close mobile search on escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && mobileSearchPanel && mobileSearchPanel.classList.contains('show')) {
            toggleMobileSearch(false);
        }
    });

    // ========================================
    // STORE SWITCHING FUNCTIONALITY
    // ========================================
    
    // Store selector with confirmation
    const storeSwitchButtons = document.querySelectorAll('[data-store-switch]');
    if (storeSwitchButtons.length > 0) {
        storeSwitchButtons.forEach(function(button) {
            button.addEventListener('click', async function(e) {
                e.preventDefault();
                const storeId = this.dataset.storeSwitch;
                const storeName = this.dataset.storeName;
                if (!storeId || !storeName) return;

                const ok = await window.confirmAction({
                    title: 'Switch store?',
                    message: `Switch to store "${storeName}"? This will change your active store context.`,
                    confirmText: 'Switch',
                    confirmClass: 'btn-primary',
                });
                if (!ok) return;

                // Show loading state
                this.disabled = true;
                const originalLabel = storeName;
                this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

                try {
                    const response = await fetch(`/dashboard/switch-store/${storeId}/`, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': getCsrfToken()
                        }
                    });
                    const data = await response.json();
                    if (data.success) {
                        window.location.reload();
                    } else {
                        showNotification(data.message || 'Failed to switch store', 'error');
                        this.disabled = false;
                        this.innerHTML = originalLabel;
                    }
                } catch (error) {
                    console.error('Store switch error:', error);
                    showNotification('An error occurred while switching stores', 'error');
                    this.disabled = false;
                    this.innerHTML = originalLabel;
                }
            });
        });
    }
    
    // ========================================
    // AJAX HELPERS
    // ========================================
    
    function getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.startsWith('csrftoken=')) {
                return cookie.substring('csrftoken='.length);
            }
        }
        return '';
    }
    
    // ========================================
    // RESPONSIVE SIDEBAR HANDLING
    // ========================================
    
    
    // This function is now integrated into initializeSidebar()
    
    // Initialize on page load
    initializeSidebar();
    
    // Listen for Alpine.js state changes
    document.addEventListener('sidebar-state-changed', function(event) {
        if (event.detail && typeof event.detail.isOpen !== 'undefined') {
            isSidebarOpen = event.detail.isOpen;
            updateSidebarState();
        }
    });
    
    // ========================================
    // LOADING STATES
    // ========================================
    
    // Add loading state to buttons
    const loadingButtons = document.querySelectorAll('[data-loading]');
    if (loadingButtons.length > 0) {
        loadingButtons.forEach(function(button) {
            if (button) {
                button.addEventListener('click', function() {
                    const originalText = this.innerHTML;
                    const loadingText = this.dataset.loading || 'Loading...';
                    
                    this.disabled = true;
                    this.innerHTML = `<span class="spinner-border spinner-border-sm" role="status"></span> ${loadingText}`;
                    
                    // Store original text for restoration
                    this.dataset.originalText = originalText;
                });
            }
        });
    }
    
    // Restore button states on page navigation
    window.addEventListener('pageshow', function(event) {
        if (event.persisted) {
            document.querySelectorAll('[data-loading]').forEach(function(button) {
                button.disabled = false;
                if (button.dataset.originalText) {
                    button.innerHTML = button.dataset.originalText;
                }
            });
        }
    });
    
    // ========================================
    // TOOLTIP AND POPOVER INITIALIZATION
    // ========================================
    
    // Initialize Bootstrap tooltips
    const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    if (tooltips.length > 0 && typeof bootstrap !== 'undefined') {
        tooltips.forEach(function(tooltip) {
            try {
                new bootstrap.Tooltip(tooltip);
            } catch (error) {
                console.warn('Failed to initialize tooltip:', error);
            }
        });
    }
    
    // Initialize Bootstrap popovers
    const popovers = document.querySelectorAll('[data-bs-toggle="popover"]');
    if (popovers.length > 0 && typeof bootstrap !== 'undefined') {
        popovers.forEach(function(popover) {
            try {
                new bootstrap.Popover(popover);
            } catch (error) {
                console.warn('Failed to initialize popover:', error);
            }
        });
    }
    
    // ========================================
    // FORM VALIDATION ENHANCEMENTS
    // ========================================
    
    // Enhanced form validation
    const validatedForms = document.querySelectorAll('form[data-validate]');
    if (validatedForms.length > 0) {
        validatedForms.forEach(function(form) {
            if (form) {
                form.addEventListener('submit', function(e) {
                    let isValid = true;
                    const requiredFields = form.querySelectorAll('[required]');
                    
                    requiredFields.forEach(function(field) {
                        if (field && !field.value.trim()) {
                            isValid = false;
                            field.classList.add('is-invalid');
                            
                            // Add error message if not exists
                            let feedback = field.nextElementSibling;
                            if (!feedback || !feedback.classList.contains('invalid-feedback')) {
                                feedback = document.createElement('div');
                                feedback.className = 'invalid-feedback';
                                field.parentNode.insertBefore(feedback, field.nextSibling);
                            }
                            feedback.textContent = 'This field is required';
                        } else if (field) {
                            field.classList.remove('is-invalid');
                            field.classList.add('is-valid');
                        }
                    });
                    
                    if (!isValid) {
                        e.preventDefault();
                        // Show first invalid field
                        const firstInvalid = form.querySelector('.is-invalid');
                        if (firstInvalid) {
                            firstInvalid.focus();
                        }
                    }
                });
            }
        });
    }
    
    // ========================================
    // KEYBOARD SHORTCUTS
    // ========================================
    
    // Global keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Cmd/Ctrl + K: Focus search
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            const searchInput = document.querySelector('input[type="search"], [data-search]');
            if (searchInput) {
                searchInput.focus();
            }
        }
        
        // Escape: Close modals and dropdowns
        if (e.key === 'Escape') {
            const modals = document.querySelectorAll('.modal.show');
            if (modals.length > 0 && typeof bootstrap !== 'undefined') {
                modals.forEach(function(modal) {
                    try {
                        const bootstrapModal = bootstrap.Modal.getInstance(modal);
                        if (bootstrapModal) {
                            bootstrapModal.hide();
                        }
                    } catch (error) {
                        console.warn('Failed to close modal:', error);
                    }
                });
            }
            
            const dropdownMenus = document.querySelectorAll('.dropdown-menu.show');
            if (dropdownMenus.length > 0) {
                dropdownMenus.forEach(function(menu) {
                    menu.classList.remove('show');
                });
            }
        }
    });
    
    // ========================================
    // PERFORMANCE OPTIMIZATIONS
    // ========================================
    
    // Lazy load images
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver(function(entries, observer) {
            entries.forEach(function(entry) {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.src = img.dataset.src;
                    img.classList.remove('lazy');
                    imageObserver.unobserve(img);
                }
            });
        });
        
        document.querySelectorAll('img[data-src]').forEach(function(img) {
            imageObserver.observe(img);
        });
    }
    
    // ========================================
    // UTILITY FUNCTIONS
    // ========================================
    
    // Debounce function
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    // Throttle function
    function throttle(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
    
    // Format currency
    function formatCurrency(amount, currency = 'USD') {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: currency
        }).format(amount);
    }
    
    // Format date
    function formatDate(date, options = {}) {
        const defaultOptions = {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        };
        return new Date(date).toLocaleDateString('en-US', { ...defaultOptions, ...options });
    }
    
    // Make functions available globally
    window.CRM = {
        debounce: debounce,
        throttle: throttle,
        formatCurrency: formatCurrency,
        formatDate: formatDate,
        getCsrfToken: getCsrfToken
    };
    
    console.log('Dashboard initialized successfully');
});