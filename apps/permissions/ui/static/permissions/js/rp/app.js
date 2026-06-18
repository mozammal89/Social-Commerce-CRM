/**
 * Role & Permission UI — shared app bootstrap.
 *
 * Provides:
 *   - Auto-submit on debounced input changes
 *   - Confirmation dialog for destructive actions
 *   - Reusable fetch wrapper with CSRF
 *
 * Loaded as a module by every page in the role/permission UI.
 */

const getCsrfToken = () => {
  const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return el ? el.value : '';
};

const parseError = async (response) => {
  let message = `Request failed (${response.status})`;
  try {
    const data = await response.json();
    if (data && data.error) message = data.error;
  } catch (_) { /* non-JSON body */ }
  return new Error(message);
};

export const api = {
  async get(url, options = {}) {
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      credentials: 'same-origin',
      ...options,
    });
    if (!response.ok) throw await parseError(response);
    return response.json();
  },

  async post(url, body, options = {}) {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
      credentials: 'same-origin',
      body: JSON.stringify(body),
      ...options,
    });
    if (!response.ok) throw await parseError(response);
    return response.json();
  },
};

const debounce = (fn, delay = 300) => {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(null, args), delay);
  };
};

const initAutoSubmit = () => {
  document.querySelectorAll('[data-auto-submit]').forEach((el) => {
    const delay = Number(el.dataset.debounce) || 0;
    const submit = () => {
      if (el.form) {
        if (el.form.requestSubmit) el.form.requestSubmit();
        else el.form.submit();
      }
    };
    if (el.type === 'search' || el.tagName === 'INPUT') {
      el.addEventListener('input', debounce(submit, delay || 300));
    } else {
      el.addEventListener('change', submit);
    }
  });
};

const initExpandCollapse = () => {
  const expandAll = document.querySelector('[data-action="expand-all"]');
  const collapseAll = document.querySelector('[data-action="collapse-all"]');
  if (!expandAll && !collapseAll) return;

  const groups = () => document.querySelectorAll('details.permission-group');
  expandAll?.addEventListener('click', () => groups().forEach((g) => g.open = true));
  collapseAll?.addEventListener('click', () => groups().forEach((g) => g.open = false));
};

const initConfirmations = () => {
  document.querySelectorAll('[data-action="delete-role"]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const name = btn.dataset.roleName || 'this role';
      const ok = window.confirm(
        `Delete "${name}"?\n\nActive members will lose access until they are reassigned. This action cannot be undone.`
      );
      if (ok) btn.form.submit();
    });
  });
};

const initCloneButtons = () => {
  document.querySelectorAll('[data-action="clone-role"]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const name = btn.dataset.roleName || 'this role';
      const newName = window.prompt(`Name for the cloned role:`, `${name} (copy)`);
      if (!newName) return;

      const roleId = btn.dataset.roleId;
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = `/dashboard/roles/${roleId}/clone/`;

      const csrf = document.createElement('input');
      csrf.type = 'hidden';
      csrf.name = 'csrfmiddlewaretoken';
      csrf.value = getCsrfToken();

      const nameInput = document.createElement('input');
      nameInput.type = 'hidden';
      nameInput.name = 'new_name';
      nameInput.value = newName;

      form.append(csrf, nameInput);
      document.body.appendChild(form);
      form.submit();
    });
  });
};

const init = () => {
  initAutoSubmit();
  initExpandCollapse();
  initConfirmations();
  initCloneButtons();
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
