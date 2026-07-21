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
   Each entry drives a labeled input; only matching fields are shown.

   The "secret" flag renders a field as a password input; the "optional"
   flag controls the required-asterisk + the submitConnect validation.

   Definitions mirror each adapter's ``authenticate_account`` contract:
     - Instagram   uses Meta OAuth (same shape as FB Messenger, with an
                   ig_user_id instead of page_id).
     - Telegram    uses a single bot_token + optional webhook secret.
     - TikTok      uses OAuth 2.0 (access_token + refresh_token) scoped
                   to a business_id, with client_key/client_secret for
                   webhook HMAC verification and token refresh. */
const CREDENTIAL_FIELDS = {
    facebook_messenger: [
        { key: 'page_id', label: 'Page Scrape ID', placeholder: 'e.g. 1029384756', help: 'Optional: Page ID for API scraping (different from your Page Numeric ID above).', optional: true },
        { key: 'page_access_token', label: 'Page Access Token', placeholder: 'EAAG...', help: 'A long-lived Page access token (Pages → Settings → Messenger).', secret: true },
        { key: 'app_id', label: 'App ID', placeholder: 'Numeric app id', help: 'Your Facebook App ID (optional if token is self-contained).', optional: true },
        { key: 'app_secret', label: 'App Secret', placeholder: 'App secret', help: 'Used to verify webhook signatures.', secret: true },
    ],
    whatsapp: [
        { key: 'phone_number_id', label: 'Phone Number ID (from Phone Number list)', placeholder: 'e.g. 1076…', help: 'The Phone Number ID from your WhatsApp Phone Numbers list (different from WABA ID above).', secret: false },
        { key: 'access_token', label: 'Permanent Access Token', placeholder: 'EAAG…', help: 'A permanent system-user access token for sending messages.', secret: true },
        { key: 'waba_id', label: 'WABA ID (optional)', placeholder: 'WhatsApp Business Account ID', help: 'Optional but recommended for advanced features.', optional: true },
        { key: 'app_secret', label: 'App Secret', placeholder: 'App secret', help: 'Used to verify webhook signatures.', secret: true, optional: true },
    ],
    instagram: [
        { key: 'page_access_token', label: 'Page Access Token', placeholder: 'EAAG...', help: 'A long-lived Page access token for the Page linked to your Instagram Professional account.', secret: true },
        { key: 'app_id', label: 'App ID', placeholder: 'Numeric app id', help: 'Your Meta App ID (the same app used for Messenger).', optional: true },
        { key: 'app_secret', label: 'App Secret', placeholder: 'App secret', help: 'Used to verify webhook signatures.', secret: true },
    ],
    telegram: [
        { key: 'bot_token', label: 'Bot Token', placeholder: '123456789:ABC-DEF...', help: 'The token issued by @BotFather when you created the bot.', secret: true },
        { key: 'secret_token', label: 'Webhook Secret Token', placeholder: 'Optional random string', help: 'Optional. If set, Telegram sends it in the X-Telegram-Bot-Api-Secret-Token header for verification.', optional: true },
        { key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://your-host/.../telegram/<account-id>/', help: 'Optional. Auto-registered with Telegram on connect when provided.', optional: true },
    ],
    tiktok: [
        { key: 'access_token', label: 'Access Token', placeholder: 'act.…', help: 'A freshly-exchanged OAuth access token for your TikTok Business account.', secret: true },
        { key: 'refresh_token', label: 'Refresh Token', placeholder: 'rft.…', help: 'Paired with the access token; used to auto-refresh it before expiry.', secret: true },
        { key: 'client_key', label: 'Client Key', placeholder: 'Numeric app key', help: 'Your TikTok app\'s client key (from the developer console).' },
        { key: 'client_secret', label: 'Client Secret', placeholder: 'App secret', help: 'Your TikTok app\'s client secret; also used to sign webhook payloads.', secret: true },
        { key: 'open_id', label: 'Open ID', placeholder: 'e.g. 7000…', help: 'Optional. The merchant\'s TikTok user id; auto-detected from the token when omitted.', optional: true },
    ],
};

// User-friendly labels for credential field names
const CREDENTIAL_LABELS = {
    // Facebook
    'page_id': 'Page ID',
    'page_access_token': 'Page Access Token',
    'app_id': 'App ID',
    'app_secret': 'App Secret',
    'user_access_token': 'User Access Token',
    'user_token_expires_at': 'User Token Expires',
    'page_token_obtained_at': 'Page Token Obtained',
    // WhatsApp
    'phone_number_id': 'Phone Number ID',
    'access_token': 'Access Token',
    'waba_id': 'WABA ID',
    'verify_token': 'Verify Token',
    // Instagram
    'ig_user_id': 'Instagram Account ID',
    // Telegram
    'bot_token': 'Bot Token',
    'bot_id': 'Bot ID',
    'bot_username': 'Bot Username',
    'secret_token': 'Webhook Secret Token',
    'webhook_url': 'Webhook URL',
    // TikTok
    'client_key': 'Client Key',
    'client_secret': 'Client Secret',
    'business_id': 'Business ID',
    'open_id': 'Open ID',
    'refresh_token': 'Refresh Token',
    'access_token_expires_at': 'Access Token Expires',
    'refresh_token_expires_at': 'Refresh Token Expires',
    // Generic
    'token': 'Token',
    'secret': 'Secret',
    'key': 'API Key',
    'id': 'ID',
};

const CHANNEL_ICONS = {
    facebook_messenger: 'bi-messenger',
    whatsapp: 'bi-whatsapp',
    instagram: 'bi-instagram',
    telegram: 'bi-telegram',
    tiktok: 'bi-tiktok',
    email: 'bi-envelope',
    sms: 'bi-chat-square-text',
    live_chat: 'bi-chat-left-text',
    other: 'bi-chat',
};

const STATUS_META = {
    connected: { label: 'Connected', cls: 'status-badge--active' },
    disconnected: { label: 'Disabled', cls: 'status-badge--inactive' },
    error: { label: 'Error', cls: 'status-badge--danger' },
    pending: { label: 'Pending', cls: 'status-badge--pending' },
    expired: { label: 'Expired', cls: 'status-badge--inactive' },
};

/* Per-channel connect-modal metadata:
     - externalIdLabel  : label for the External ID field
     - externalIdPlaceholder : input placeholder
     - externalIdHelp   : where to find the value
     - namePlaceholder  : placeholder for the account-name field
   Used by connectMeta(type) so the connect modal adapts to any channel
   without per-channel template branches. */
const CONNECT_META = {
    facebook_messenger: {
        externalIdLabel: 'Facebook Page Numeric ID',
        externalIdPlaceholder: 'e.g. 1029384756',
        externalIdHelp: 'From Facebook Page Settings → About section (Page ID).',
        namePlaceholder: 'e.g. Main Facebook Page',
    },
    whatsapp: {
        externalIdLabel: 'Phone Number ID',
        externalIdPlaceholder: 'e.g. 1076498231564',
        externalIdHelp: 'From WhatsApp Manager → Phone Numbers (NOT the E.164 number).',
        namePlaceholder: 'e.g. Sales WhatsApp',
    },
    instagram: {
        externalIdLabel: 'Instagram Account ID (ig-user-id)',
        externalIdPlaceholder: 'e.g. 17841005822304914',
        externalIdHelp: 'From Meta Business Settings → Instagram Accounts, or Instagram Graph API.',
        namePlaceholder: 'e.g. Main Instagram Account',
    },
    telegram: {
        externalIdLabel: 'Bot ID',
        externalIdPlaceholder: 'e.g. 123456789',
        externalIdHelp: 'The numeric prefix of the bot token (everything before the colon). Auto-detected on connect when blank.',
        namePlaceholder: 'e.g. Support Bot',
    },
    tiktok: {
        externalIdLabel: 'Business ID',
        externalIdPlaceholder: 'e.g. 7001234567890',
        externalIdHelp: 'From TikTok Business Center → Business Account Info.',
        namePlaceholder: 'e.g. TikTok Business',
    },
};

// Fallback for channels without an explicit entry (email, sms, live_chat, …).
const CONNECT_META_DEFAULT = {
    externalIdLabel: 'External Account ID',
    externalIdPlaceholder: 'Platform account id',
    externalIdHelp: 'The platform-side identifier for this account.',
    namePlaceholder: 'e.g. My channel account',
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
        verifyingId: null,          // id of the account being verified

        // Connect modal state
        showConnect: false,
        connectChannel: null,       // the selected catalog Channel
        connectName: '',
        connectExternalId: '',
        connectVerifyToken: '',
        connectCreds: {},           // {field_key: value}
        connecting: false,

        // Settings modal state
        showSettings: false,
        settingsAccount: null,      // the account being edited
        settingsData: null,         // { credentials: {...}, webhook: {...} }
        settingsTab: 'details',
        loadingSettings: false,
        updateFieldKey: '',         // stores the actual field key for API calls
        updateValue: '',
        newVerifyToken: '',
        showVerifyToken: false,
        updatingCredentials: false,

        // WhatsApp onboarding / migration guide modal
        showWaGuide: false,

        // Channel-aware setup guide: showGuide controls visibility,
        // guideChannel holds the channel_type whose guide to render
        // (e.g. 'whatsapp', 'facebook_messenger'). Each channel ships
        // its own guide modal in the template, shown when its type matches.
        showGuide: false,
        guideChannel: null,

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

        /* ---- setup guide (channel-aware) ---- */
        openGuide(channelType) {
            // channelType may come from a catalog item, a connected
            // account, or a raw string. Accept either an object with
            // ``channel_type`` / ``channel.channel_type`` or the string.
            let type = channelType;
            if (type && typeof type === 'object') {
                type = type.channel_type || (type.channel && type.channel.channel_type) || type.channel_type;
            }
            if (!type) return;
            this.guideChannel = type;
            this.showGuide = true;
            // Keep the legacy WhatsApp-only flag in sync so existing
            // template bindings keep working during the transition.
            this.showWaGuide = (type === 'whatsapp');
        },

        closeGuide() {
            this.showGuide = false;
            this.showWaGuide = false;
            this.guideChannel = null;
        },

        guideFor(accountOrChannel) {
            // Convenience for templates: returns true if the guide
            // currently open is for the given account/channel.
            const type = accountOrChannel?.channel_type ||
                         accountOrChannel?.channel?.channel_type || '';
            return this.showGuide && this.guideChannel === type;
        },

        /* Channels with a dedicated setup-guide modal in the template.
           Kept in sync with the markup so showGenericGuide() picks the
           right modal. Add a new entry here when you ship a dedicated
           guide modal for a channel. */
        guideForChannel(type) {
            return [
                'whatsapp',
                'facebook_messenger',
                'instagram',
                'telegram',
                'tiktok',
            ].includes(type);
        },

        /* True when the generic guide modal should be shown instead of a
           dedicated one (i.e. the user opened a channel without its own
           guide, or picked "General help"). Drives the generic modal's
           visibility in the template. */
        showGenericGuide() {
            const t = this.guideChannel;
            return this.showGuide && (t === 'generic' || (t && !this.guideForChannel(t)));
        },

        credentialFields() {
            if (!this.connectChannel) return [];
            return CREDENTIAL_FIELDS[this.connectChannel.channel_type] || [];
        },

        smallCredentialFieldPairs() {
            // Group small fields (non-secret, non-token) into pairs for inline rendering
            const fields = this.credentialFields().filter(f => !f.secret && !f.key.includes('token'));
            const pairs = [];
            for (let i = 0; i < fields.length; i += 2) {
                pairs.push([fields[i], fields[i + 1] || null]);
            }
            return pairs;
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

        async verifyChannel(account) {
            // Live-check the credentials against the platform. Sets the
            // account status to connected/error and shows the result.
            // Prevent duplicate calls and check for valid account
            if (this.verifyingId) return; // Already verifying
            if (!account || !account.id) {
                this.notify('Cannot verify: account information is missing.', 'error');
                return;
            }
            this.verifyingId = account.id;
            try {
                const updated = await api(`${this.apiBase}/channels/${account.id}/verify/`, {
                    method: 'POST', storeId: this.storeId,
                });
                // Patch the in-memory account so the card updates live.
                Object.assign(account, updated);
                if (updated.status === 'connected') {
                    this.notify(`Connection verified${updated.metadata?.verified_name ? ' as ' + updated.metadata.verified_name : ''}.`, 'success');
                } else {
                    const msg = updated.error_message || 'invalid credentials';
                    // If the error hints at a Business App migration issue,
                    // proactively open the migration guide for WhatsApp.
                    if (account.channel?.channel_type === 'whatsapp' &&
                        /migrat|not registered|business app|cloud api/i.test(msg)) {
                        this.openGuide('whatsapp');
                    }
                    this.notify(`Verification failed: ${msg}.`, 'error');
                }
            } catch (err) { this.notify(err.message, 'error'); }
            finally { this.verifyingId = null; }
        },

        /* ---- settings modal ---- */
        async openSettings(account) {
            this.settingsAccount = account;
            this.settingsData = null;
            this.settingsTab = 'details';
            this.loadingSettings = true;
            this.updateFieldKey = '';
            this.updateValue = '';
            this.newVerifyToken = '';
            this.showVerifyToken = false;
            // Show modal AFTER setting account to ensure reactive consistency
            this.$nextTick(() => {
                this.showSettings = true;
            });

            try {
                const data = await api(`${this.apiBase}/channels/${account.id}/settings/`, {
                    storeId: this.storeId,
                });
                this.settingsData = data;
            } catch (err) {
                this.notify(err.message, 'error');
                this.showSettings = false;
            } finally {
                this.loadingSettings = false;
            }
        },

        getCredentialLabel(key) {
            return CREDENTIAL_LABELS[key] || key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' ');
        },

        editCredential(key) {
            this.updateFieldKey = key;
            this.updateField = this.getCredentialLabel(key);
            this.updateValue = '';
            // Focus the input after Alpine updates
            this.$nextTick(() => {
                const input = document.querySelector('input[type="password"]');
                if (input) input.focus();
            });
        },

        async submitCredentialUpdate() {
            if (!this.updateFieldKey || !this.updateValue || this.updatingCredentials) return;

            this.updatingCredentials = true;
            try {
                const data = await api(`${this.apiBase}/channels/${this.settingsAccount.id}/credentials/`, {
                    method: 'POST',
                    storeId: this.storeId,
                    body: {
                        credentials: {
                            [this.updateFieldKey]: this.updateValue,
                        },
                    },
                });
                this.notify('Credential updated successfully.', 'success');
                this.updateFieldKey = '';
                this.updateValue = '';
                // Reload settings to show updated masked value
                await this.openSettings(this.settingsAccount);
                // Reload accounts to reflect any status changes
                await this.loadAccounts();
            } catch (err) {
                this.notify(err.message, 'error');
            } finally {
                this.updatingCredentials = false;
            }
        },

        toggleVerifyToken() {
            this.showVerifyToken = !this.showVerifyToken;
        },

        generateVerifyToken() {
            // Generate a random token similar to the connect modal
            this.newVerifyToken = 'crm_' + Math.random().toString(36).slice(2, 14);
        },

        async submitVerifyTokenUpdate() {
            if (!this.newVerifyToken || this.updatingCredentials) return;

            this.updatingCredentials = true;
            try {
                const data = await api(`${this.apiBase}/channels/${this.settingsAccount.id}/credentials/`, {
                    method: 'POST',
                    storeId: this.storeId,
                    body: {
                        webhook_verify_token: this.newVerifyToken,
                    },
                });
                this.notify('Verify token updated successfully.', 'success');
                this.newVerifyToken = '';
                // Reload settings to show updated masked value
                await this.openSettings(this.settingsAccount);
            } catch (err) {
                this.notify(err.message, 'error');
            } finally {
                this.updatingCredentials = false;
            }
        },

        copyWebhookUrl() {
            const url = this.settingsData?.webhook?.url || '';
            navigator.clipboard?.writeText(url).then(
                () => this.notify('Webhook URL copied.', 'success'),
                () => this.notify('Copy failed — select and copy manually.', 'error'),
            );
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

        /* Per-channel text for the connect modal (external-id label,
           placeholder, help, account-name placeholder). Falls back to
           a generic entry so any channel renders correctly without a
           dedicated CONNECT_META entry. */
        connectMeta(type) {
            return CONNECT_META[type] || CONNECT_META_DEFAULT;
        },

        statusMeta(status) {
            return STATUS_META[status] || STATUS_META.pending;
        },

        maskToken(token) {
            if (!token) return '(not set)';
            if (token === '(in account settings)') return token;
            if (token.length > 8) {
                return `${token.slice(0, 4)}${'*'.repeat(token.length - 8)}${token.slice(-4)}`;
            } else if (token.length > 4) {
                return `${token.slice(0, 2)}${'*'.repeat(token.length - 4)}${token.slice(-2)}`;
            }
            return '****';
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
