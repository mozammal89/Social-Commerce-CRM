/**
 * Member list: inline role change + activate/deactivate (with confirmation).
 */

import { api } from './app.js';

const setRowInactive = (row) => {
  if (!row) return;
  row.classList.add('text-muted');
  const badge = row.querySelector('.badge.bg-success-subtle');
  if (badge) {
    badge.classList.remove('bg-success-subtle', 'text-success-emphasis');
    badge.classList.add('bg-secondary');
    badge.textContent = 'Inactive';
  }
  const roleSelect = row.querySelector('.member-role-select');
  if (roleSelect) roleSelect.disabled = true;
};

const setRowActive = (row) => {
  if (!row) return;
  row.classList.remove('text-muted');
  const badge = row.querySelector('.badge.bg-secondary');
  if (badge) {
    badge.classList.remove('bg-secondary');
    badge.classList.add('bg-success-subtle', 'text-success-emphasis');
    badge.textContent = 'Active';
  }
  const roleSelect = row.querySelector('.member-role-select');
  if (roleSelect) roleSelect.disabled = false;
};

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
        setRowInactive(row);
        // Swap the button to a Reactivate button.
        btn.classList.remove('btn-outline-danger');
        btn.classList.add('btn-outline-success');
        btn.dataset.action = 'reactivate-member';
        const icon = btn.querySelector('i.bi');
        if (icon) {
          icon.classList.remove('bi-person-x');
          icon.classList.add('bi-person-check');
        }
        const text = btn.textContent.trim();
        btn.lastChild && (btn.lastChild.nodeValue = ' Reactivate');
        btn.disabled = false;
      } catch (err) {
        btn.disabled = false;
        window.alert(err.message || 'Failed to deactivate member');
      }
    });
  });
};

const initReactivate = () => {
  document.querySelectorAll('[data-action="reactivate-member"]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const name = btn.dataset.memberName || 'this member';
      const ok = window.confirm(
        `Reactivate ${name}? They will regain access to this store immediately.`
      );
      if (!ok) return;

      const membershipId = btn.dataset.membershipId;
      btn.disabled = true;
      try {
        await api.post(`/dashboard/members/${membershipId}/reactivate/`);
        const row = btn.closest('tr');
        setRowActive(row);
        // Swap the button to a Deactivate button.
        btn.classList.remove('btn-outline-success');
        btn.classList.add('btn-outline-danger');
        btn.dataset.action = 'deactivate-member';
        const icon = btn.querySelector('i.bi');
        if (icon) {
          icon.classList.remove('bi-person-check');
          icon.classList.add('bi-person-x');
        }
        btn.disabled = false;
      } catch (err) {
        btn.disabled = false;
        window.alert(err.message || 'Failed to reactivate member');
      }
    });
  });
};

const init = () => {
  initChangeRole();
  initDeactivate();
  initReactivate();
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
