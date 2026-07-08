/**
 * Role & Permission management UI scripts
 * Handles form auto-submit, search debouncing, and AJAX filtering
 */

console.log('RP app.js loaded');

// Debounce utility function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// AJAX form submission
async function submitFormAjax(form) {
    console.log('Submitting form via AJAX...');
    const formData = new FormData(form);
    const params = new URLSearchParams(formData).toString();
    const url = `${window.location.pathname}?${params}`;

    // Show loading state
    const resultsContainer = document.querySelector('[data-results-container]');
    if (resultsContainer) {
        resultsContainer.style.opacity = '0.5';
    }

    try {
        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
            },
        });

        if (!response.ok) {
            throw new Error('Network response was not ok');
        }

        const html = await response.text();
        console.log('AJAX response received');

        // Parse the response
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');

        // Update the results container
        const newResults = doc.querySelector('[data-results-container]');
        const currentResults = document.querySelector('[data-results-container]');

        if (newResults && currentResults) {
            currentResults.innerHTML = newResults.innerHTML;
        } else {
            console.error('Could not find results containers');
        }

        // Update URL without reloading
        window.history.replaceState({}, '', url);

    } catch (error) {
        console.error('Error loading results:', error);
        // Fallback to regular form submission on error
        form.submit();
    } finally {
        if (resultsContainer) {
            resultsContainer.style.opacity = '1';
        }
    }
}

// Initialize auto-submit functionality
function initOverrideFilters() {
    console.log('Initializing override filters...');

    const filterForm = document.getElementById('filterForm');

    if (!filterForm) {
        console.error('Filter form #filterForm not found');
        return;
    }

    console.log('Filter form found, attaching event listeners...');

    // Prevent normal form submission
    filterForm.addEventListener('submit', function(e) {
        console.log('Form submit event intercepted');
        e.preventDefault();
        e.stopPropagation();
        submitFormAjax(filterForm);
        return false;
    });

    // Attach listeners to all inputs and selects
    const inputs = filterForm.querySelectorAll('input, select');
    console.log(`Found ${inputs.length} inputs to attach to`);

    inputs.forEach((input, index) => {
        const inputName = input.name || input.id || 'unnamed';
        const debounceTime = parseInt(input.dataset.debounce || '0', 10);

        if (debounceTime > 0) {
            // Debounced input (search boxes)
            input.addEventListener('input', debounce(function() {
                console.log(`Debounced input changed: ${inputName}`);
                submitFormAjax(filterForm);
            }, debounceTime));
            console.log(`Attached debounced listener to: ${inputName} (${debounceTime}ms)`);
        } else {
            // Immediate submit (select dropdowns)
            input.addEventListener('change', function() {
                console.log(`Filter changed: ${inputName}`);
                submitFormAjax(filterForm);
            });
            console.log(`Attached change listener to: ${inputName}`);
        }
    });

    console.log('Override filters initialized successfully');
}

// Wait for DOM to be ready
function initWhenReady() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initOverrideFilters);
    } else {
        // DOM is already ready
        initOverrideFilters();
    }
}

// Start initialization
initWhenReady();

// Also try after a short delay in case of timing issues
setTimeout(function() {
    console.log('Retrying initialization...');
    initOverrideFilters();
}, 500);

// Export for global access
window.RP = window.RP || {};
window.RP.initOverrideFilters = initOverrideFilters;
window.RP.submitFormAjax = submitFormAjax;
