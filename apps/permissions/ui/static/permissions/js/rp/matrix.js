/**
 * Permission matrix — AJAX toggling of individual permissions on a role.
 *
 * Optimistic UI: toggle the checkbox visually first, send the request,
 * reconcile on response, rollback on error.
 */

import { api } from './app.js';

const init = () => {
  const matrix = document.querySelector('[data-component="permission-matrix"]');
  if (!matrix) return;
  const roleId = matrix.dataset.roleId;

  matrix.addEventListener('change', async (event) => {
    const cb = event.target.closest('[data-action="toggle-permission"]');
    if (!cb || cb.disabled) return;

    const permissionId = cb.dataset.permissionId;
    const row = cb.closest('.permission-row');

    const wasChecked = cb.checked;
    row.classList.toggle('bg-primary-subtle', wasChecked);
    row.classList.toggle('border-primary', wasChecked);
    cb.disabled = true;

    try {
      const data = await api.post(
        `/dashboard/roles/${roleId}/toggle-permission/`,
        { permission_id: permissionId },
      );
      row.classList.toggle('bg-primary-subtle', data.granted);
      row.classList.toggle('border-primary', data.granted);
      cb.checked = data.granted;
    } catch (err) {
      // Rollback
      cb.checked = !wasChecked;
      row.classList.toggle('bg-primary-subtle', !wasChecked);
      row.classList.toggle('border-primary', !wasChecked);
      // eslint-disable-next-line no-console
      console.error('Failed to toggle permission', err);
      window.alert(err.message || 'Failed to update permission');
    } finally {
      cb.disabled = false;
    }
  });
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
