/**
 * Team Management Module
 * Handles member activation, deactivation, role management, and AJAX filtering
 */

const TeamManagement = (function() {
    let storeId = null;
    let isLoading = false;
    let currentFilters = {
        search: '',
        role: '',
        status: ''
    };

    function init(storeIdParam) {
        storeId = storeIdParam;
        setupEventListeners();
        loadMembers(); // Initial load via AJAX
    }

    function setupEventListeners() {
        const searchInput = document.getElementById('memberSearch');
        if (searchInput) {
            searchInput.addEventListener('input', debounce(handleFilterChange, 300));
        }

        const roleFilter = document.getElementById('roleFilter');
        if (roleFilter) {
            roleFilter.addEventListener('change', handleFilterChange);
        }

        const statusFilter = document.getElementById('statusFilter');
        if (statusFilter) {
            statusFilter.addEventListener('change', handleFilterChange);
        }

        const applyFiltersBtn = document.getElementById('applyFilters');
        if (applyFiltersBtn) {
            applyFiltersBtn.addEventListener('click', handleFilterChange);
        }

        // Event delegation for action buttons
        document.addEventListener('click', function(e) {
            // Handle button clicks directly instead of dropdown
            if (e.target.closest('.deactivate-member-btn')) {
                e.preventDefault();
                const btn = e.target.closest('.deactivate-member-btn');
                const membershipId = btn.dataset.membershipId;
                deactivateMember(membershipId);
            }
            
            if (e.target.closest('.activate-member-btn')) {
                e.preventDefault();
                const btn = e.target.closest('.activate-member-btn');
                const membershipId = btn.dataset.membershipId;
                activateMember(membershipId);
            }

            if (e.target.closest('.change-role-btn')) {
                e.preventDefault();
                const btn = e.target.closest('.change-role-btn');
                const membershipId = btn.dataset.membershipId;
                openChangeRoleModal(membershipId);
            }

            if (e.target.closest('.remove-member-btn')) {
                e.preventDefault();
                const btn = e.target.closest('.remove-member-btn');
                const membershipId = btn.dataset.membershipId;
                confirmRemoveMember(membershipId);
            }
        });

        const inviteForm = document.getElementById('inviteMemberForm');
        if (inviteForm) {
            inviteForm.addEventListener('submit', handleInviteMember);
        }

        const changeRoleForm = document.getElementById('changeRoleForm');
        if (changeRoleForm) {
            changeRoleForm.addEventListener('submit', handleChangeRole);
        }

        // Enhanced invite form validation
        setupInviteFormValidation();
    }

    function setupInviteFormValidation() {
        const emailInput = document.getElementById('memberEmail');
        const emailHelp = document.getElementById('emailHelp');
        const messageInput = document.getElementById('memberMessage');
        const charCount = document.getElementById('charCount');
        const sendBtn = document.getElementById('sendInviteBtn');

        if (emailInput) {
            emailInput.addEventListener('blur', function() {
                validateEmailField(this, emailHelp);
            });

            emailInput.addEventListener('input', function() {
                if (emailHelp && emailHelp.classList.contains('text-danger')) {
                    validateEmailField(this, emailHelp);
                }
            });
        }

        if (messageInput && charCount) {
            messageInput.addEventListener('input', function() {
                const remaining = 500 - this.value.length;
                charCount.textContent = this.value.length + '/500';
                if (remaining < 50) {
                    charCount.classList.add('text-danger');
                    charCount.classList.remove('text-muted');
                } else {
                    charCount.classList.remove('text-danger');
                    charCount.classList.add('text-muted');
                }
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('mouseenter', function() {
                if (this.disabled) {
                    this.title = 'Please fill in all required fields correctly';
                } else {
                    this.title = '';
                }
            });
        }
    }

    function validateEmailField(input, helpElement) {
        const email = input.value.trim().toLowerCase();
        
        if (!email) {
            helpElement.textContent = 'Email address is required.';
            helpElement.classList.add('text-danger');
            helpElement.classList.remove('text-muted');
            input.classList.add('is-invalid');
            input.classList.remove('is-valid');
            return false;
        }

        if (!validateEmail(email)) {
            helpElement.textContent = 'Please enter a valid email address.';
            helpElement.classList.add('text-danger');
            helpElement.classList.remove('text-muted');
            input.classList.add('is-invalid');
            input.classList.remove('is-valid');
            return false;
        }

        // Check if email matches current user (self-invitation prevention)
        const currentUserEmail = document.querySelector('[data-current-user-email]')?.dataset.currentUserEmail;
        if (currentUserEmail && email === currentUserEmail.toLowerCase()) {
            helpElement.textContent = 'You cannot invite yourself to the team.';
            helpElement.classList.add('text-danger');
            helpElement.classList.remove('text-muted');
            input.classList.add('is-invalid');
            input.classList.remove('is-valid');
            return false;
        }

        helpElement.textContent = 'Enter the email address of the person you want to invite.';
        helpElement.classList.remove('text-danger');
        helpElement.classList.add('text-muted');
        input.classList.remove('is-invalid');
        input.classList.add('is-valid');
        return true;
    }

    function handleFilterChange() {
        currentFilters.search = document.getElementById('memberSearch')?.value.toLowerCase().trim() || '';
        currentFilters.role = document.getElementById('roleFilter')?.value || '';
        currentFilters.status = document.getElementById('statusFilter')?.value || '';
        
        loadMembers();
    }

    function loadMembers() {
        if (isLoading) return;
        
        isLoading = true;
        showLoading();

        // Build query parameters
        const params = new URLSearchParams();
        if (currentFilters.search) params.append('search', currentFilters.search);
        if (currentFilters.role) params.append('role', currentFilters.role);
        if (currentFilters.status) params.append('status', currentFilters.status);
        
        const url = '/settings/team/' + storeId + '/filter/?' + params.toString();
        
        console.log('Fetching members from:', url); // Debug logging
        
        fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            console.log('Response status:', response.status); // Debug logging
            return response.json();
        })
        .then(data => {
            console.log('Response data:', data); // Debug logging
            if (data.success) {
                renderMembersTable(data.members);
                if (data.stats) {
                    renderStats(data.stats);
                    updateInviteButton(data.stats);
                }
            } else {
                showNotification(data.error || 'Error loading members', 'error');
            }
        })
        .catch(error => {
            console.error('Error loading members:', error); // Debug logging
            showNotification('Error loading members', 'error');
        })
        .finally(() => {
            isLoading = false;
            hideLoading();
        });
    }

    function renderMembersTable(members) {
        const tbody = document.querySelector('#membersTable tbody');
        if (!tbody) return;

        if (members.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center py-5">
                        <i class="bi bi-search text-muted" style="font-size: 3rem;"></i>
                        <p class="text-muted mt-3">No team members found matching your criteria</p>
                        <button class="btn btn-outline-secondary btn-sm" onclick="TeamManagement.resetFilters()">
                            <i class="bi bi-x-circle me-1"></i>Clear Filters
                        </button>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = members.map(member => {
            const statusBadge = member.is_active 
                ? '<span class="status-badge status-badge--active">Active</span>'
                : '<span class="status-badge status-badge--inactive">Inactive</span>';
            
            const actionButtons = generateActionButtons(member);
            console.log('Member:', member.name, 'Action buttons:', actionButtons.substring(0, 100)); // Debug
            
            return `
                <tr class="member-row animate-in" 
                    data-member-id="${member.id}"
                    data-name="${member.name}"
                    data-email="${member.email}"
                    data-role="${member.role_name}"
                    data-status="${member.status}">
                    <td>
                        <div class="d-flex align-items-center">
                            <div class="avatar me-3">${member.avatar}</div>
                            <div>
                                <div class="fw-semibold">${member.name}</div>
                                <div class="small text-muted">${member.email}</div>
                            </div>
                        </div>
                    </td>
                    <td>
                        <span class="badge bg-secondary">${member.role_name}</span>
                    </td>
                    <td>${statusBadge}</td>
                    <td>
                        <small>${member.created_at}</small>
                    </td>
                    <td class="text-end">
                        <div class="btn-group">
                            ${actionButtons}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
        
        console.log('Table rendered successfully'); // Debug
        
        // Initialize action button event listeners
        initializeActionButtonListeners();
    }

    function initializeActionButtonListeners() {
        console.log('Initializing action button listeners'); // Debug
        // Event listeners are already set up via delegation in setupEventListeners
        // This function is a placeholder if needed for specific initialization
    }

    function generateActionButtons(member) {
        console.log('Generating action buttons for member:', member.name); // Debug logging
        let buttons = '';
        
        // Change Role button (always visible)
        buttons += `
            <button class="btn btn-sm btn-outline-secondary change-role-btn" 
                    data-membership-id="${member.id}"
                    data-bs-toggle="modal" 
                    data-bs-target="#changeRoleModal"
                    title="Change Role">
                <i class="bi bi-pencil"></i>
            </button>
        `;

        if (member.is_active) {
            // Deactivate button (for active members)
            buttons += `
                <button class="btn btn-sm btn-outline-warning deactivate-member-btn" 
                        data-membership-id="${member.id}"
                        title="Deactivate">
                    <i class="bi bi-person-x"></i>
                </button>
            `;
        } else {
            // Activate button (for inactive members)
            buttons += `
                <button class="btn btn-sm btn-outline-success activate-member-btn" 
                        data-membership-id="${member.id}"
                        title="Activate">
                    <i class="bi bi-person-check"></i>
                </button>
            `;
        }

        // Remove button (always visible)
        buttons += `
            <button class="btn btn-sm btn-outline-danger remove-member-btn" 
                    data-membership-id="${member.id}"
                    title="Remove">
                <i class="bi bi-trash"></i>
            </button>
        `;

        console.log('Generated buttons HTML:', buttons.substring(0, 200)); // Debug logging
        return buttons;
    }

    /**
     * Update the Team Statistics card AND the Team Stats modal in one pass.
     * Stat values are looked up by data-stat attribute so we don't depend on
     * label text matching.
     */
    function renderStats(stats) {
        if (!stats) return;

        const format = (val) => (val === null || val === undefined ? '∞' : val);

        const apply = (key, value) => {
            document.querySelectorAll(`[data-stat="${key}"]`).forEach(el => {
                el.textContent = format(value);
            });
        };

        apply('total_members', stats.total_members);
        apply('active_members', stats.active_members);
        apply('available_roles', stats.available_roles);
        apply('max_seats', stats.max_seats);
        apply('used_seats', stats.used_seats);
        apply('remaining_seats', stats.remaining_seats);

        // Toggle the danger highlight on the Remaining Seats wrapper when at cap.
        const atCap = stats.remaining_seats === 0;
        document.querySelectorAll('[data-stat-wrap="remaining_seats"]').forEach(el => {
            el.classList.toggle('text-danger', atCap);
            el.classList.toggle('stat-card--danger', atCap);
        });
    }

    /**
     * Toggle the Invite Member / Upgrade Plan button based on remaining_seats.
     * The button sits inside #teamActionButtons; we replace it in place so
     * Bootstrap attributes and event handlers stay consistent.
     */
    function updateInviteButton(stats) {
        if (!stats) return;

        const container = document.getElementById('teamActionButtons');
        if (!container) return;

        const canManage = container.querySelector('[data-bs-target="#inviteMemberModal"], .btn-warning');
        if (!canManage) return; // User without manage perm — nothing to update.

        const remaining = stats.remaining_seats;
        const remainingKnown = remaining !== null && remaining !== undefined;
        const atCap = remainingKnown && remaining === 0;

        // Find the existing action button (the invite or upgrade button).
        const existing = container.querySelector(
            '[data-bs-target="#inviteMemberModal"], .btn-warning[onclick*="subscriptions/manage"]'
        );
        if (!existing) return;

        if (atCap) {
            existing.outerHTML = `
                <button type="button" class="btn btn-warning"
                        onclick="window.location.href='/subscriptions/manage/'">
                    <i class="bi bi-arrow-up-circle me-1"></i>
                    Upgrade Plan
                    <span class="badge bg-light text-dark ms-2">0 seats remaining</span>
                </button>
            `;
        } else {
            const badge = remainingKnown
                ? `<span class="badge bg-light text-dark ms-2">${remaining} remaining</span>`
                : '';
            existing.outerHTML = `
                <button type="button" class="btn btn-primary"
                        data-bs-toggle="modal"
                        data-bs-target="#inviteMemberModal">
                    <i class="bi bi-person-plus me-1"></i>
                    Invite Member
                    ${badge}
                </button>
            `;
        }
    }

    function resetFilters() {
        document.getElementById('memberSearch').value = '';
        document.getElementById('roleFilter').value = '';
        document.getElementById('statusFilter').value = '';

        currentFilters = {
            search: '',
            role: '',
            status: ''
        };

        loadMembers();
    }

    function deactivateMember(membershipId) {
        window.confirmAction({
            title: "Deactivate Team Member",
            message: "Are you sure you want to deactivate this member? They will lose access to this store.",
            confirmText: "Deactivate",
            confirmClass: "btn-warning",
            onConfirm: function() {
                showLoading();
                fetch('/settings/team/' + storeId + '/deactivate/' + membershipId + '/', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                    },
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification(data.message, 'success');
                        loadMembers();
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
        });
    }

    function activateMember(membershipId) {
        window.confirmAction({
            title: "Activate Team Member",
            message: "Are you sure you want to activate this member? They will regain access to this store.",
            confirmText: "Activate",
            confirmClass: "btn-success",
            onConfirm: function() {
                showLoading();
                fetch('/settings/team/' + storeId + '/activate/' + membershipId + '/', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                    },
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification(data.message, 'success');
                        loadMembers();
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
        });
    }

    function openChangeRoleModal(membershipId) {
        const modal = document.getElementById('changeRoleModal');
        const membershipIdInput = document.getElementById('changeMembershipId');
        
        if (modal && membershipIdInput) {
            membershipIdInput.value = membershipId;
            const bsModal = bootstrap.Modal.getInstance(modal) || new bootstrap.Modal(modal);
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

        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Changing Role...';

        showLoading();

        fetch('/settings/team/' + storeId + '/change-role/' + membershipId + '/', {
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
                const modal = bootstrap.Modal.getInstance(document.getElementById('changeRoleModal'));
                if (modal) modal.hide();
                loadMembers(); // Reload to show updated roles
            } else {
                showNotification(data.error || 'Error changing role', 'error');
            }
        })
        .catch(error => {
            showNotification('Error changing role', 'error');
        })
        .finally(() => {
            hideLoading();
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnText;
        });
    }

    function confirmRemoveMember(membershipId) {
        window.confirmAction({
            title: "Remove Team Member",
            message: "Are you sure you want to remove this member from the team? This action cannot be undone.",
            confirmText: "Remove",
            confirmClass: "btn-danger",
            onConfirm: function() {
                showLoading();
                fetch('/settings/team/' + storeId + '/remove/' + membershipId + '/', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                    },
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification(data.message, 'success');
                        loadMembers();
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
        });
    }

    function handleInviteMember(e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);
        
        // Enhanced validation
        const email = formData.get('email')?.trim().toLowerCase();
        const role = formData.get('role');
        const message = formData.get('message')?.trim();

        // Client-side validation
        if (!email) {
            showNotification('Please enter an email address', 'error');
            return;
        }

        if (!validateEmail(email)) {
            showNotification('Please enter a valid email address', 'error');
            return;
        }

        if (!role) {
            showNotification('Please select a role', 'error');
            return;
        }

        // Prevent self-invitation check
        if (email === document.querySelector('[data-current-user-email]')?.dataset.currentUserEmail?.toLowerCase()) {
            showNotification('You cannot invite yourself to the team', 'error');
            return;
        }

        // Disable form and show loading
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Sending Invite...';

        showLoading();

        fetch('/settings/team/' + storeId + '/invite/', {
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
                const modal = bootstrap.Modal.getInstance(document.getElementById('inviteMemberModal'));
                if (modal) modal.hide();
                form.reset();
                loadMembers(); // Load members + stats to reflect new member
            } else {
                if (data.upgrade_required) {
                    showUpgradeModal(data);
                } else {
                    showNotification(data.error || 'Error inviting member', 'error');
                }
            }
        })
        .catch(error => {
            console.error('Invite error:', error);
            showNotification('Error inviting member. Please try again.', 'error');
        })
        .finally(() => {
            hideLoading();
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnText;
        });
    }

    function validateEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email);
    }

    function showUpgradeModal(data) {
        const modal = document.getElementById('inviteMemberModal');
        const modalBody = modal.querySelector('.modal-body');
        const modalTitle = modal.querySelector('.modal-title');
        const originalContent = modalBody.innerHTML;
        const originalTitle = modalTitle.textContent;

        modalTitle.textContent = 'Upgrade Required';
        
        const upgradeContent = `
            <div class="text-center py-4">
                <i class="bi bi-exclamation-triangle text-warning" style="font-size: 3rem;"></i>
                <h5 class="mt-3 mb-3">Seat Limit Reached</h5>
                <p class="text-muted mb-4">
                    ${data.error || 'You have reached the maximum number of team members for your current plan.'}
                </p>
                <div class="alert alert-info text-start">
                    <strong>Current Usage:</strong> ${data.current_usage || 0} / ${data.max_users || 0} seats
                </div>
                <div class="d-flex gap-2 justify-content-center">
                    <a href="/subscriptions/manage/" class="btn btn-primary">
                        <i class="bi bi-arrow-up-circle me-1"></i>Upgrade Plan
                    </a>
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                        Cancel
                    </button>
                </div>
            </div>
        `;
        
        modalBody.innerHTML = upgradeContent;
        
        // Reset modal when closed
        modal.addEventListener('hidden.bs.modal', function resetModal() {
            modalBody.innerHTML = originalContent;
            modalTitle.textContent = originalTitle;
            modal.removeEventListener('hidden.bs.modal', resetModal);
        }, { once: true });
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
        
        // Also clean up any Bootstrap modal backdrops that might be stuck
        const backdrops = document.querySelectorAll('.modal-backdrop');
        backdrops.forEach(backdrop => backdrop.remove());
        
        // Remove modal-open class from body
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
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

    function showNotification(message, type) {
        const container = document.getElementById('notificationContainer') || createNotificationContainer();
        const notification = document.createElement('div');
        
        notification.className = 'alert alert-' + (type === 'error' ? 'danger' : type) + ' alert-dismissible fade show';
        notification.innerHTML = message + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button>';
        
        container.appendChild(notification);
        
        setTimeout(function() {
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
            const later = function() {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    return {
        init: init,
        loadMembers: loadMembers,
        resetFilters: resetFilters
    };
})();

document.addEventListener('DOMContentLoaded', function() {
    const storeId = document.querySelector('[data-store-id]')?.dataset.storeId;
    if (storeId) {
        TeamManagement.init(storeId);
    }
});