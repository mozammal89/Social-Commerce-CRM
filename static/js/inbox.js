/**
 * Unified Inbox — Alpine.js single-page component.
 *
 * Drives the three-pane inbox (conversation list | message thread |
 * customer panel) over the DRF messaging API + the WebSocket realtime
 * layer. Session-cookie auth (no JWT in the browser); CSRF token is
 * attached to every unsafe request via the standard project helper.
 *
 * Exposed to the template as ``x-data="inboxApp()"`` — Alpine auto-
 * initializes the returned object and calls ``init()``.
 */

/* ------------------------------------------------------------------ */
/* CSRF helper (matches the convention in static/js/stores.js).        */
/* ------------------------------------------------------------------ */
function getCSRFToken() {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input) return input.value;
    const cookies = document.cookie.split(';');
    for (const c of cookies) {
        const [name, value] = c.trim().split('=');
        if (name === 'csrftoken') return decodeURIComponent(value);
    }
    return null;
}

/* ------------------------------------------------------------------ */
/* Minimal API wrapper: JSON in/out, credentials + CSRF on writes.     */
/* ------------------------------------------------------------------ */
async function api(path, { method = 'GET', body, storeId } = {}) {
    const headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
    if (storeId) headers['X-Store-Id'] = storeId;
    if (method !== 'GET') headers['X-CSRFToken'] = getCSRFToken();
    const opts = { method, headers, credentials: 'same-origin' };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    if (resp.status === 204) return null;
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        const msg = data.detail || data.message || `Request failed (${resp.status})`;
        const err = new Error(msg);
        err.status = resp.status;
        err.data = data;
        throw err;
    }
    return data;
}

/* ------------------------------------------------------------------ */
/* Static label maps (avoid hardcoding strings in markup).             */
/* ------------------------------------------------------------------ */
const CHANNEL_ICONS = {
    facebook_messenger: 'bi-messenger',
    whatsapp: 'bi-whatsapp',
    instagram: 'bi-instagram',
    telegram: 'bi-telegram',
    email: 'bi-envelope',
    sms: 'bi-chat-square-text',
    tiktok: 'bi-tiktok',
    live_chat: 'bi-chat-left',
    other: 'bi-chat',
};

const STATUS_META = {
    open: { label: 'Open', cls: 'status-badge--active', icon: 'bi-chat-dots' },
    pending: { label: 'Pending', cls: 'status-badge--pending', icon: 'bi-clock' },
    resolved: { label: 'Resolved', cls: 'status-badge--active', icon: 'bi-check2-circle' },
    closed: { label: 'Closed', cls: 'status-badge--inactive', icon: 'bi-lock' },
    spam: { label: 'Spam', cls: 'status-badge--danger', icon: 'bi-slash-circle' },
};

const DELIVERY_META = {
    pending: { label: 'Pending', icon: 'bi-clock' },
    sent: { label: 'Sent', icon: 'bi-check2' },
    delivered: { label: 'Delivered', icon: 'bi-check2-all' },
    read: { label: 'Read', icon: 'bi-check2-all text-primary' },
    failed: { label: 'Failed', icon: 'bi-x-circle text-danger' },
    undelivered: { label: 'Undelivered', icon: 'bi-exclamation-circle text-danger' },
};

/* ------------------------------------------------------------------ */
/* The Alpine component factory.                                       */
/* ------------------------------------------------------------------ */
function inboxApp() {
    return {
        /* ---- config (set from template data-* attrs) ---- */
        storeId: '',
        currentUserId: '',
        apiBase: '/api/v1/messaging',

        /* ---- state ---- */
        conversations: [],
        loadingList: false,
        listError: '',
        searchQuery: '',
        statusFilter: '',
        channelFilter: '',
        assigneeFilter: '',         // '' | 'me' | 'unassigned'

        activeConversationId: null,
        activeConversation: null,
        messages: [],
        loadingMessages: false,
        replyText: '',
        sending: false,
        threadError: '',

        notes: [],
        loadingNotes: false,
        newNote: '',
        showNotes: false,
        savingNote: false,

        customer: null,
        loadingCustomer: false,

        channels: [],               // connected accounts (for the channel filter)

        ws: null,
        wsConnected: false,
        wsReconnectTimer: null,

        /* ================================================================
         * Lifecycle
         * ================================================================ */
        init() {
            // Read config from the root element's data attributes.
            const root = this.$el;
            this.storeId = root.dataset.storeId || '';
            this.currentUserId = root.dataset.currentUserId || '';
            if (!this.storeId) {
                this.notify('No store selected. Switch to a store to view the inbox.', 'error');
                return;
            }
            this.loadConversations();
            this.loadChannels();
            this.connectWebSocket();
        },

        /* ================================================================
         * Conversation list
         * ================================================================ */
        async loadConversations() {
            this.loadingList = true;
            this.listError = '';
            try {
                const params = new URLSearchParams();
                if (this.statusFilter) params.set('status', this.statusFilter);
                if (this.channelFilter) params.set('channel_id', this.channelFilter);
                if (this.assigneeFilter === 'unassigned') params.set('unassigned', 'true');
                else if (this.assigneeFilter === 'me') params.set('assigned_to', this.currentUserId);
                if (this.searchQuery.trim()) params.set('q', this.searchQuery.trim());
                const qs = params.toString();
                const data = await api(`${this.apiBase}/conversations/${qs ? '?' + qs : ''}`, { storeId: this.storeId });
                this.conversations = data.results || data || [];
                // NOTE: do NOT clear the active conversation here. A list
                // reload (e.g. triggered by a WS event for a *new* convo,
                // or a filter change) may not include the currently-open
                // conversation in the result set — but the user is still
                // viewing it. Clearing it would wipe the thread they're
                // reading ("messages go away" bug). The active selection
                // is only changed by an explicit user click.
            } catch (err) {
                this.listError = err.message;
            } finally {
                this.loadingList = false;
            }
        },

        selectConversation(conv) {
            if (this.activeConversationId === conv.id) return;
            this.activeConversationId = conv.id;
            this.activeConversation = conv;
            this.messages = [];
            this.threadError = '';
            this.customer = null;
            this.notes = [];
            this.showNotes = false;
            this.loadMessages();
            // Mark as read when opened (best-effort; ignore failures).
            if (conv.unread_count > 0) this.markRead(conv.id);
        },

        /* ================================================================
         * Message thread
         * ================================================================ */
        async loadMessages() {
            if (!this.activeConversationId) return;
            this.loadingMessages = true;
            try {
                const data = await api(`${this.apiBase}/conversations/${this.activeConversationId}/messages/`, { storeId: this.storeId });
                this.messages = (data.results || data || []).slice().reverse();
                // Conversation carries the customer id — load the profile once.
                if (this.activeConversation && this.activeConversation.customer_id) {
                    this.loadCustomer(this.activeConversation.customer_id);
                }
                this.$nextTick(() => this.scrollToBottom());
            } catch (err) {
                this.threadError = err.message;
            } finally {
                this.loadingMessages = false;
            }
        },

        async sendReply() {
            const text = this.replyText.trim();
            if (!text || !this.activeConversationId || this.sending) return;
            this.sending = true;
            this.threadError = '';
            try {
                const msg = await api(`${this.apiBase}/conversations/${this.activeConversationId}/messages/`, {
                    method: 'POST', body: { text }, storeId: this.storeId,
                });
                // The realtime broadcast may have already added it; dedupe by id.
                if (!this.messages.find(m => m.id === msg.id)) this.messages.push(msg);
                this.replyText = '';
                this.touchConversation({ last_message_preview: text, last_message_direction: 'outbound', message_count: (this.activeConversation.message_count || 0) + 1 });
                this.$nextTick(() => this.scrollToBottom());
            } catch (err) {
                this.threadError = err.message;
            } finally {
                this.sending = false;
            }
        },

        async markRead(conversationId) {
            try {
                await api(`${this.apiBase}/conversations/${conversationId}/read/`, { method: 'POST', storeId: this.storeId });
                this.touchConversation({ unread_count: 0 }, conversationId);
            } catch { /* best-effort */ }
        },

        /* ================================================================
         * Conversation actions (assign / status)
         * ================================================================ */
        async assignToMe() {
            if (!this.activeConversationId) return;
            try {
                const updated = await api(`${this.apiBase}/conversations/${this.activeConversationId}/assign/`, {
                    method: 'POST', body: { agent_id: this.currentUserId }, storeId: this.storeId,
                });
                this.activeConversation = { ...this.activeConversation, ...updated };
                this.touchConversation({ assigned_to: updated.assigned_to });
                this.notify('Conversation assigned to you.', 'success');
            } catch (err) { this.notify(err.message, 'error'); }
        },

        async unassign() {
            if (!this.activeConversationId) return;
            try {
                const updated = await api(`${this.apiBase}/conversations/${this.activeConversationId}/assign/`, {
                    method: 'POST', body: { agent_id: null }, storeId: this.storeId,
                });
                this.activeConversation = { ...this.activeConversation, ...updated };
                this.touchConversation({ assigned_to: null });
                this.notify('Conversation unassigned.', 'success');
            } catch (err) { this.notify(err.message, 'error'); }
        },

        async setStatus(newStatus) {
            if (!this.activeConversationId) return;
            try {
                const updated = await api(`${this.apiBase}/conversations/${this.activeConversationId}/`, {
                    method: 'PATCH', body: { status: newStatus }, storeId: this.storeId,
                });
                this.activeConversation = { ...this.activeConversation, status: updated.status };
                this.touchConversation({ status: updated.status });
                this.notify(`Status set to ${STATUS_META[newStatus]?.label || newStatus}.`, 'success');
            } catch (err) { this.notify(err.message, 'error'); }
        },

        /* ================================================================
         * Internal notes
         * ================================================================ */
        async toggleNotes() {
            this.showNotes = !this.showNotes;
            if (this.showNotes && this.notes.length === 0) await this.loadNotes();
        },

        async loadNotes() {
            if (!this.activeConversationId) return;
            this.loadingNotes = true;
            try {
                const data = await api(`${this.apiBase}/conversations/${this.activeConversationId}/notes/`, { storeId: this.storeId });
                this.notes = data.results || data || [];
            } catch { /* best-effort */ } finally { this.loadingNotes = false; }
        },

        async addNote() {
            const body = this.newNote.trim();
            if (!body || !this.activeConversationId || this.savingNote) return;
            this.savingNote = true;
            try {
                const note = await api(`${this.apiBase}/conversations/${this.activeConversationId}/notes/`, {
                    method: 'POST', body: { body }, storeId: this.storeId,
                });
                this.notes.unshift(note);
                this.newNote = '';
            } catch (err) { this.notify(err.message, 'error'); }
            finally { this.savingNote = false; }
        },

        /* ================================================================
         * Customer panel
         * ================================================================ */
        async loadCustomer(customerId) {
            this.loadingCustomer = true;
            try {
                this.customer = await api(`${this.apiBase}/customers/${customerId}/`, { storeId: this.storeId });
            } catch { this.customer = null; } finally { this.loadingCustomer = false; }
        },

        /* ================================================================
         * Connected channels (for the filter dropdown)
         * ================================================================ */
        async loadChannels() {
            try {
                const data = await api(`${this.apiBase}/channels/`, { storeId: this.storeId });
                this.channels = data.results || data || [];
            } catch { /* filter just won't populate */ }
        },

        /* ================================================================
         * WebSocket realtime
         * ================================================================ */
        connectWebSocket() {
            if (this.ws) return;
            const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
            const url = `${scheme}://${location.host}/ws/messaging/inbox/?store=${this.storeId}`;
            try {
                this.ws = new WebSocket(url);
            } catch (err) {
                this.scheduleReconnect();
                return;
            }
            this.ws.onopen = () => { this.wsConnected = true; };
            this.ws.onclose = () => {
                this.wsConnected = false;
                this.ws = null;
                this.scheduleReconnect();
            };
            this.ws.onerror = () => { /* onclose will handle reconnect */ };
            this.ws.onmessage = (evt) => {
                try { this.handleWsEvent(JSON.parse(evt.data)); }
                catch { /* ignore malformed */ }
            };
        },

        scheduleReconnect() {
            if (this.wsReconnectTimer) return;
            this.wsReconnectTimer = setTimeout(() => {
                this.wsReconnectTimer = null;
                this.connectWebSocket();
            }, 5000);
        },

        handleWsEvent(payload) {
            // Inbox broadcasts carry a flat message/conversation payload.
            // The service layer sends {id, conversation_id, direction, text, ...}
            // for message.new and the conversation brief for conversation.updated.
            if (payload.reaction && payload.message_id) {
                this.onReaction(payload);
            } else if (payload.conversation_id) {
                this.onMessageNew(payload);
            } else if (payload.id && payload.status !== undefined) {
                this.onConversationUpdated(payload);
            } else if (payload.message_ids && payload.status) {
                this.onDeliveryUpdated(payload);
            }
        },

        onReaction(payload) {
            // Update the message's reactions array in place (live).
            const msg = this.messages.find(m => m.id === payload.message_id);
            if (!msg) return;
            if (!msg.reactions) msg.reactions = [];
            if (payload.reaction === 'unreact') {
                msg.reactions = msg.reactions.filter(r => r.emoji !== payload.emoji);
            } else {
                if (!msg.reactions.find(r => r.emoji === payload.emoji)) {
                    msg.reactions.push({ emoji: payload.emoji, reactor_type: 'customer' });
                }
            }
        },

        onMessageNew(msg) {
            if (msg.conversation_id === this.activeConversationId) {
                if (!this.messages.find(m => m.id === msg.id)) {
                    this.messages.push(msg);
                    this.$nextTick(() => this.scrollToBottom());
                    // Inbound in an open thread → auto mark read.
                    if (msg.direction === 'inbound') this.markRead(msg.conversation_id);
                }
            }
            // Bump the conversation's preview/last-activity in the list.
            this.touchConversation({
                last_message_preview: msg.text || msg.message_type,
                last_message_direction: msg.direction,
                unread_count: (msg.direction === 'inbound' && msg.conversation_id !== this.activeConversationId)
                    ? '?+1' : undefined,
            }, msg.conversation_id);
            // If this message created a new conversation (not in list), reload.
            if (!this.conversations.find(c => c.id === msg.conversation_id)) {
                this.loadConversations();
            }
        },

        onConversationUpdated(conv) {
            this.touchConversation(conv, conv.id);
            if (this.activeConversationId === conv.id) {
                this.activeConversation = { ...this.activeConversation, ...conv };
            }
        },

        onDeliveryUpdated(payload) {
            for (const m of this.messages) {
                if (payload.message_ids.includes(m.id) || payload.message_ids.includes(m.external_id)) {
                    m.delivery_status = payload.status;
                }
            }
        },

        /* ================================================================
         * Helpers
         * ================================================================ */
        /** Patch a conversation in the list (and active) with partial data. */
        touchConversation(patch, conversationId) {
            const id = conversationId || this.activeConversationId;
            const idx = this.conversations.findIndex(c => c.id === id);
            if (idx === -1) return;
            const conv = { ...this.conversations[idx] };
            for (const [k, v] of Object.entries(patch)) {
                if (v === '?+1') conv[k] = (conv[k] || 0) + 1;
                else conv[k] = v;
            }
            conv.last_message_at = new Date().toISOString();
            this.conversations.splice(idx, 1, conv);
            // Re-sort by last_message_at descending.
            this.conversations.sort((a, b) => (b.last_message_at || '').localeCompare(a.last_message_at || ''));
        },

        scrollToBottom() {
            const el = document.getElementById('thread-messages');
            if (el) el.scrollTop = el.scrollHeight;
        },

        /** Delegate to the project's global notification system. */
        notify(message, type = 'info') {
            if (typeof window.showNotification === 'function') {
                window.showNotification(message, type);
            }
        },

        /* ---- display helpers (used in template) ---- */
        channelIcon(conv) {
            return CHANNEL_ICONS[conv.channel?.channel_type] || 'bi-chat';
        },
        statusMeta(status) {
            return STATUS_META[status] || STATUS_META.open;
        },
        deliveryMeta(status) {
            return DELIVERY_META[status] || DELIVERY_META.pending;
        },
        fmtTime(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            const now = new Date();
            const sameDay = d.toDateString() === now.toDateString();
            return sameDay ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                           : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
        },
        get unreadTotal() {
            return this.conversations.reduce((n, c) => n + (c.unread_count || 0), 0);
        },
    };
}

// Expose for the template (Alpine picks up globally-scoped functions).
window.inboxApp = inboxApp;
