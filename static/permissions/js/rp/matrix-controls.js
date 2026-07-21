/**
 * Permission matrix controls: expand-all / collapse-all / clone-role
 * for the role detail page.
 *
 * Uses the native <details>/<summary> elements; we just flip their
 * `open` attribute in bulk.
 */

const init = () => {
  const matrix = document.querySelector('[data-component="permission-matrix"]');
  if (!matrix) return;

  const groups = matrix.querySelectorAll('details.permission-group');

  const expandAll = document.querySelector('[data-action="expand-all"]');
  const collapseAll = document.querySelector('[data-action="collapse-all"]');

  expandAll?.addEventListener('click', (e) => {
    e.preventDefault();
    groups.forEach((g) => { g.open = true; });
  });

  collapseAll?.addEventListener('click', (e) => {
    e.preventDefault();
    groups.forEach((g) => { g.open = false; });
  });
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
