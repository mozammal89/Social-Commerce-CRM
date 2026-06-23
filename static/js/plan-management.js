/**
 * Plan Management JavaScript Module
 *
 * Provides functionality for checking plan limits and refreshing plan information
 */

// Plan Cache Management
const PlanCache = {
    currentPlan: null,
    lastCheck: null,
    cacheTimeout: 60000, // 1 minute cache timeout
    cacheKey: 'current_user_plan',

    /**
     * Get user's current plan with caching
     */
    async getCurrentPlan(forceRefresh = false) {
        const now = Date.now();
        
        // Return cached data if fresh
        if (!forceRefresh && PlanCache.currentPlan && PlanCache.lastCheck && 
            (now - PlanCache.lastCheck) < PlanCache.cacheTimeout) {
            return PlanCache.currentPlan;
        }

        try {
            const response = await fetch('/api/v1/subscriptions/current/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin',
            });

            if (response.ok) {
                const data = await response.json();
                
                PlanCache.currentPlan = data;
                PlanCache.lastCheck = now;
                
                // Cache in session storage for cross-page persistence
                try {
                    sessionStorage.setItem(PlanCache.cacheKey, JSON.stringify(data));
                } catch (e) {
                    console.warn('Failed to cache plan in session storage:', e);
                }
                
                return data;
            } else {
                console.warn('Failed to fetch current plan:', response.status);
                return null;
            }
        } catch (error) {
            console.error('Error fetching current plan:', error);
            
            // Try to get from session storage as fallback
            try {
                const cached = sessionStorage.getItem(PlanCache.cacheKey);
                if (cached) {
                    return JSON.parse(cached);
                }
            } catch (e) {
                console.warn('Failed to get plan from session storage:', e);
            }
            
            return null;
        }
    },

    /**
     * Force refresh the plan cache
     */
    async refreshPlan() {
        return await PlanCache.getCurrentPlan(true);
    },

    /**
     * Get the max stores limit from current plan
     */
    async getMaxStoresLimit() {
        const plan = await PlanCache.getCurrentPlan();
        
        if (!plan || !plan.subscription || !plan.subscription.plan) {
            // Fallback to checking plans directly
            try {
                const response = await fetch('/api/v1/subscriptions/api/limits/', {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    credentials: 'same-origin',
                });

                if (response.ok) {
                    const data = await response.json();
                    return data.limits?.max_stores || 1;
                }
            } catch (error) {
                console.error('Error fetching plan limits:', error);
            }
            
            return 1; // Default fallback
        }
        
        return plan.subscription.plan.max_stores || 1;
    },

    /**
     * Check if user can create more stores
     */
    async canCreateMoreStores(currentStoreCount = 0) {
        const maxStores = await PlanCache.getMaxStoresLimit();
        return currentStoreCount < maxStores;
    },

    /**
     * Get remaining store slots
     */
    async getRemainingStores(currentStoreCount = 0) {
        const maxStores = await PlanCache.getMaxStoresLimit();
        return maxStores - currentStoreCount;
    },

    /**
     * Clear cached plan data
     */
    clearCache() {
        PlanCache.currentPlan = null;
        PlanCache.lastCheck = null;
        try {
            sessionStorage.removeItem(PlanCache.cacheKey);
        } catch (e) {
            console.warn('Failed to clear session storage:', e);
        }
    },

    /**
     * Plan upgrade handling
     */
    onPlanUpgrade() {
        // Clear cache when user upgrades their plan
        PlanCache.clearCache();
        
        // Show success message
        notify('Your plan has been upgraded! You can now create more stores.', 'success');
        
        // Refresh plan data after a short delay
        setTimeout(() => {
            PlanCache.getCurrentPlan(true);
        }, 500);
    }
};

// Create Store Function with Plan Limit Checking
async function createStore(data) {
    try {
        // First check if user can create more stores
        const canCreate = await PlanCache.canCreateMoreStores();
        
        if (!canCreate) {
            const maxStores = await PlanCache.getMaxStoresLimit();
            
            // Show helpful error message
            if (maxStores === 1) {
                notify(`You've reached your plan's limit of ${maxStores} store. Upgrade your plan to create more stores.`, 'error');
            } else {
                const remaining = await PlanCache.getRemainingStores();
                notify(`You've reached your plan's limit of ${maxStores} stores. You have ${remaining} stores remaining.`, 'warning');
                
                // Suggest plan upgrade if they have no remaining slots
                if (remaining <= 0) {
                    notify('Upgrade your plan to create more stores', 'info');
                }
            }
            
            return { ok: false };
        }

        // Show loading state
        const submitBtn = document.querySelector('button[type="submit"]');
        if (submitBtn) {
            const originalText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Creating...';
            submitBtn.dataset.originalText = originalText;
        }

        // Create the store
        const result = await StoreAPI.createStore(data);
        
        // Clear plan cache after store creation
        PlanCache.clearCache();
        
        return result;
        
    } catch (error) {
        console.error('Error in enhanced createStore:', error);
        return { ok: false };
    } finally {
        // Reset button state
        const submitBtn = document.querySelector('button[type="submit"]');
        if (submitBtn && submitBtn.dataset.originalText) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = submitBtn.dataset.originalText;
            delete submitBtn.dataset.originalText;
        }
    }
}

// Store Manager with Plan Integration
const EnhancedStoreManager = {
    /**
     * Load and display stores with plan-aware UI
     */
    async loadStores(containerId = 'storesTable') {
        try {
            const stores = await StoreAPI.getStores();
            const container = document.getElementById(containerId);
            
            if (!container) {
                console.warn(`Container with id "${containerId}" not found`);
                return stores;
            }
            
            // Trigger custom event for stores loaded
            document.dispatchEvent(new CustomEvent('stores:loaded', { detail: stores }));
            
            // Check plan limits and update UI
            await PlanCache.getCurrentPlan();
            const remainingStores = await PlanCache.getRemainingStores(stores.length);
            
            // Update UI with plan information
            const remainingInfo = document.getElementById('remainingStores');
            if (remainingInfo) {
                remainingInfo.textContent = `${remainingStores} stores remaining`;
                if (remainingStores > 0) {
                    remainingInfo.classList.remove('text-muted');
                    remainingInfo.classList.add('text-success');
                } else if (remainingStores === 0) {
                    remainingInfo.classList.add('text-warning');
                }
            }
            
            return stores;
        } catch (error) {
            console.error('Error loading stores:', error);
            notify('Failed to load stores', 'error');
            return [];
        }
    },

    /**
     * Create a store with plan limit checking
     */
    async createStore(data, redirectTo = '/dashboard/') {
        const result = await createStore(data);
        
        if (result.ok) {
            notify('Store created successfully!', 'success');
            
            // Show next steps message
            setTimeout(() => {
                window.location.href = redirectTo;
            }, 1000);
        } else {
            // Handle specific plan-related errors
            if (result.data && result.data.error === 'plan_limit_exceeded') {
                const cap = result.data.cap || 1;
                const remaining = result.data.current || 0;
                
                if (cap === 1 && remaining >= cap) {
                    notify(`You've reached your plan's limit of ${cap} store. Upgrade your plan to create more stores.`, 'error');
                } else {
                    notify(`You can create ${cap - remaining} more store${(cap - remaining) === 1 ? '' : 's'}.`, 'warning');
                }
                
                // Suggest plan upgrade
                const upgradeBtn = document.getElementById('upgradePlanButton');
                if (upgradeBtn) {
                    upgradeBtn.style.display = 'block';
                    upgradeBtn.classList.remove('d-none');
                }
            } else {
                // Handle other errors
                let errorMessage = 'Failed to create store.';
                if (result.data && result.data.name) {
                    errorMessage += ' ' + result.data.name[0];
                } else if (result.data && result.data.detail) {
                    errorMessage += ' ' + result.data.detail;
                } else if (result.data && result.data.error) {
                    errorMessage += ' ' + result.data.error;
                }
                
                notify(errorMessage, 'error');
            }
        }
        
        return result;
    },

    /**
     * Override update, delete, switchStore with PlanCache clearing
     */
    async updateStore(storeId, data, redirectUrl = null) {
        const result = await StoreManager.updateStore(storeId, data, redirectUrl);
        PlanCache.clearCache(); // Clear plan cache on store update
        return result;
    },

    async deleteStore(storeId, storeName) {
        const result = await StoreManager.deleteStore(storeId, storeName);
        PlanCache.clearCache(); // Clear plan cache on store deletion
        return result;
    },

    async switchStore(storeId, storeName) {
        const result = await StoreManager.switchStore(storeId, storeName);
        return result;
    }
};

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Initialize enhanced store management
    if (typeof window.StoreManager !== 'undefined') {
        // Replace with enhanced version
        Object.assign(window.StoreManager, EnhancedStoreManager);
    }
    
    // Initialize forms with enhanced functionality
    if (typeof window.StoreFormHandler !== 'undefined') {
        // Replace createStore with enhanced version
        window.StoreManager.createStore = EnhancedStoreManager.createStore;
    }
    
    // Listen for plan upgrade events
    document.addEventListener('plan:upgraded', function() {
        PlanCache.onPlanUpgrade();
    });
    
    // Listen for store events that should trigger plan cache refresh
    document.addEventListener('store:created', PlanCache.clearCache);
    document.addEventListener('store:deleted', PlanCache.clearCache);
    
    // Initialize search/filter
    if (typeof window.StoreSearch !== 'undefined') {
        StoreSearch.init();
    }
});

// Export for use in templates
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        PlanCache,
        EnhancedStoreManager,
        createStore
    };
}