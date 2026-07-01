/**
 * Member List JavaScript
 * Handles member activation, deactivation, and role management
 */

const MemberList = (function() {
    let storeId = null;
    let filters = {
        search: '',
        role: '',
        status: ''
    };

    function init(storeIdParam) {
        storeId = storeIdParam;
        setupEventListeners();
        initializeFromURL();
    }

    function setupEventListeners() {
        // Search functionality
        const searchInput = document.querySelector('input[name="q"]');
        if (searchInput) {
            searchInput.addEventListener('input', debounce(handleSearch, 300));
        }

        // Role filter
        const roleSelect = document.querySelector('select[name="role"]');
        if (roleSelect) {
            roleSelect.addEventListener('change', function() {
                filters.role = this.value;
                applyFilters();
            });
        }

        // Status filter
        const statusSelect = document.querySelector('select[name="status"]');
        if (statusSelect) {
            statusSelect.addEventListener('change', function() {
                filters.status = this.value;
                applyFilters();
            });
        }

        // Deactivate buttons
        document.querySelectorAll('[data-action="deactivate-member"]').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const membershipId = this.dataset.membershipId;
                const memberName = this.dataset.memberName;
                confirmDeactivateMember(membershipId, memberName);
            });
        });

        // Reactivate buttons
        document.querySelectorAll('[data-action="reactivate-member"]').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const membershipId = this.dataset.membershipId;
                const memberName = this.dataset.memberName;
                confirmReactivateMember(membershipId, memberName);
            });
        });

        // Role change dropdowns
        document.querySelectorAll('[data-action="change-role"]').forEach(select => {
            select.addEventListener('change', function() {
                const membershipId = this.dataset.membershipId;
                const newRoleId = this.value;
                const oldRoleId = this.dataset.originalRole;
                changeMemberRole(membershipId, newRoleId, oldRoleId);
            });
        });
    }

    function initializeFromURL() {
        // Initialize filters from URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        
        filters.search = urlParams.get('q') || '';
        filters.role = urlParams.get('role') || '';
        filters.status = urlParams.get('status') || '';

        // Set input values
        const searchInput = document.querySelector('input[name="q"]');
        const roleSelect = document.querySelector('select[name="role"]');
        const statusSelect = document.querySelector('select[name="status"]');

        if (searchInput) searchInput.value = filters.search;
        if (roleSelect) roleSelect.value = filters.role;
        if (statusSelect) statusSelect.value = filters.status;

        // Store current values for change tracking
        document.querySelectorAll('[data-action="change-role"]').forEach(select => {
            const selectedOption = select.options[select.selectedIndex];
            select.dataset.originalRole = selectedOption ? selectedOption.value : '';
        });
    }

    function handleSearch() {
        filters.search = this.value;
        applyFilters();
    }

    function applyFilters() {
        const searchLower = filters.search.toLowerCase();
        const selectedRole = filters.role;
        const selectedStatus = filters.status;

        document.querySelectorAll('[data-membership-id]').forEach(row => {
            const memberName = row.dataset.memberName ? row.dataset.memberName.toLowerCase() : '';
            const memberRole = row.dataset.memberRole ? row.dataset.memberRole.toLowerCase() : '';
            const memberStatus = row.dataset.memberStatus ? row.dataset.memberStatus.toLowerCase() : '';

            const matchesSearch = !searchLower || memberName.includes(searchLower);
            const matchesRole = !selectedRole || memberRole === selectedRole;
            const matchesStatus = !selectedStatus || memberStatus === selectedStatus || 
                                  (selectedStatus === 'all' && (memberStatus === 'active' || memberStatus === 'inactive'));

            if (matchesSearch && matchesRole && matchesStatus) {
                row.style.display = '';
                row.classList.remove('d-none');
            } else {
                row.style.display = 'none';
                row.classList.add('d-none');
            }
        });

        updateTableVisibility();
    }

    function updateTableVisibility() {
        const table = document.querySelector('[data-component="member-table"]');
        if (!table) return;

        const visibleRows = table.querySelectorAll('tbody tr:not(.d-none)');
        const emptyState = document.querySelector('.card .empty-state');

        if (table) {
            if (visibleRows.length === 0) {
                // Show empty state if all rows are hidden
                if (emptyState) {
                    table.closest('.card').style.display = 'none';
                    emptyState.style.display = 'block';
                }
            } else {
                table.closest('.card').style.display = '';
                if (emptyState) {
                    emptyState.style.display = 'none';
                }
            }
        }
    }

    function confirmDeactivateMember(membershipId, memberName) {
        if (confirm(`Are you sure you want to deactivate ${memberName}? They will lose access to this store.`)) {
            const btn = document.querySelector(`[data-membership-id="${membershipId}"][data-action="deactivate-member"]`);
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deactivating...';
            }

            deactivateMember(membershipId)
                .then(() => {
                    updateMemberUI(membershipId, 'deactivated');
                    showNotification(`${memberName} has been deactivated`, 'success');
                })
                .catch(error => {
                    showNotification(`Error deactivating ${memberName}: ${error.message || 'Unknown error'}`, 'error');
                })
                .finally(() => {
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-person-x"></i> Deactivate';
                    }
                });
        }
    }

    function confirmReactivateMember(membershipId, memberName) {
        if (confirm(`Are you sure you want to reactivate ${memberName}? They will regain access to this store.`)) {
            const btn = document.querySelector(`[data-membership-id="${membershipId}"][data-action="reactivate-member"]`);
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Reactivating...';
            }

            activateMember(membershipId)
                .then(() => {
                    updateMemberUI(membershipId, 'reactivated');
                    showNotification(`${memberName} has been reactivated`, 'success');
                })
                .catch(error => {
                    // If the server indicates a plan upgrade is required
                    // (seat-cap block), surface the upgrade CTA inline so
                    // the user has an obvious next step.
                    if (error.upgrade_required) {
                        showNotification(
                            `${error.message || 'Seat limit reached.'} ` +
                            `<a href="/subscriptions/manage/" class="alert-link ms-2">Upgrade plan</a>`,
                            'warning'
                        );
                    } else {
                        showNotification(`Error reactivating ${memberName}: ${error.message || 'Unknown error'}`, 'error');
                    }
                })
                .finally(() => {
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-person-check"></i> Reactivate';
                    }
                });
        }
    }

    function changeMemberRole(membershipId, newRoleId, oldRoleId) {
        const btn = document.querySelector(`[data-membership-id="${membershipId}"][data-action="change-role"]`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Updating...';
        }

        updateRole(membershipId, newRoleId, oldRoleId)
            .then(() => {
                // Update button state
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-check"></i> Updated';
                    btn.classList.remove('btn-outline-secondary');
                    btn.classList.add('btn-success');
                    
                    // Show updated state briefly
                    setTimeout(() => {
                        btn.innerHTML = '<i class="bi bi-pencil"></i> Change';
                        btn.classList.remove('btn-success');
                        btn.classList.add('btn-outline-secondary');
                    }, 2000);
                }
                showNotification('Member role updated successfully', 'success');
            })
            .catch(error => {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-pencil"></i> Change';
                    
                    // Reset to old role
                    if (oldRoleId) {
                        btn.value = oldRoleId;
                    }
                }
                showNotification(`Error updating role: ${error.message || 'Unknown error'}`, 'error');
            });
    }

    function deactivateMember(membershipId) {
        return fetch(`/settings/team/${storeId}/deactivate/${membershipId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || 'Request failed');
                });
            }
            return response.json();
        });
    }

    function activateMember(membershipId) {
        return fetch(`/settings/team/${storeId}/activate/${membershipId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    // Preserve the full payload (including
                    // ``upgrade_required``) on the thrown Error so the
                    // caller can branch on it without losing context.
                    const err = new Error(data.error || 'Request failed');
                    Object.assign(err, data);
                    throw err;
                });
            }
            return response.json();
        });
    }

    function updateRole(membershipId, newRoleId, oldRoleId) {
        const formData = new FormData();
        formData.append('role', newRoleId);
        formData.append('membership_id', membershipId);
        formData.append('csrfmiddlewaretoken', getCsrfToken());

        return fetch(`/settings/team/${storeId}/change-role/${membershipId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams(formData).toString()
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || 'Request failed');
                });
            }
            return response.json();
        });
    }

    function updateMemberUI(membershipId, action) {
        const row = document.querySelector(`[data-membership-id="${membershipId}"]`);
        if (!row) return;

        const statusCell = row.querySelector('td:nth-child(5)');
        const actionsCell = row.querySelector('td:nth-child(6)');

        if (action === 'deactivated') {
            row.classList.add('text-muted');
            if (statusCell) {
                statusCell.innerHTML = '<span class="badge bg-secondary">Inactive</span>';
            }
            if (actionsCell) {
                const deactivateBtn = actionsCell.querySelector('[data-action="deactivate-member"]');
                const reactivateBtn = actionsCell.querySelector('[data-action="reactivate-member"]');
                if (deactivateBtn) deactivateBtn.style.display = 'none';
                if (reactivateBtn) reactivateBtn.style.display = '';
            }
        } else if (action === 'reactivated') {
            row.classList.remove('text-muted');
            if (statusCell) {
                statusCell.innerHTML = '<span class="badge bg-success-subtle text-success-emphasis">Active</span>';
            }
            if (actionsCell) {
                const deactivateBtn = actionsCell.querySelector('[data-action="deactivate-member"]');
                const reactivateBtn = actionsCell.querySelector('[data-action="reactivate-member"]');
                if (deactivateBtn) deactivateBtn.style.display = '';
                if (reactivateBtn) reactivateBtn.style.display = 'none';
            }
        }
    }

    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
               getCookie('csrftoken');
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function showNotification(message, type = 'info') {
        const container = document.getElementById('notificationContainer') || createNotificationContainer();
        const notification = document.createElement('div');
        
        notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show`;
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        container.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }

    function createNotificationContainer() {
        const container = document.createElement('div');
        container.id = 'notificationContainer';
        container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 400px;';
        document.body.appendChild(container);
        return container;
    }

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

    return {
        init: init,
        refreshMembers: applyFilters,
        getStoreId: () => storeId
    };
})();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    const storeElement = document.querySelector('[data-store-id]');
    if (storeElement) {
        const storeId = storeElement.dataset.storeId;
        if (storeId) {
            MemberList.init(storeId);
        }
    }
});