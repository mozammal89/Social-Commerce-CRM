/**
 * Table Dropdown Fix - Specifically for store-row dropdowns
 * Ensures dropdowns in tables work properly
 */

document.addEventListener('DOMContentLoaded', function() {
    // Fix for table dropdowns that aren't showing
    const tableDropdownToggles = document.querySelectorAll('.store-row .dropdown-toggle, .table .dropdown-toggle');
    
    tableDropdownToggles.forEach(function(toggle) {
        const dropdown = toggle.closest('.dropdown');
        const menu = dropdown.querySelector('.dropdown-menu');
        
        if (!dropdown || !menu) return;
        
        // Remove Bootstrap dropdown instance to prevent conflicts
        const bsInstance = bootstrap.Dropdown.getInstance(toggle);
        if (bsInstance) {
            bsInstance.dispose();
        }
        
        // Custom dropdown handling
        toggle.addEventListener('click', function(event) {
            event.preventDefault();
            event.stopPropagation();
            
            // Close all other dropdowns first
            document.querySelectorAll('.dropdown.show').forEach(function(otherDropdown) {
                if (otherDropdown !== dropdown) {
                    otherDropdown.classList.remove('show');
                    const otherMenu = otherDropdown.querySelector('.dropdown-menu');
                    if (otherMenu) {
                        otherMenu.style.display = 'none';
                    }
                }
            });
            
            // Toggle current dropdown
            const isOpen = dropdown.classList.contains('show');
            dropdown.classList.toggle('show');
            
            if (!isOpen) {
                // Show dropdown
                menu.style.display = 'block';
                menu.style.position = 'absolute';
                menu.style.zIndex = '1055';
                menu.style.left = 'auto';
                menu.style.right = '0';
                menu.style.top = '100%';
                menu.style.marginTop = '4px';
                
                // Ensure it's visible
                setTimeout(() => {
                    menu.style.opacity = '1';
                    menu.style.visibility = 'visible';
                }, 10);
            } else {
                // Hide dropdown
                menu.style.display = 'none';
                menu.style.opacity = '0';
                menu.style.visibility = 'hidden';
            }
        });
        
        // Ensure proper initial state
        menu.style.display = 'none';
        menu.style.opacity = '0';
        menu.style.visibility = 'hidden';
    });
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', function(event) {
        if (!event.target.closest('.store-row .dropdown') && !event.target.closest('.table .dropdown')) {
            document.querySelectorAll('.store-row .dropdown.show, .table .dropdown.show').forEach(function(dropdown) {
                dropdown.classList.remove('show');
                const menu = dropdown.querySelector('.dropdown-menu');
                if (menu) {
                    menu.style.display = 'none';
                    menu.style.opacity = '0';
                    menu.style.visibility = 'hidden';
                }
            });
        }
    });
    
    console.log('Table dropdown fix applied');
});