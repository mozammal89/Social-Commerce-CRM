/**
 * Member list: inline role change + deactivate (with confirmation).
 */

import { api } from './app.js';

const initChangeRole = () => {
  document.querySelectorAll('[data-action="change-role"]').forEach((select) => {
    select.addEventListener('change', async (e) => {
      const membershipId = select.dataset.membershipId;
      const newRoleId = select.value;
      const previous = select.dataset.previous || select.defaultValue;
      select.dataset.previous = newRoleId;

      select.disabled = true;
      try {
        await api.post(
          `/dashboard/members/${membershipId}/change-role/`,
          { role_id: newRoleId },
        );
      } catch (err) {
        select.value = previous;
        window.alert(err.message || 'Failed to change role');
      } finally {
        select.disabled = false;
      }
    });
  });
};

const initDeactivate = () => {
  document.querySelectorAll('[data-action="deactivate-member"]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const name = btn.dataset.memberName || 'this member';
      const ok = window.confirm(
        `Deactivate ${name}?\n\nThey will lose access to this store immediately, but their history is preserved.`
      );
      if (!ok) return;

      const membershipId = btn.dataset.membershipId;
      btn.disabled = true;
      try {
        await api.post(`/dashboard/members/${membershipId}/deactivate/`);
        const row = btn.closest('tr');
        if (row) {
          row.classList.add('text-muted');
          const badge = row.querySelector('.badge.bg-success-subtle');
          if (badge) {
            badge.classList.remove('bg-success-subtle', 'text-success-emphasis');
            badge.classList.add('bg-secondary');
            badge.textContent = 'Inactive';
          }
          const roleSelect = row.querySelector('.member-role-select');
          if (roleSelect) roleSelect.disabled = true;
          btn.remove();
        }
      } catch (err) {
        btn.disabled = false;
        window.alert(err.message || 'Failed to deactivate member');
      }
    });
  });
};

const init = () => {
  initChangeRole();
  initDeactivate();
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
