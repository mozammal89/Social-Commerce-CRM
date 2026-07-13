/**
 * Connected Channels — Alpine component for the channels management page.
 *
 * Lists connected accounts, shows the catalog of connectable channels,
 * opens a connect modal with platform-specific credential fields, and
 * supports enable/disable. The webhook URL for each account is computed
 * so the store owner can register it with Facebook/WhatsApp.
 *
 * Exposed to the template as ``x-data="channelsApp()"``.
 */

/* Reuse the CSRF + API helpers pattern from inbox.js (kept local so this
   file has no runtime dependency on inbox.js being loaded). */
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

/* Platform credential field definitions for the connect modal.
   Each entry drives a labeled input; only matching fields are shown. */
const CREDENTIAL_FIELDS = {
    facebook_messenger: [
        { key: 'page_id', label: 'Page ID', placeholder: 'e.g. 1029384756', help: 'The numeric Facebook Page ID.' },
        { key: 'page_access_token', label: 'Page Access Token', placeholder: 'EAAG...', help: 'A long-lived Page access token (Pages → Settings → Messenger).', secret: true },
        { key: 'app_id', label: 'App ID', placeholder: 'Numeric app id', help: 'Your Facebook App ID (optional if token is self-contained).', optional: true },
        { key: 'app_secret', label: 'App Secret', placeholder: 'App secret', help: 'Used to verify webhook signatures.', secret: true },
    ],
    whatsapp: [
        { key: 'phone_number_id', label: 'Phone Number ID', placeholder: 'e.g. 1076…', help: 'From Meta Business → WhatsApp phone number.' },
        { key: 'access_token', label: 'Access Token', placeholder: 'EAAG…', help: 'A permanent system-user access token.', secret: true },
        { key: 'waba_id', label: 'WABA ID', placeholder: 'WhatsApp Business Account ID', help: 'Optional but recommended.', optional: true },
        { key: 'app_secret', label: 'App Secret', placeholder: 'App secret', help: 'Used to verify webhook signatures.', secret: true, optional: true },
    ],
};

const CHANNEL_ICONS = {
    facebook_messenger: 'bi-messenger',
    whatsapp: 'bi-whatsapp',
    instagram: 'bi-instagram',
    telegram: 'bi-telegram',
    email: 'bi-envelope',
    sms: 'bi-chat-square-text',
    other: 'bi-chat',
};

const STATUS_META = {
    connected: { label: 'Connected', cls: 'status-badge--active' },
    disconnected: { label: 'Disabled', cls: 'status-badge--inactive' },
    error: { label: 'Error', cls: 'status-badge--danger' },
    pending: { label: 'Pending', cls: 'status-badge--pending' },
    expired: { label: 'Expired', cls: 'status-badge--inactive' },
};

function channelsApp() {
    return {
        storeId: '',
        apiBase: '/api/v1/messaging',

        accounts: [],
        catalog: [],                // connectable channels (enabled, not connected)
        loading: false,
        error: '',

        // Super-admin platform catalog management
        isSuperuser: false,
        adminCatalog: [],           // ALL channels (enabled + disabled)
        togglingId: null,           // id of the channel currently being toggled

        // Connect modal state
        showConnect: false,
        connectChannel: null,       // the selected catalog Channel
        connectName: '',
        connectExternalId: '',
        connectVerifyToken: '',
        connectCreds: {},           // {field_key: value}
        connecting: false,

        /* ---- lifecycle ---- */
        async init() {
            const el = this.$el;
            this.storeId = el.dataset.storeId || '';
            this.isSuperuser = el.dataset.isSuperuser === 'true';
            if (!this.storeId) { this.error = 'No store selected.'; return; }
            // Accounts must load before the catalog so we can hide already-
            // connected channels from the "Available" section.
            await this.loadAccounts();
            await this.loadCatalog();
            // Super-admin: load the full catalog (incl. disabled) for the
            // platform management section at the bottom of the page.
            if (this.isSuperuser) await this.loadAdminCatalog();
            // Generate a default verify token suggestion
            this.connectVerifyToken = 'crm_' + Math.random().toString(36).slice(2, 14);
        },

        /* ---- data loading ---- */
        async loadAccounts() {
            this.loading = true; this.error = '';
            try {
                const data = await api(`${this.apiBase}/channels/`, { storeId: this.storeId });
                this.accounts = data.results || data || [];
            } catch (err) { this.error = err.message; }
            finally { this.loading = false; }
        },

        async loadCatalog() {
            // Fetch the enabled catalog channels from the API (the super-
            // admin's on/off gate is respected server-side). Then filter out
            // the ones this store has already connected so the "Available"
            // section only shows connectable, not-yet-connected channels.
            try {
                const data = await api(`${this.apiBase}/catalog/`, { storeId: this.storeId });
                const all = data.results || data || [];
                const connectedTypes = new Set(this.accounts.map(a => a.channel?.channel_type));
                this.catalog = all.filter(c => !connectedTypes.has(c.channel_type));
            } catch { this.catalog = []; }
        },

        async loadAdminCatalog() {
            // Super-admin only: fetch the FULL catalog (enabled + disabled)
            // for the platform management section. No store header needed
            // (the catalog is global).
            try {
                const data = await api(`${this.apiBase}/admin/channels/`);
                this.adminCatalog = data.results || data || [];
            } catch { this.adminCatalog = []; }
        },

        async adminToggle(channel, enable) {
            // Flip a channel's is_enabled platform-wide. Super-admin only
            // (the endpoint enforces it too).
            this.togglingId = channel.id;
            try {
                const updated = await api(`${this.apiBase}/admin/channels/${channel.id}/toggle/`, {
                    method: 'PATCH', body: { is_enabled: enable },
                });
                const idx = this.adminCatalog.findIndex(c => c.id === channel.id);
                if (idx !== -1) this.adminCatalog.splice(idx, 1, updated);
                this.notify(`${channel.name} ${enable ? 'enabled' : 'disabled'} for all stores.`, 'success');
                // Refresh the connectable catalog so the change is reflected.
                await this.loadCatalog();
            } catch (err) {
                // Revert the switch on failure.
                channel.is_enabled = !enable;
                this.notify(err.message, 'error');
            } finally {
                this.togglingId = null;
            }
        },

        /* ---- connect modal ---- */
        openConnect(channelSlug) {
            const ch = this.catalog.find(c => c.slug === channelSlug);
            if (!ch) return;
            this.connectChannel = ch;
            this.connectName = '';
            this.connectExternalId = '';
            this.connectCreds = {};
            this.showConnect = true;
        },

        credentialFields() {
            if (!this.connectChannel) return [];
            return CREDENTIAL_FIELDS[this.connectChannel.channel_type] || [];
        },

        async submitConnect() {
            if (!this.connectChannel || this.connecting) return;
            // Validate required fields
            const missing = this.credentialFields().filter(f => !f.optional && !this.connectCreds[f.key]);
            if (missing.length) { this.notify('Please fill in all required fields.', 'warning'); return; }
            if (!this.connectName.trim()) { this.notify('Please enter an account name.', 'warning'); return; }
            if (!this.connectExternalId.trim()) { this.notify('Please enter the external ID.', 'warning'); return; }

            this.connecting = true;
            try {
                await api(`${this.apiBase}/channels/`, {
                    method: 'POST',
                    storeId: this.storeId,
                    body: {
                        channel_slug: this.connectChannel.slug,
                        external_id: this.connectExternalId.trim(),
                        name: this.connectName.trim(),
                        credentials: { ...this.connectCreds },
                        webhook_verify_token: this.connectVerifyToken,
                    },
                });
                this.showConnect = false;
                this.notify(`${this.connectChannel.name} connected successfully.`, 'success');
                await this.loadAccounts();
                await this.loadCatalog();
            } catch (err) {
                this.notify(err.message, 'error');
            } finally {
                this.connecting = false;
            }
        },

        /* ---- enable / disable ---- */
        async toggleStatus(account) {
            const newStatus = account.status === 'connected' ? 'disconnected' : 'connected';
            try {
                await api(`${this.apiBase}/channels/${account.id}/`, {
                    method: 'PATCH',
                    storeId: this.storeId,
                    body: { status: newStatus },
                });
                account.status = newStatus;
                this.notify(`Channel ${newStatus === 'connected' ? 'enabled' : 'disabled'}.`, 'success');
            } catch (err) { this.notify(err.message, 'error'); }
        },

        async disconnect(account) {
            // Use the project's central confirm modal (not browser confirm()).
            const ok = await window.confirmAction({
                title: 'Disconnect channel?',
                message: `Disconnect "${account.name}"? You can re-enable it later from the channel list — credentials are kept.`,
                confirmText: 'Disconnect',
                confirmClass: 'btn-danger',
            });
            if (!ok) return;
            try {
                await api(`${this.apiBase}/channels/${account.id}/`, {
                    method: 'DELETE',
                    storeId: this.storeId,
                });
                // Disconnect is a soft-disable (status -> disconnected), so the
                // account stays in the list with a "Disabled" badge rather than
                // vanishing. Reload to reflect the persisted status.
                await this.loadAccounts();
                await this.loadCatalog();
                this.notify(`"${account.name}" disconnected.`, 'success');
            } catch (err) { this.notify(err.message, 'error'); }
        },

        /* ---- helpers ---- */
        webhookUrl(account) {
            if (!account.id) return '';
            const proto = location.protocol === 'https:' ? 'https' : 'http';
            return `${proto}://${location.host}/messaging/webhooks/${account.channel?.slug}/${account.id}/`;
        },

        copyWebhook(account) {
            const url = this.webhookUrl(account);
            navigator.clipboard?.writeText(url).then(
                () => this.notify('Webhook URL copied.', 'success'),
                () => this.notify('Copy failed — select and copy manually.', 'error'),
            );
        },

        channelIcon(account) {
            return CHANNEL_ICONS[account.channel?.channel_type] || 'bi-chat';
        },

        statusMeta(status) {
            return STATUS_META[status] || STATUS_META.pending;
        },

        /** Delegate to the project's global notification system. */
        notify(message, type = 'info') {
            if (typeof window.showNotification === 'function') {
                window.showNotification(message, type);
            } else {
                console.log(`[${type}] ${message}`);
            }
        },
    };
}

window.channelsApp = channelsApp;
