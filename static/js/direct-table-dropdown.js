/**
 * Direct Table Dropdown Override
 * Completely bypasses Bootstrap for table dropdowns to ensure they work
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('Applying direct table dropdown fix...');
    
    // Find all store row dropdowns
    const storeDropdowns = document.querySelectorAll('.store-row .dropdown');
    
    storeDropdowns.forEach(function(dropdown) {
        const toggle = dropdown.querySelector('[data-bs-toggle="dropdown"]');
        const menu = dropdown.querySelector('.dropdown-menu');
        
        if (!toggle || !menu) return;
        
        // Completely disable Bootstrap dropdown for this element
        toggle.removeAttribute('data-bs-toggle');
        toggle.removeAttribute('data-bs-toggle');
        toggle.setAttribute('data-custom-dropdown', 'true');
        
        // Add custom click handler
        toggle.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            
            const allDropdowns = document.querySelectorAll('.store-row .dropdown');
            allDropdowns.forEach(function(otherDropdown) {
                if (otherDropdown !== dropdown) {
                    otherDropdown.classList.remove('show');
                    const otherMenu = otherDropdown.querySelector('.dropdown-menu');
                    if (otherMenu) {
                        otherMenu.style.display = 'none';
                        otherMenu.style.visibility = 'hidden';
                        otherMenu.style.opacity = '0';
                    }
                }
            });
            
            const isOpen = dropdown.classList.contains('show');
            
            if (!isOpen) {
                dropdown.classList.add('show');
                menu.style.display = 'block';
                menu.style.visibility = 'visible';
                menu.style.opacity = '1';
                menu.style.position = 'absolute';
                menu.style.zIndex = '9999';
                menu.style.right = '0';
                menu.style.left = 'auto';
                menu.style.top = '100%';
                menu.style.marginTop = '4px';
                
                // Get toggle button position and align dropdown
                const toggleRect = toggle.getBoundingClientRect();
                const parentRect = dropdown.getBoundingClientRect();
                
                menu.style.position = 'absolute';
                menu.style.right = '0';
                menu.style.left = 'auto';
                menu.style.top = '100%';
            } else {
                dropdown.classList.remove('show');
                menu.style.display = 'none';
                menu.style.visibility = 'hidden';
                menu.style.opacity = '0';
            }
        });
        
        // Initialize hidden state
        menu.style.display = 'none';
        menu.style.visibility = 'hidden';
        menu.style.opacity = '0';
        menu.style.position = 'absolute';
        menu.style.zIndex = '9999';
    });
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', function(event) {
        const clickedInsideDropdown = event.target.closest('.store-row .dropdown');
        
        if (!clickedInsideDropdown) {
            document.querySelectorAll('.store-row .dropdown.show').forEach(function(dropdown) {
                dropdown.classList.remove('show');
                const menu = dropdown.querySelector('.dropdown-menu');
                if (menu) {
                    menu.style.display = 'none';
                    menu.style.visibility = 'hidden';
                    menu.style.opacity = '0';
                }
            });
        }
    });
    
    // Handle escape key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            document.querySelectorAll('.store-row .dropdown.show').forEach(function(dropdown) {
                dropdown.classList.remove('show');
                const menu = dropdown.querySelector('.dropdown-menu');
                if (menu) {
                    menu.style.display = 'none';
                    menu.style.visibility = 'hidden';
                    menu.style.opacity = '0';
                }
            });
        }
    });
    
    console.log('Direct table dropdown fix applied successfully');
});