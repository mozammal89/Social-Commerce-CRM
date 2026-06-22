/**
 * Bootstrap Dropdown Enhancement
 * Ensures dropdowns work properly with fixed navbar
 * Works WITH Bootstrap, not against it
 */

document.addEventListener('DOMContentLoaded', function() {
    // Only enhance, don't replace Bootstrap dropdown functionality
    const dropdownToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');

    dropdownToggles.forEach(function(toggle) {
        const dropdown = toggle.closest('.dropdown');
        if (!dropdown) return; // Skip if no dropdown parent found

        const menu = dropdown.querySelector('.dropdown-menu');
        if (!menu) return; // Skip if no menu found

        // Listen for Bootstrap show event
        toggle.addEventListener('show.bs.dropdown', function() {
            // Ensure proper positioning when Bootstrap shows the dropdown
            menu.style.position = 'absolute';
            menu.style.zIndex = '1055';
        });

        // Listen for Bootstrap hide event
        toggle.addEventListener('hide.bs.dropdown', function() {
            // Clean up when hidden
            setTimeout(() => {
                if (!dropdown.classList.contains('show')) {
                    menu.style.display = '';
                }
            }, 10);
        });
    });

    // Global dropdown positioning fix
    document.addEventListener('shown.bs.dropdown', function(event) {
        const menu = event.target.querySelector('.dropdown-menu');
        if (menu) {
            menu.style.position = 'absolute';
            menu.style.zIndex = '1055';
            
            // Special handling for table dropdowns
            if (event.target.closest('.store-row') || event.target.closest('table')) {
                menu.style.position = 'absolute';
                menu.style.zIndex = '1055';
                menu.style.left = 'auto';
                menu.style.right = '0';
            }
        }
    });
    
    // Fix for table dropdown positioning
    const tableDropdowns = document.querySelectorAll('.store-row .dropdown');
    tableDropdowns.forEach(function(tableDropdown) {
        const toggle = tableDropdown.querySelector('[data-bs-toggle="dropdown"]');
        if (toggle) {
            // Ensure the dropdown container has proper positioning
            tableDropdown.style.position = 'relative';
            tableDropdown.style.zIndex = '10';
        }
    });

    // Ensure only one dropdown is open at a time
    document.addEventListener('show.bs.dropdown', function(event) {
        const currentDropdown = event.target.closest('.dropdown');

        // Close other open dropdowns
        document.querySelectorAll('.dropdown.show').forEach(function(openDropdown) {
            if (openDropdown !== currentDropdown) {
                const dropdownInstance = bootstrap.Dropdown.getInstance(openDropdown.querySelector('[data-bs-toggle="dropdown"]'));
                if (dropdownInstance) {
                    dropdownInstance.hide();
                }
            }
        });
    });

    console.log('Bootstrap dropdown enhancement applied (works WITH Bootstrap)');
});