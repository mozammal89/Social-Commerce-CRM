/**
 * Team Management Module
 * Handles member activation, deactivation, and role management
 */

const TeamManagement = (function() {
    let storeId = null;

    function init(storeIdParam) {
        storeId = storeIdParam;
        setupEventListeners();
    }

    function setupEventListeners() {
        const searchInput = document.getElementById('memberSearch');
        if (searchInput) {
            searchInput.addEventListener('input', debounce(filterMembers, 300));
        }

        const roleFilter = document.getElementById('roleFilter');
        if (roleFilter) {
            roleFilter.addEventListener('change', filterMembers);
        }

        const statusFilter = document.getElementById('statusFilter');
        if (statusFilter) {
            statusFilter.addEventListener('change', filterMembers);
        }

        const applyFiltersBtn = document.getElementById('applyFilters');
        if (applyFiltersBtn) {
            applyFiltersBtn.addEventListener('click', filterMembers);
        }

        document.querySelectorAll('.deactivate-member-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const membershipId = this.dataset.membershipId;
                deactivateMember(membershipId);
            });
        });

        document.querySelectorAll('.activate-member-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const membershipId = this.dataset.membershipId;
                activateMember(membershipId);
            });
        });

        document.querySelectorAll('.change-role-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const membershipId = this.dataset.membershipId;
                openChangeRoleModal(membershipId);
            });
        });

        document.querySelectorAll('.remove-member-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const membershipId = this.dataset.membershipId;
                confirmRemoveMember(membershipId);
            });
        });

        const inviteForm = document.getElementById('inviteMemberForm');
        if (inviteForm) {
            inviteForm.addEventListener('submit', handleInviteMember);
        }

        const changeRoleForm = document.getElementById('changeRoleForm');
        if (changeRoleForm) {
            changeRoleForm.addEventListener('submit', handleChangeRole);
        }
    }

    function filterMembers() {
        const searchTerm = document.getElementById('memberSearch')?.value.toLowerCase() || '';
        const roleFilter = document.getElementById('roleFilter')?.value || '';
        const statusFilter = document.getElementById('statusFilter')?.value || '';

        document.querySelectorAll('.member-row').forEach(row => {
            const name = row.dataset.name.toLowerCase();
            const role = row.dataset.role.toLowerCase();
            const status = row.dataset.status;

            const matchesSearch = name.includes(searchTerm);
            const matchesRole = !roleFilter || role.includes(roleFilter);
            const matchesStatus = !statusFilter || status === statusFilter;

            if (matchesSearch && matchesRole && matchesStatus) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });

        const visibleMembers = document.querySelectorAll('.member-row[style=""]');
        const noResults = document.querySelector('.no-members-message');
        if (noResults) {
            noResults.style.display = visibleMembers.length === 0 ? '' : 'none';
        }
    }

    function deactivateMember(membershipId) {
        if (confirm('Are you sure you want to deactivate this member? They will lose access to this store.')) {
            showLoading();

            fetch(`/settings/team/${storeId}/deactivate/${membershipId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification(data.message, 'success');
                    updateMemberStatus(membershipId, false);
                } else {
                    showNotification(data.error || 'Error deactivating member', 'error');
                }
            })
            .catch(error => {
                showNotification('Error deactivating member', 'error');
            })
            .finally(() => {
                hideLoading();
            });
        }
    }

    function activateMember(membershipId) {
        if (confirm('Are you sure you want to activate this member? They will regain access to this store.')) {
            showLoading();

            fetch(`/settings/team/${storeId}/activate/${membershipId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification(data.message, 'success');
                    updateMemberStatus(membershipId, true);
                } else {
                    showNotification(data.error || 'Error activating member', 'error');
                }
            })
            .catch(error => {
                showNotification('Error activating member', 'error');
            })
            .finally(() => {
                hideLoading();
            });
        }
    }

    function updateMemberStatus(membershipId, isActive) {
        const row = document.querySelector(`.member-row[data-membership-id="${membershipId}"]`);
        if (row) {
            const statusCell = row.querySelector('td:nth-child(3)');
            const actionCell = row.querySelector('td:nth-child(5)');
            
            if (isActive) {
                statusCell.innerHTML = '<span class="status-badge status-badge--active">Active</span>';
                row.dataset.status = 'active';
                
                // Update action button to deactivate
                const deactivateBtn = actionCell.querySelector('.deactivate-member-btn');
                if (deactivateBtn) {
                    deactivateBtn.style.display = '';
                }
                
                const activateBtn = actionCell.querySelector('.activate-member-btn');
                if (activateBtn) {
                    activateBtn.style.display = 'none';
                }
            } else {
                statusCell.innerHTML = '<span class="status-badge status-badge--inactive">Inactive</span>';
                row.dataset.status = 'inactive';
                
                // Update action button to activate
                const deactivateBtn = actionCell.querySelector('.deactivate-member-btn');
                if (deactivateBtn) {
                    deactivateBtn.style.display = 'none';
                }
                
                const activateBtn = actionCell.querySelector('.activate-member-btn');
                if (activateBtn) {
                    activateBtn.style.display = '';
                }
            }
            
            // Update row visibility for filters
            filterMembers();
        }
    }

    function openChangeRoleModal(membershipId) {
        const modal = document.getElementById('changeRoleModal');
        const membershipIdInput = document.getElementById('changeMembershipId');
        
        if (modal && membershipIdInput) {
            membershipIdInput.value = membershipId;
            
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }

    function handleChangeRole(e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);
        
        const membershipId = formData.get('membership_id');
        const newRole = formData.get('role');
        
        if (!newRole) {
            showNotification('Please select a role', 'error');
            return;
        }

        showLoading();

        fetch(`/settings/team/${storeId}/change-role/${membershipId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams(formData).toString()
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(data.message, 'success');
                bootstrap.Modal.getInstance(document.getElementById('changeRoleModal')).hide();
                location.reload(); // Reload to show updated roles
            } else {
                showNotification(data.error || 'Error changing role', 'error');
            }
        })
        .catch(error => {
            showNotification('Error changing role', 'error');
        })
        .finally(() => {
            hideLoading();
        });
    }

    function confirmRemoveMember(membershipId) {
        if (confirm('Are you sure you want to remove this member from the team? This action cannot be undone.')) {
            showLoading();

            fetch(`/settings/team/${storeId}/remove/${membershipId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken(),
                },
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification(data.message, 'success');
                    location.reload(); // Reload to show updated team list
                } else {
                    showNotification(data.error || 'Error removing member', 'error');
                }
            })
            .catch(error => {
                showNotification('Error removing member', 'error');
            })
            .finally(() => {
                hideLoading();
            });
        }
    }

    function handleInviteMember(e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);

        showLoading();

        fetch(`/settings/team/${storeId}/invite/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(data.message, 'success');
                bootstrap.Modal.getInstance(document.getElementById('inviteMemberModal')).hide();
                form.reset();
                location.reload();
            } else {
                showNotification(data.error || 'Error inviting member', 'error');
            }
        })
        .catch(error => {
            showNotification('Error inviting member', 'error');
        })
        .finally(() => {
            hideLoading();
        });
    }

    function showLoading() {
        const existingOverlay = document.querySelector('.loading-overlay');
        if (!existingOverlay) {
            const overlay = document.createElement('div');
            overlay.className = 'loading-overlay position-fixed top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center';
            overlay.style.cssText = 'background: rgba(0,0,0,0.5); z-index: 9999;';
            
            const spinner = document.createElement('div');
            spinner.className = 'spinner-border text-primary';
            spinner.style.cssText = 'width: 3rem; height: 3rem;';
            
            overlay.appendChild(spinner);
            document.body.appendChild(overlay);
        }
    }

    function hideLoading() {
        const overlay = document.querySelector('.loading-overlay');
        if (overlay) {
            overlay.remove();
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
        init: init
    };
})();

document.addEventListener('DOMContentLoaded', function() {
    const storeId = document.querySelector('[data-store-id]')?.dataset.storeId;
    if (storeId) {
        TeamManagement.init(storeId);
    }
});