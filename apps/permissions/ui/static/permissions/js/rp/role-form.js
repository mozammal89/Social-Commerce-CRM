/**
 * Role form: select-all / deselect-all for the permission checkboxes.
 */

const init = () => {
  const selectAll = document.querySelector('[data-action="select-all"]');
  const deselectAll = document.querySelector('[data-action="deselect-all"]');
  if (!selectAll && !deselectAll) return;

  // Scope to this form's permission checkboxes
  const form = (selectAll || deselectAll).closest('form');
  const checkboxes = () => form.querySelectorAll('input[type="checkbox"][name$="-permissions"]');

  selectAll?.addEventListener('click', (e) => {
    e.preventDefault();
    checkboxes().forEach((cb) => { cb.checked = true; });
  });

  deselectAll?.addEventListener('click', (e) => {
    e.preventDefault();
    checkboxes().forEach((cb) => { cb.checked = false; });
  });
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
