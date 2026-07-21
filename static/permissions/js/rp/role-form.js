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
    animateSelectAll(allCheckboxes());
    allCheckboxes().forEach((cb) => { cb.checked = true; });
    syncGroupHeaders(form, allCheckboxes);
    updateCounter(form, allCheckboxes);
  });

  deselectAll?.addEventListener('click', (e) => {
    e.preventDefault();
    animateDeselectAll(allCheckboxes());
    allCheckboxes().forEach((cb) => { cb.checked = false; });
    syncGroupHeaders(form, allCheckboxes);
    updateCounter(form, allCheckboxes);
  });

  invert?.addEventListener('click', (e) => {
    e.preventDefault();
    animateInvertSelection(allCheckboxes());
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

      // Animate the group's checkboxes
      const checkboxes = group.querySelectorAll('input[type="checkbox"][name="permissions"]');
      animateSelectAll(checkboxes);

      group.querySelectorAll('input[type="checkbox"][name="permissions"]')
        .forEach((cb) => { cb.checked = true; });
      syncGroupHeaders(form, allCheckboxes);
      updateCounter(form, allCheckboxes);

      // Visual feedback on the button
      btn.style.transform = 'scale(1.1)';
      setTimeout(() => btn.style.transform = '', 150);
    });
  });

  form.querySelectorAll('[data-action="group-deselect-all"]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const group = btn.closest('[data-permission-group]');
      if (!group) return;

      // Animate the group's checkboxes
      const checkboxes = group.querySelectorAll('input[type="checkbox"][name="permissions"]');
      animateDeselectAll(checkboxes);

      group.querySelectorAll('input[type="checkbox"][name="permissions"]')
        .forEach((cb) => { cb.checked = false; });
      syncGroupHeaders(form, allCheckboxes);
      updateCounter(form, allCheckboxes);

      // Visual feedback on the button
      btn.style.transform = 'scale(1.1)';
      setTimeout(() => btn.style.transform = '', 150);
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

/**
 * Animation functions for smooth micro-interactions
 */

/**
 * Animate select-all with a ripple effect
 */
const animateSelectAll = (checkboxes) => {
  checkboxes.forEach((cb, index) => {
    const tile = cb.closest('.rp-permission-tile');
    if (tile) {
      setTimeout(() => {
        tile.style.transform = 'scale(0.98)';
        setTimeout(() => {
          tile.style.transform = '';
        }, 100);
      }, index * 10);
    }
  });
};

/**
 * Animate deselect-all with a fade effect
 */
const animateDeselectAll = (checkboxes) => {
  checkboxes.forEach((cb, index) => {
    const tile = cb.closest('.rp-permission-tile');
    if (tile) {
      setTimeout(() => {
        tile.style.transition = 'all 150ms ease';
        tile.style.opacity = '0.7';
        setTimeout(() => {
          tile.style.opacity = '';
          tile.style.transition = '';
        }, 150);
      }, index * 8);
    }
  });
};

/**
 * Animate invert with a pulse effect
 */
const animateInvertSelection = (checkboxes) => {
  checkboxes.forEach((cb) => {
    const tile = cb.closest('.rp-permission-tile');
    if (tile) {
      tile.style.transition = 'all 200ms cubic-bezier(0.4, 0, 0.2, 1)';
      tile.style.transform = 'scale(0.97)';
      setTimeout(() => {
        tile.style.transform = '';
        tile.style.transition = '';
      }, 200);
    }
  });
};

/**
 * Add smooth collapse animation to permission groups
 */
const animateGroupCollapse = () => {
  document.querySelectorAll('.rp-permission-group').forEach(group => {
    const summary = group.querySelector('summary');
    if (!summary) return;

    summary.addEventListener('click', () => {
      const isOpen = group.hasAttribute('open');
      const grid = group.querySelector('.rp-permission-grid');
      if (!grid) return;

      if (!isOpen) {
        // Opening
        grid.style.opacity = '0';
        grid.style.transform = 'translateY(-8px)';
        setTimeout(() => {
          grid.style.transition = 'all 250ms ease';
          grid.style.opacity = '1';
          grid.style.transform = '';
        }, 50);
      }
    });
  });
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    init();
    animateGroupCollapse();
  });
} else {
  init();
  animateGroupCollapse();
}
