/**
 * Store Management JavaScript Module
 *
 * Provides AJAX functionality for store management operations including:
 * - Loading stores
 * - Creating/updating stores
 * - Deleting stores
 * - Switching between stores
 * - Managing store members
 */

// CSRF Token Helper
function getCSRFToken() {
    // First try to get from the hidden input (Django template tag)
    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (csrfInput) {
        return csrfInput.value;
    }

    // Then try to get from cookie
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return decodeURIComponent(value);
        }
    }

    return null;
}

/**
 * Get cookie value by name
 */
function getCookie(name) {
    const cookieValue = document.cookie.match('(^|;)\\s*' + name + '=([^;]*)');
    return cookieValue ? decodeURIComponent(cookieValue[2]) : null;
}

/**
 * Show notification message (uses global showNotification if available)
 */
function notify(message, type = 'info') {
    if (typeof showNotification === 'function') {
        showNotification(message, type);
    } else {
        console.log(`[${type.toUpperCase()}] ${message}`);
    }
}

/**
 * Store API Client
 */
const StoreAPI = {
    /**
     * Get all stores for the current user
     */
    async getStores() {
        const response = await fetch('/api/v1/stores/', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
        });
        return response.json();
    },

    /**
     * Get a single store by ID
     */
    async getStore(storeId) {
        const response = await fetch(`/api/v1/stores/${storeId}/`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
        });
        return response.json();
    },

    /**
     * Create a new store
     */
    async createStore(data) {
        const response = await fetch('/api/v1/stores/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify(data),
        });
        return {
            ok: response.ok,
            data: await response.json(),
            status: response.status,
        };
    },

    /**
     * Update an existing store
     */
    async updateStore(storeId, data) {
        const response = await fetch(`/api/v1/stores/${storeId}/`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify(data),
        });
        return {
            ok: response.ok,
            data: await response.json(),
            status: response.status,
        };
    },

    /**
     * Delete a store
     */
    async deleteStore(storeId) {
        const response = await fetch(`/api/v1/stores/${storeId}/`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
        });
        return {
            ok: response.ok,
            status: response.status,
        };
    },

    /**
     * Switch to a different store
     */
    async switchStore(storeId) {
        const response = await fetch(`/api/v1/stores/${storeId}/switch/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
        });
        return {
            ok: response.ok,
            data: await response.json(),
        };
    },

    /**
     * Add a member to the store
     */
    async addMember(storeId, userId, role) {
        const response = await fetch(`/api/v1/stores/${storeId}/staff/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                action: 'add',
                user_id: userId,
                role: role,
            }),
        });
        return {
            ok: response.ok,
            data: await response.json(),
        };
    },

    /**
     * Remove a member from the store
     */
    async removeMember(storeId, userId, role) {
        const response = await fetch(`/api/v1/stores/${storeId}/staff/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                action: 'remove',
                user_id: userId,
                role: role,
            }),
        });
        return {
            ok: response.ok,
            data: await response.json(),
        };
    },
};

/**
 * Store Management Functions
 */
const StoreManager = {
    /**
     * Load and display stores in a table/list
     */
    async loadStores(containerId = 'storesTable') {
        try {
            const stores = await StoreAPI.getStores();
            const container = document.getElementById(containerId);

            if (!container) {
                console.warn(`Container with id "${containerId}" not found`);
                return stores;
            }

            // Trigger custom event for stores loaded
            document.dispatchEvent(new CustomEvent('stores:loaded', { detail: stores }));

            return stores;
        } catch (error) {
            console.error('Error loading stores:', error);
            notify('Failed to load stores', 'error');
            return [];
        }
    },

    /**
     * Create a new store
     */
    async createStore(data, redirectTo = '/dashboard/') {
        try {
            const result = await StoreAPI.createStore(data);

            if (result.ok) {
                notify('Store created successfully!', 'success');
                setTimeout(() => {
                    window.location.href = redirectTo;
                }, 1000);
            } else {
                let errorMessage = 'Failed to create store.';
                if (result.data.name) {
                    errorMessage += ' ' + result.data.name[0];
                } else if (result.data.detail) {
                    errorMessage += ' ' + result.data.detail;
                } else if (result.data.error) {
                    errorMessage += ' ' + result.data.error;
                }
                notify(errorMessage, 'error');
            }

            return result;
        } catch (error) {
            console.error('Error creating store:', error);
            notify('An error occurred. Please try again.', 'error');
            return { ok: false };
        }
    },

    /**
     * Update a store
     */
    async updateStore(storeId, data, redirectUrl = null) {
        try {
            const result = await StoreAPI.updateStore(storeId, data);

            if (result.ok) {
                notify('Store updated successfully!', 'success');
                if (redirectUrl) {
                    setTimeout(() => {
                        window.location.href = redirectUrl;
                    }, 1000);
                }
            } else {
                let errorMessage = 'Failed to update store.';
                if (result.data.name) {
                    errorMessage += ' ' + result.data.name[0];
                } else if (result.data.detail) {
                    errorMessage += ' ' + result.data.detail;
                } else if (result.data.error) {
                    errorMessage += ' ' + result.data.error;
                }
                notify(errorMessage, 'error');
            }

            return result;
        } catch (error) {
            console.error('Error updating store:', error);
            notify('An error occurred. Please try again.', 'error');
            return { ok: false };
        }
    },

    /**
     * Delete a store with confirmation
     */
    async deleteStore(storeId, storeName) {
        if (!confirm(`Are you sure you want to delete "${storeName}"? This action cannot be undone.`)) {
            return;
        }

        try {
            const result = await StoreAPI.deleteStore(storeId);

            if (result.ok) {
                notify(`"${storeName}" has been deleted`, 'success');
                // Trigger custom event for store deleted
                document.dispatchEvent(new CustomEvent('store:deleted', { detail: { storeId } }));
                // Reload page after short delay
                setTimeout(() => location.reload(), 1000);
            } else {
                notify('Failed to delete store', 'error');
            }

            return result;
        } catch (error) {
            console.error('Error deleting store:', error);
            notify('An error occurred while deleting the store', 'error');
            return { ok: false };
        }
    },

    /**
     * Switch to a different store
     */
    async switchStore(storeId, storeName) {
        try {
            const result = await StoreAPI.switchStore(storeId);

            if (result.ok) {
                notify(`Switched to ${storeName}`, 'success');
                // Trigger custom event for store switched
                document.dispatchEvent(new CustomEvent('store:switched', { detail: { storeId, storeName } }));
                setTimeout(() => location.reload(), 500);
            } else {
                notify('Failed to switch store', 'error');
            }

            return result;
        } catch (error) {
            console.error('Error switching store:', error);
            notify('An error occurred while switching stores', 'error');
            return { ok: false };
        }
    },

    /**
     * Add a member to the store
     */
    async addMember(storeId, userId, role) {
        try {
            const result = await StoreAPI.addMember(storeId, userId, role);

            if (result.ok) {
                notify(result.data.message || 'Member added successfully', 'success');
                // Trigger custom event
                document.dispatchEvent(new CustomEvent('store:memberAdded', { detail: { storeId, userId, role } }));
            } else {
                notify(result.data.error || 'Failed to add member', 'error');
            }

            return result;
        } catch (error) {
            console.error('Error adding member:', error);
            notify('An error occurred while adding the member', 'error');
            return { ok: false };
        }
    },

    /**
     * Remove a member from the store
     */
    async removeMember(storeId, userId, role) {
        if (!confirm('Are you sure you want to remove this member?')) {
            return;
        }

        try {
            const result = await StoreAPI.removeMember(storeId, userId, role);

            if (result.ok) {
                notify(result.data.message || 'Member removed successfully', 'success');
                // Trigger custom event
                document.dispatchEvent(new CustomEvent('store:memberRemoved', { detail: { storeId, userId, role } }));
            } else {
                notify(result.data.error || 'Failed to remove member', 'error');
            }

            return result;
        } catch (error) {
            console.error('Error removing member:', error);
            notify('An error occurred while removing the member', 'error');
            return { ok: false };
        }
    },
};

/**
 * Form Handler for Store Operations
 */
const StoreFormHandler = {
    /**
     * Initialize create store form
     */
    initCreateForm(formId = 'createStoreForm') {
        const form = document.getElementById(formId);
        if (!form) return;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;

            // Set loading state
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';

            // Get form data
            const name = form.querySelector('[name="name"]').value;
            const description = form.querySelector('[name="description"]').value;

            const data = {
                name: name,
                description: description || ''
            };

            const result = await StoreManager.createStore(data);

            if (!result.ok) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        });
    },

    /**
     * Initialize edit store form
     */
    initEditForm(formId = 'editStoreForm') {
        const form = document.getElementById(formId);
        if (!form) return;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const submitBtn = form.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;

            // Set loading state
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

            // Get form data
            const storeId = form.querySelector('[name="storeId"]').value;
            const name = form.querySelector('[name="name"]').value;
            const description = form.querySelector('[name="description"]').value;
            const status = form.querySelector('[name="status"]').value;

            const data = {
                name: name,
                description: description || '',
                status: status
            };

            const redirectUrl = form.getAttribute('data-redirect') || null;
            const result = await StoreManager.updateStore(storeId, data, redirectUrl);

            if (!result.ok) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        });
    },
};

/**
 * Search and Filter for Store Lists
 */
const StoreSearch = {
    init(searchInputId = 'searchStores', statusFilterId = 'filterStatus', tableId = 'storesTable') {
        const searchInput = document.getElementById(searchInputId);
        const statusFilter = document.getElementById(statusFilterId);
        const table = document.getElementById(tableId);

        if (!table) return;

        const storeRows = table.querySelectorAll('.store-row') || [];

        function filterStores() {
            const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
            const statusValue = statusFilter ? statusFilter.value : '';

            storeRows.forEach(row => {
                const storeName = row.getAttribute('data-store-name') || '';
                const storeStatus = row.getAttribute('data-store-status') || '';

                const matchesSearch = storeName.includes(searchTerm);
                const matchesStatus = !statusValue || storeStatus === statusValue;

                row.style.display = (matchesSearch && matchesStatus) ? '' : 'none';
            });
        }

        if (searchInput) {
            searchInput.addEventListener('input', filterStores);
        }

        if (statusFilter) {
            statusFilter.addEventListener('change', filterStores);
        }
    },
};

/**
 * Auto-initialize when DOM is ready
 */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize forms
    StoreFormHandler.initCreateForm();
    StoreFormHandler.initEditForm();

    // Initialize search/filter
    StoreSearch.init();
});

// Export for use in templates
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { StoreAPI, StoreManager, StoreFormHandler, StoreSearch };
}
