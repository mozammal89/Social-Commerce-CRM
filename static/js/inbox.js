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

// Brand colors per channel — applied to icons so users can scan the
// conversation list / customer panel and instantly spot which channel a
// thread belongs to. Matches the official brand palette for each
// platform; falls back to the muted text color for unknown channels.
const CHANNEL_COLORS = {
    facebook_messenger: '#0084FF',  // Messenger blue
    whatsapp: '#25D366',            // WhatsApp green
    instagram: '#E1306C',           // Instagram pink/red
    telegram: '#0088CC',            // Telegram blue
    email: '#EA4335',               // Gmail-style red
    sms: '#4F46E5',                 // Indigo (generic)
    tiktok: '#000000',              // TikTok black
    live_chat: '#0EA5E9',           // Sky blue
    other: 'var(--text-muted)',
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

        isMobileView: false,        // Mobile: true when detail view is active
        activeConversationId: null,
        activeConversation: null,
        messages: [],
        loadingMessages: false,
        loadingMoreMessages: false,
        hasMoreMessages: true,
        currentPage: 1,            // Current page number (for reverse pagination)
        totalPages: 1,             // Total pages available
        _autoFillAttempts: 0,      // Counter for auto-fill attempts
        replyText: '',
        sending: false,
        threadError: '',

        notes: [],
        loadingNotes: false,
        newNote: '',
        showNotes: false,
        savingNote: false,

        customer: {},              // Always an object to prevent null reference errors
        loadingCustomer: false,
        refreshingIdentity: null,  // identity_id currently being refreshed (for spinner)
        refreshNotice: '',         // transient feedback message under Channels

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
            this.setupScrollHandler();
        },

        setupScrollHandler() {
            // Remove existing listener if any
            if (this._scrollHandler && this._scrollElement) {
                this._scrollElement.removeEventListener('scroll', this._scrollHandler);
            }

            // Debounced scroll handler for loading more messages
            let scrollTimeout;
            this._scrollHandler = () => {
                const threadEl = document.getElementById('thread-messages');
                if (!threadEl || this.loadingMessages || this.loadingMoreMessages || !this.hasMoreMessages) return;
                if (this.currentPage <= 1) return;  // Already on first page

                // When near the top (within 100px), load more messages
                const scrollTop = threadEl.scrollTop;
                if (scrollTop < 100) {
                    if (scrollTimeout) clearTimeout(scrollTimeout);
                    scrollTimeout = setTimeout(() => {
                        this.loadMoreMessages();
                    }, 300);  // Increased debounce to prevent rapid-fire requests
                }
            };

            // Set up the scroll observer after DOM is ready
            this.$nextTick(() => {
                const threadEl = document.getElementById('thread-messages');
                if (threadEl) {
                    this._scrollElement = threadEl;
                    threadEl.addEventListener('scroll', this._scrollHandler, { passive: true });
                    console.log('[Inbox] Scroll handler attached to thread-messages', {
                        hasMoreMessages: this.hasMoreMessages,
                        currentPage: this.currentPage,
                        scrollTop: threadEl.scrollTop
                    });
                } else {
                    console.warn('[Inbox] thread-messages element not found');
                }
            });
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
                this.syncBadge();
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
            this.customer = {};
            this.notes = [];
            this.showNotes = false;
            this.isMobileView = true;  // Enter mobile detail view
            this.loadMessages();
            // Re-setup scroll handler for the new conversation
            this.$nextTick(() => this.setupScrollHandler());
            // Mark as read when opened (best-effort; ignore failures).
            if (conv.unread_count > 0) this.markRead(conv.id);
        },

        backToList() {
            this.isMobileView = false;  // Return to list on mobile
            this.activeConversationId = null;
            this.activeConversation = null;
            this.messages = [];
            this.customer = {};
            this.notes = [];
            this.showNotes = false;
        },

        /* ================================================================
         * Message thread
         * ================================================================ */
        async loadMessages() {
            if (!this.activeConversationId) return;
            this.loadingMessages = true;
            this.messages = [];
            this.currentPage = 1;
            this.hasMoreMessages = false;  // Will update based on pagination
            this._autoFillAttempts = 0;  // Reset auto-fill attempts
            try {
                // First, fetch to get total count and determine the last page
                const data = await api(`${this.apiBase}/conversations/${this.activeConversationId}/messages/`, {
                    storeId: this.storeId
                });

                // Calculate total pages from count
                const totalCount = data.count || 0;
                const pageSize = data.results?.length || 20;
                this.totalPages = Math.ceil(totalCount / pageSize);

                if (this.totalPages > 1) {
                    // Load the last page first (most recent messages)
                    this.currentPage = this.totalPages;
                    const lastPageData = await api(`${this.apiBase}/conversations/${this.activeConversationId}/messages/?page=${this.currentPage}`, {
                        storeId: this.storeId
                    });
                    // Don't reverse - API returns ascending order (oldest first), which is correct for chat
                    this.messages = lastPageData.results || [];
                    // There are more pages if current page > 1
                    this.hasMoreMessages = this.currentPage > 1;

                    // Schedule auto-fill check after DOM updates (using $nextTick)
                    this.$nextTick(() => {
                        setTimeout(() => this._checkAndFillThread(), 100);
                    });
                } else {
                    // Single page - API returns ascending order, which is correct
                    this.messages = data.results || data || [];
                    // No more pages available
                    this.hasMoreMessages = false;
                }

                console.log('[Inbox] Loaded messages', {
                    totalPages: this.totalPages,
                    currentPage: this.currentPage,
                    hasMoreMessages: this.hasMoreMessages,
                    messageCount: this.messages.length
                });

                // Conversation carries the customer id — load the profile once.
                if (this.activeConversation && this.activeConversation.customer_id) {
                    this.loadCustomer(this.activeConversation.customer_id);
                }
                // Use the layout-settled scroll so the first paint of
                // the messages is also at the bottom. For single-page
                // conversations this is the final state; for multi-page
                // ones the auto-fill chain will re-scroll after each
                // prepend via _scrollToBottomSettled.
                this.$nextTick(() => this._scrollToBottomSettled());
            } catch (err) {
                this.threadError = err.message;
            } finally {
                this.loadingMessages = false;
            }
        },

        _checkAndFillThread() {
            // Check if thread needs more messages to be properly scrollable
            const threadEl = document.getElementById('thread-messages');
            if (!threadEl) return;

            // Require a scroll buffer: content should be 1.5x the viewport height
            // This ensures there's meaningful scrollable content above
            const scrollBuffer = threadEl.clientHeight * 0.5;
            const hasEnoughContent = threadEl.scrollHeight >= (threadEl.clientHeight + scrollBuffer);

            if (hasEnoughContent || !this.hasMoreMessages || this._autoFillAttempts >= 5) {
                console.log('[Inbox] Auto-fill check complete', {
                    hasEnoughContent,
                    scrollHeight: threadEl.scrollHeight,
                    clientHeight: threadEl.clientHeight,
                    required: threadEl.clientHeight + scrollBuffer,
                    hasMoreMessages: this.hasMoreMessages,
                    attempts: this._autoFillAttempts
                });
                return;
            }

            // Load previous page
            this._autoFillAttempts++;
            console.log('[Inbox] Thread not filled, auto-loading previous page', this.currentPage - 1);
            this._loadPreviousPageSilent();
        },

        _loadPreviousPageSilent() {
            // Load previous page during the INITIAL auto-fill (not user
            // scrolling). The user just clicked a conversation, so they
            // want to see the most recent messages — we ALWAYS scroll to
            // the bottom after prepending older ones. We do NOT try to
            // "preserve" the scroll offset because (a) the user is at
            // the bottom anyway, and (b) capturing an offset before an
            // async network call and applying it after is racy: the
            // viewport may have moved, layout may have shifted, etc.
            // Forcing scroll-to-bottom is simpler and deterministic.
            const prevPage = this.currentPage - 1;
            if (prevPage < 1) {
                this.hasMoreMessages = false;
                return;
            }

            api(`${this.apiBase}/conversations/${this.activeConversationId}/messages/?page=${prevPage}`, {
                storeId: this.storeId
            }).then(data => {
                if (data.results && data.results.length > 0) {
                    // Prepend older messages.
                    this.messages = [...data.results, ...this.messages];
                    this.currentPage = prevPage;
                    this.hasMoreMessages = prevPage > 1;

                    // Force scroll to bottom AFTER the new content has
                    // been laid out. Double-rAF guarantees the browser
                    // has painted the new DOM (a single $nextTick or
                    // rAF can fire before layout settles, which is what
                    // made the previous "preserve distance" fix flaky).
                    this.$nextTick(() => this._scrollToBottomSettled(() => {
                        setTimeout(() => this._checkAndFillThread(), 50);
                    }));
                }
            }).catch(err => {
                console.error('[Inbox] Failed to load previous page silently:', err);
            });
        },

        /**
         * Scroll to bottom after the browser has definitely laid out
         * the current DOM. Uses double requestAnimationFrame so the
         * second rAF fires in the frame AFTER paint — guaranteeing
         * scrollHeight reflects the just-rendered messages. The
         * optional callback runs after the scroll, so callers can
         * chain follow-up work (e.g. another auto-fill iteration).
         */
        _scrollToBottomSettled(cb) {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    const el = document.getElementById('thread-messages');
                    if (el) el.scrollTop = el.scrollHeight;
                    if (typeof cb === 'function') cb();
                });
            });
        },

        async loadMoreMessages() {
            if (!this.activeConversationId || this.loadingMoreMessages || !this.hasMoreMessages) {
                console.log('[Inbox] loadMoreMessages skipped', {
                    hasConversationId: !!this.activeConversationId,
                    loadingMoreMessages: this.loadingMoreMessages,
                    hasMoreMessages: this.hasMoreMessages
                });
                return;
            }

            console.log('[Inbox] Loading more messages', {
                currentPage: this.currentPage,
                conversationId: this.activeConversationId
            });

            this.loadingMoreMessages = true;
            try {
                // Load the previous page
                const prevPage = this.currentPage - 1;
                if (prevPage < 1) {
                    this.hasMoreMessages = false;
                    return;
                }

                const data = await api(`${this.apiBase}/conversations/${this.activeConversationId}/messages/?page=${prevPage}`, {
                    storeId: this.storeId
                });

                console.log('[Inbox] Loaded page', prevPage, 'with', data.results?.length, 'messages');

                if (data.results && data.results.length > 0) {
                    // Store current scroll position
                    const threadEl = document.getElementById('thread-messages');
                    const oldScrollHeight = threadEl ? threadEl.scrollHeight : 0;

                    // Prepend new messages (API returns ascending order, which is correct)
                    // Previous page messages are older, so they go at the beginning
                    this.messages = [...data.results, ...this.messages];
                    this.currentPage = prevPage;

                    // Restore scroll position to maintain user's view
                    this.$nextTick(() => {
                        if (threadEl) {
                            const newScrollHeight = threadEl.scrollHeight;
                            threadEl.scrollTop = newScrollHeight - oldScrollHeight;
                        }
                    });
                }

                // Update hasMoreMessages based on whether we've reached page 1
                this.hasMoreMessages = prevPage > 1;
                console.log('[Inbox] Updated hasMoreMessages to', this.hasMoreMessages);
            } catch (err) {
                console.error('[Inbox] Failed to load more messages:', err);
            } finally {
                this.loadingMoreMessages = false;
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
            } catch { this.customer = {}; } finally { this.loadingCustomer = false; }
        },

        /**
         * Trigger an on-demand profile refresh for one channel identity.
         * Enqueues the enrich_customer_identity Celery task and polls
         * the customer endpoint a few seconds later to surface the new
         * name/avatar. Source-of-truth rule still applies (agent-edited
         * fields are never overwritten by the sync).
         */
        async refreshIdentity(identityId) {
            if (!this.customer.id || !identityId) return;
            try {
                await api(
                    `${this.apiBase}/customers/${this.customer.id}/identities/${identityId}/refresh/`,
                    { method: 'POST', storeId: this.storeId },
                );
                return true;
            } catch (err) {
                this.notify(err.message || 'Could not queue profile refresh.', 'error');
                return false;
            }
        },

        /**
         * Refresh ALL channel identities for the active customer at once.
         * Used by the single "Refresh profile" button in the customer
         * panel header — one click triggers a sync for every connected
         * channel (Facebook, WhatsApp, etc.). Shows a spinner on the
         * button via `refreshingIdentity` (set to a non-null sentinel
         * while any refresh is in-flight), then re-fetches the customer
         * to surface the new data.
         */
        async refreshAllIdentities() {
            if (!this.customer.id || !this.customer.channel_identities?.length) return;
            this.refreshingIdentity = 'all';  // sentinel: non-null spins the header button
            this.refreshNotice = '';
            try {
                // Fire all refresh requests in parallel — each enqueues
                // an independent Celery task on the backend.
                const results = await Promise.allSettled(
                    this.customer.channel_identities.map(ci => this.refreshIdentity(ci.id))
                );
                const ok = results.filter(r => r.status === 'fulfilled' && r.value).length;
                const total = this.customer.channel_identities.length;
                this.refreshNotice = `Refreshed ${ok}/${total} channel${total === 1 ? '' : 's'}. Profile will update shortly.`;
                // Re-fetch after a short delay to pick up the refreshed data.
                setTimeout(() => {
                    this.loadCustomer(this.customer.id);
                    this.refreshingIdentity = null;
                }, 2500);
            } catch (err) {
                this.refreshingIdentity = null;
                this.notify(err.message || 'Could not queue profile refresh.', 'error');
            }
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
                    // Generate a unique ID for the reaction object (required for Alpine x-for key)
                    msg.reactions.push({
                        id: `reaction-${payload.message_id}-${payload.emoji}-${Date.now()}`,
                        emoji: payload.emoji,
                        reactor_type: 'customer'
                    });
                }
            }
        },

        onMessageNew(msg) {
            console.log('[Inbox] WebSocket message received:', {
                id: msg.id,
                message_type: msg.message_type,
                has_text: !!msg.text,
                has_attachments: !!msg.attachments,
                attachments_count: msg.attachments?.length || 0,
                attachments: msg.attachments
            });
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
            this.syncBadge();
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
        /** Brand color for the channel's icon. Use via:
         *  `<i class="bi" :class="channelIcon(conv)" :style="{ color: channelColor(conv) }"></i>` */
        channelColor(conv) {
            return CHANNEL_COLORS[conv.channel?.channel_type] || 'var(--text-muted)';
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
        formatFileSize(bytes) {
            if (!bytes) return '';
            const units = ['B', 'KB', 'MB', 'GB'];
            let size = bytes;
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex++;
            }
            return `${size.toFixed(1)} ${units[unitIndex]}`;
        },
        getAttachmentType(att) {
            // Helper to determine attachment type safely
            if (!att) return 'unknown';
            if (att.attachment_type === 'image') return 'image';
            if (att.attachment_type === 'video') return 'video';
            if (att.attachment_type === 'audio') return 'audio';
            if (att.attachment_type === 'sticker') return 'image';  // Treat stickers as images

            // Check mime_type if available
            if (att.mime_type && typeof att.mime_type === 'string') {
                if (att.mime_type.indexOf('image/') === 0) return 'image';
                if (att.mime_type.indexOf('video/') === 0) return 'video';
                if (att.mime_type.indexOf('audio/') === 0) return 'audio';
            }

            return 'file';
        },
        isImageAttachment(att) {
            return this.getAttachmentType(att) === 'image';
        },
        get unreadTotal() {
            return this.conversations.reduce((n, c) => n + (c.unread_count || 0), 0);
        },
        /** Push the authoritative unread total into the global sidebar
         *  badge store so the nav counter stays correct while the inbox
         *  is open (reads, assignments, status changes all flow through). */
        syncBadge() {
            const store = window.Alpine && Alpine.store('inboxBadge');
            if (store) store.set(this.unreadTotal);
        },
    };
}

// Expose for the template (Alpine picks up globally-scoped functions).
window.inboxApp = inboxApp;
