/**
 * Customers — Alpine component for the customers management page.
 *
 * Lists customers in the store with search, and opens a slide-over
 * timeline drawer showing the unified timeline (messages, notes,
 * activities) with the ability to merge duplicates.
 *
 * Exposed to the template as ``x-data="customersApp()"``.
 */

function getCSRFToken() {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input) return input.value;
    for (const c of document.cookie.split(';')) {
        const [name, value] = c.trim().split('=');
        if (name === 'csrftoken') return decodeURIComponent(value);
    }
    return null;
}

async function api(path, { method = 'GET', body, storeId } = {}) {
    const headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
    if (storeId) headers['X-Store-Id'] = storeId;
    if (method !== 'GET') headers['X-CSRFToken'] = getCSRFToken();
    const opts = { method, headers, credentials: 'same-origin' };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data.detail || data.message || `Request failed (${resp.status})`);
    }
    return data;
}

const CHANNEL_ICONS = {
    facebook_messenger: 'bi-messenger', whatsapp: 'bi-whatsapp',
    instagram: 'bi-instagram', telegram: 'bi-telegram', email: 'bi-envelope',
    sms: 'bi-chat-square-text', other: 'bi-chat',
};

function customersApp() {
    return {
        storeId: '',
        apiBase: '/api/v1/messaging',

        customers: [],
        loading: false,
        error: '',
        searchQuery: '',

        // Timeline drawer state
        drawerOpen: false,
        activeCustomer: null,
        timeline: [],
        loadingTimeline: false,

        // Merge state
        showMerge: false,
        mergeSearch: '',
        mergeCandidates: [],
        merging: false,

        toasts: [],

        init() {
            this.storeId = this.$el.dataset.storeId || '';
            if (!this.storeId) { this.error = 'No store selected.'; return; }
            this.loadCustomers();
        },

        async loadCustomers() {
            this.loading = true; this.error = '';
            try {
                const params = new URLSearchParams();
                if (this.searchQuery.trim()) params.set('q', this.searchQuery.trim());
                const qs = params.toString();
                const data = await api(`${this.apiBase}/customers/${qs ? '?' + qs : ''}`, { storeId: this.storeId });
                this.customers = data.results || data || [];
            } catch (err) { this.error = err.message; }
            finally { this.loading = false; }
        },

        async openTimeline(customer) {
            this.activeCustomer = customer;
            this.drawerOpen = true;
            this.timeline = [];
            this.loadingTimeline = true;
            try {
                const data = await api(`${this.apiBase}/customers/${customer.id}/timeline/`, { storeId: this.storeId });
                this.timeline = data.items || [];
            } catch (err) { this.toast(err.message, 'danger'); }
            finally { this.loadingTimeline = false; }
        },

        closeDrawer() {
            this.drawerOpen = false;
            this.showMerge = false;
        },

        /* ---- merge ---- */
        async searchMergeCandidates() {
            if (!this.mergeSearch.trim()) { this.mergeCandidates = []; return; }
            try {
                const data = await api(`${this.apiBase}/customers/?q=${encodeURIComponent(this.mergeSearch)}`, { storeId: this.storeId });
                // Exclude the active customer from candidates.
                this.mergeCandidates = (data.results || data || []).filter(c => c.id !== this.activeCustomer.id);
            } catch { /* best-effort */ }
        },

        async mergeWith(duplicateId) {
            if (!this.activeCustomer || !duplicateId) return;
            if (!confirm('Merge this customer into the selected one? The duplicate will be retired and all its history moved over.')) return;
            this.merging = true;
            try {
                const primary = await api(`${this.apiBase}/customers/${this.activeCustomer.id}/merge/`, {
                    method: 'POST', storeId: this.storeId, body: { duplicate_id: duplicateId },
                });
                this.activeCustomer = primary;
                this.toast('Customers merged successfully.', 'success');
                this.showMerge = false;
                this.mergeCandidates = [];
                this.mergeSearch = '';
                await this.loadCustomers();
                await this.openTimeline(primary);
            } catch (err) { this.toast(err.message, 'danger'); }
            finally { this.merging = false; }
        },

        /* ---- helpers ---- */
        initials(name) {
            if (!name) return '?';
            return name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
        },

        channelIcon(ci) {
            return CHANNEL_ICONS[ci?.channel?.channel_type] || 'bi-chat';
        },

        fmtTime(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
        },

        fmtDateTime(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        },

        timelineIcon(item) {
            if (item.type === 'message') return 'bi-chat-left-text';
            if (item.type === 'note') return 'bi-sticky';
            if (item.type === 'activity') return 'bi-activity';
            return 'bi-circle';
        },

        toast(message, type = 'info') {
            const id = Date.now() + Math.random();
            this.toasts.push({ id, message, type });
            setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 4000);
        },
    };
}

window.customersApp = customersApp;
