/**
 * Navbar Sticky Fix & Dropdown Enhancement
 * Ensures the navbar remains properly sticky and dropdowns work correctly
 */

document.addEventListener('DOMContentLoaded', function() {
    const navbar = document.querySelector('.navbar');
    const body = document.body;
    
    if (!navbar) return;
    
    // Function to handle navbar visibility
    function handleNavbarScroll() {
        const scrollY = window.scrollY;
        
        // Always ensure navbar is visible and fixed
        navbar.style.position = 'fixed';
        navbar.style.top = '0';
        navbar.style.left = '0';
        navbar.style.right = '0';
        navbar.style.zIndex = '1000';
        navbar.style.transform = 'translateY(0)';
        navbar.style.opacity = '1';
        navbar.style.visibility = 'visible';
        
        // Add shadow when scrolled
        if (scrollY > 10) {
            navbar.style.boxShadow = '0 2px 10px rgba(0, 0, 0, 0.1)';
        } else {
            navbar.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.05)';
        }
    }
    
    // Initial setup
    handleNavbarScroll();
    
    // Add scroll event listener
    let ticking = false;
    window.addEventListener('scroll', function() {
        if (!ticking) {
            window.requestAnimationFrame(function() {
                handleNavbarScroll();
                ticking = false;
            });
            ticking = true;
        }
    }, { passive: true });
    
    // Ensure dropdown elements work properly with Bootstrap
    const dropdowns = navbar.querySelectorAll('.dropdown');
    dropdowns.forEach(dropdown => {
        const toggle = dropdown.querySelector('[data-bs-toggle="dropdown"]');
        
        if (toggle) {
            // Let Bootstrap handle everything, just ensure positioning is correct
            toggle.style.position = 'relative';
            toggle.style.zIndex = '1';
        }
    });
    
    // Ensure navbar container allows overflow for dropdowns
    navbar.style.overflow = 'visible';
    
    // Handle mobile search panel
    const mobileSearchPanel = document.getElementById('mobileSearchPanel');
    if (mobileSearchPanel) {
        mobileSearchPanel.style.position = 'fixed';
        mobileSearchPanel.style.zIndex = '999';
    }
    
    console.log('Navbar sticky fix applied (Bootstrap-friendly)');

    // Store dropdown search functionality
    const storeSearchInput = document.getElementById('storeSearchInput');
    const storeList = document.getElementById('storeList');
    const storeDropdownMenu = document.getElementById('storeDropdownMenu');

    if (storeSearchInput && storeList) {
        // Store all store items for filtering
        const storeItems = Array.from(storeList.querySelectorAll('li'));
        const noResultsItem = document.createElement('li');
        noResultsItem.className = 'store-dropdown-no-results';
        noResultsItem.textContent = 'No stores found';
        noResultsItem.style.display = 'none';

        // Add no results item to the list
        storeList.appendChild(noResultsItem);

        // Focus search input when dropdown opens
        const storeDropdownToggle = document.querySelector('.navbar-store-button');
        if (storeDropdownToggle) {
            storeDropdownToggle.addEventListener('click', function() {
                setTimeout(() => {
                    if (storeDropdownMenu && storeDropdownMenu.classList.contains('show')) {
                        storeSearchInput.focus();
                    }
                }, 100);
            });
        }

        // Filter stores on input
        storeSearchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase().trim();
            let hasResults = false;

            storeItems.forEach(item => {
                if (item.classList.contains('store-dropdown-no-results')) return;

                const storeName = item.getAttribute('data-store-name') || '';
                const storeLink = item.querySelector('span');
                const linkText = storeLink ? storeLink.textContent.toLowerCase() : '';

                if (storeName.includes(searchTerm) || linkText.includes(searchTerm)) {
                    item.style.display = '';
                    hasResults = true;
                } else {
                    item.style.display = 'none';
                }
            });

            // Show/hide no results message
            if (noResultsItem) {
                noResultsItem.style.display = hasResults ? 'none' : '';
            }
        });

        // Clear search when dropdown closes
        storeDropdownMenu.addEventListener('hidden.bs.dropdown', function() {
            storeSearchInput.value = '';
            storeItems.forEach(item => {
                if (!item.classList.contains('store-dropdown-no-results')) {
                    item.style.display = '';
                }
            });
            if (noResultsItem) {
                noResultsItem.style.display = 'none';
            }
        });
    }
});

// Export for potential use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { handleNavbarScroll };
}