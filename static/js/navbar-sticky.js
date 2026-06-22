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
});

// Export for potential use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { handleNavbarScroll };
}