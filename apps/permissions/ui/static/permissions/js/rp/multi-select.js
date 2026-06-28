/**
 * Custom multi-select dropdown component.
 * Converts a standard <select multiple> into a dropdown with chips for selected items.
 */

class MultiSelect {
  constructor(selectElement, options = {}) {
    this.select = selectElement;
    this.options = {
      placeholder: options.placeholder || 'Select items...',
      maxHeight: options.maxHeight || '300px',
      searchPlaceholder: options.searchPlaceholder || 'Search...',
      ...options
    };

    this.selectedOptions = new Set();
    this.init();
  }

  init() {
    // Hide the original select
    this.select.style.display = 'none';

    // Get the container (usually the parent div)
    const container = this.select.parentElement;

    // Create the custom multi-select UI
    this.multiSelectContainer = document.createElement('div');
    this.multiSelectContainer.className = 'custom-multi-select';

    // Create the selected items display area
    this.selectedDisplay = document.createElement('div');
    this.selectedDisplay.className = 'custom-multi-select__display';
    this.selectedDisplay.innerHTML = `<span class="custom-multi-select__placeholder">${this.options.placeholder}</span>`;
    this.multiSelectContainer.appendChild(this.selectedDisplay);

    // Create the dropdown
    this.dropdown = document.createElement('div');
    this.dropdown.className = 'custom-multi-select__dropdown';
    this.dropdown.style.maxHeight = this.options.maxHeight;

    // Create search input
    this.searchInput = document.createElement('input');
    this.searchInput.type = 'text';
    this.searchInput.className = 'custom-multi-select__search';
    this.searchInput.placeholder = this.options.searchPlaceholder;
    this.dropdown.appendChild(this.searchInput);

    // Create options list
    this.optionsList = document.createElement('div');
    this.optionsList.className = 'custom-multi-select__options';
    this.dropdown.appendChild(this.optionsList);

    this.multiSelectContainer.appendChild(this.dropdown);

    // Insert before the original select
    container.insertBefore(this.multiSelectContainer, this.select);

    // Populate options
    this.populateOptions();

    // Set initial selected values
    this.setInitialValues();

    // Event listeners
    this.setupEventListeners();
  }

  populateOptions() {
    const options = this.select.querySelectorAll('option');
    options.forEach(option => {
      const optionElement = document.createElement('div');
      optionElement.className = 'custom-multi-select__option';
      optionElement.dataset.value = option.value;
      optionElement.textContent = option.textContent;

      optionElement.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleOption(option.value, option.textContent);
      });

      this.optionsList.appendChild(optionElement);
    });
  }

  setInitialValues() {
    const options = this.select.querySelectorAll('option:selected');
    options.forEach(option => {
      this.selectedOptions.add(option.value);
    });
    this.updateDisplay();
  }

  toggleOption(value, text) {
    if (this.selectedOptions.has(value)) {
      this.selectedOptions.delete(value);
    } else {
      this.selectedOptions.add(value);
    }

    // Update the original select
    const originalOption = this.select.querySelector(`option[value="${value}"]`);
    if (originalOption) {
      originalOption.selected = this.selectedOptions.has(value);
    }

    this.updateDisplay();
    this.updateOptionStates();

    // Trigger change event on original select
    this.select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  updateDisplay() {
    if (this.selectedOptions.size === 0) {
      this.selectedDisplay.innerHTML = `<span class="custom-multi-select__placeholder">${this.options.placeholder}</span>`;
      return;
    }

    this.selectedDisplay.innerHTML = '';

    this.selectedOptions.forEach(value => {
      const option = this.select.querySelector(`option[value="${value}"]`);
      if (!option) return;

      const chip = document.createElement('span');
      chip.className = 'custom-multi-select__chip';
      chip.innerHTML = `
        <span class="custom-multi-select__chip-text">${option.textContent}</span>
        <span class="custom-multi-select__chip-remove" data-value="${value}">&times;</span>
      `;

      const removeBtn = chip.querySelector('.custom-multi-select__chip-remove');
      removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleOption(value, option.textContent);
      });

      this.selectedDisplay.appendChild(chip);
    });
  }

  updateOptionStates() {
    const optionElements = this.optionsList.querySelectorAll('.custom-multi-select__option');
    optionElements.forEach(element => {
      const value = element.dataset.value;
      if (this.selectedOptions.has(value)) {
        element.classList.add('custom-multi-select__option--selected');
      } else {
        element.classList.remove('custom-multi-select__option--selected');
      }
    });
  }

  setupEventListeners() {
    // Toggle dropdown on click
    this.selectedDisplay.addEventListener('click', () => {
      this.dropdown.classList.toggle('custom-multi-select__dropdown--open');
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
      if (!this.multiSelectContainer.contains(e.target)) {
        this.dropdown.classList.remove('custom-multi-select__dropdown--open');
      }
    });

    // Filter options based on search
    this.searchInput.addEventListener('input', (e) => {
      const searchTerm = e.target.value.toLowerCase();
      const optionElements = this.optionsList.querySelectorAll('.custom-multi-select__option');

      optionElements.forEach(element => {
        const text = element.textContent.toLowerCase();
        if (text.includes(searchTerm)) {
          element.style.display = '';
        } else {
          element.style.display = 'none';
        }
      });
    });

    // Prevent dropdown from closing when clicking inside it
    this.dropdown.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  }
}

// Initialize multi-selects on page load
const initMultiSelects = () => {
  const selects = document.querySelectorAll('select[multiple]');
  selects.forEach(select => {
    if (!select.dataset.multiSelectInitialized) {
      new MultiSelect(select, {
        placeholder: 'Select permissions...',
        searchPlaceholder: 'Search permissions...',
        maxHeight: '300px'
      });
      select.dataset.multiSelectInitialized = 'true';
    }
  });
};

// Auto-initialize
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMultiSelects);
} else {
  initMultiSelects();
}

// Export for manual initialization
window.MultiSelect = MultiSelect;
window.initMultiSelects = initMultiSelects;
