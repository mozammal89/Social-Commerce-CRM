/**
 * Role form: select-all / deselect-all for the permission checkboxes,
 * plus per-resource (per-group) toggle helpers.
 *
 * The form renders each permission as <input type="checkbox" name="permissions" value="...">
 * grouped inside <fieldset data-permission-group="<resource-id>"> blocks.
 */

const init = () => {
  const form = document.querySelector('form[data-component="role-form"]');
  if (!form) return;

  const allCheckboxes = () =>
    Array.from(form.querySelectorAll('input[type="checkbox"][name="permissions"]'));

  // ----- Global select-all / deselect-all -----
  const selectAll = form.querySelector('[data-action="select-all"]');
  const deselectAll = form.querySelector('[data-action="deselect-all"]');
  const invert = form.querySelector('[data-action="invert-selection"]');

  selectAll?.addEventListener('click', (e) => {
    e.preventDefault();
    allCheckboxes().forEach((cb) => { cb.checked = true; });
    syncGroupHeaders(form, allCheckboxes);
    updateCounter(form, allCheckboxes);
  });

  deselectAll?.addEventListener('click', (e) => {
    e.preventDefault();
    allCheckboxes().forEach((cb) => { cb.checked = false; });
    syncGroupHeaders(form, allCheckboxes);
    updateCounter(form, allCheckboxes);
  });

  invert?.addEventListener('click', (e) => {
    e.preventDefault();
    allCheckboxes().forEach((cb) => { cb.checked = !cb.checked; });
    syncGroupHeaders(form, allCheckboxes);
    updateCounter(form, allCheckboxes);
  });

  // ----- Per-resource select-all / deselect-all -----
  form.querySelectorAll('[data-action="group-select-all"]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const group = btn.closest('[data-permission-group]');
      if (!group) return;
      group.querySelectorAll('input[type="checkbox"][name="permissions"]')
        .forEach((cb) => { cb.checked = true; });
      syncGroupHeaders(form, allCheckboxes);
      updateCounter(form, allCheckboxes);
    });
  });

  form.querySelectorAll('[data-action="group-deselect-all"]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const group = btn.closest('[data-permission-group]');
      if (!group) return;
      group.querySelectorAll('input[type="checkbox"][name="permissions"]')
        .forEach((cb) => { cb.checked = false; });
      syncGroupHeaders(form, allCheckboxes);
      updateCounter(form, allCheckboxes);
    });
  });

  // ----- Per-checkbox change → update headers & counter -----
  form.addEventListener('change', (e) => {
    if (e.target.matches('input[type="checkbox"][name="permissions"]')) {
      syncGroupHeaders(form, allCheckboxes);
      updateCounter(form, allCheckboxes);
    }
  });

  // ----- Initial paint -----
  syncGroupHeaders(form, allCheckboxes);
  updateCounter(form, allCheckboxes);
};

/**
 * Update each resource group's "X / Y selected" badge to reflect the
 * current selection state.
 */
const syncGroupHeaders = (form, allCheckboxes) => {
  const groups = form.querySelectorAll('[data-permission-group]');
  groups.forEach((group) => {
    const cbs = group.querySelectorAll('input[type="checkbox"][name="permissions"]');
    const checked = Array.from(cbs).filter((cb) => cb.checked).length;
    const total = cbs.length;
    const counter = group.querySelector('[data-group-counter]');
    if (counter) counter.textContent = `${checked} / ${total}`;
    const allBtn = group.querySelector('[data-action="group-select-all"]');
    const noneBtn = group.querySelector('[data-action="group-deselect-all"]');
    if (allBtn) allBtn.disabled = (checked === total);
    if (noneBtn) noneBtn.disabled = (checked === 0);
  });
};

/**
 * Update the global "X permissions selected" badge and the
 * submit-button label so the user knows what they're about to grant.
 */
const updateCounter = (form, allCheckboxes) => {
  const cbs = allCheckboxes();
  const total = cbs.length;
  const checked = cbs.filter((cb) => cb.checked).length;
  const counter = form.querySelector('[data-permission-counter]');
  if (counter) {
    counter.textContent = `${checked} of ${total} selected`;
  }
  const submit = form.querySelector('button[type="submit"]');
  if (submit && submit.dataset.submitTemplate) {
    // Only swap the badge portion of the label so the icon stays put.
    const tmpl = submit.dataset.submitTemplate; // e.g. "Create role ({n})"
    submit.innerHTML = submit.innerHTML.replace(
      /\{n\}/g,
      String(checked),
    );
    submit.dataset.submitTemplate = tmpl;
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
