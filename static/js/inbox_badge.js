/**
 * Unified Inbox — sidebar unread badge.
 *
 * Keeps the "Unified Inbox" nav badge in sync with the store-wide
 * unread-message total. The initial value is rendered server-side by the
 * ``unread_inbox_count`` context processor; this module exposes a global
 * Alpine store (``Alpine.store('inboxBadge')``) that the sidebar badge
 * binds to, and keeps it live via the inbox WebSocket.
 *
 * On the inbox page itself the inbox SPA (``inboxApp``) is the source of
 * truth — it calls ``store.set(unreadTotal)`` on every list mutation, so
 * we deliberately skip opening a second WS connection there.
 *
 * De-duplication: a single inbound message can reach this client more
 * than once (duplicate WS connections, script re-injection after an
 * HTMX swap, or a re-delivered platform webhook that shares the same
 * message id). The store tracks message ids it has already counted so a
 * repeat delivery is ignored — this is what makes the off-inbox badge
 * match the (self-healing) inbox SPA count.
 */
(function () {
    document.addEventListener('alpine:init', () => {
        const badge = document.getElementById('inbox-unread-badge');
        const initialCount = badge ? (parseInt(badge.dataset.initialCount, 10) || 0) : 0;
        const storeId = badge ? (badge.dataset.storeId || '') : '';

        Alpine.store('inboxBadge', {
            count: initialCount,
            _seen: new Set(),
            set(n) { this.count = Math.max(0, n | 0); },
            increment(n = 1) { this.count += n; },
            decrement(n = 1) { this.count = Math.max(0, this.count - n); },
            /** Count one inbound message, ignoring ids we've already
             *  seen. Returns true if the count actually changed. */
            countInbound(messageId) {
                if (!messageId) return false;
                if (this._seen.has(messageId)) return false;
                this._seen.add(messageId);
                // Bound the id cache so a very long session doesn't grow
                // it without limit (drop the oldest entries).
                if (this._seen.size > 5000) {
                    const drop = this._seen.size - 4000;
                    let i = 0;
                    for (const id of this._seen) {
                        this._seen.delete(id);
                        if (++i >= drop) break;
                    }
                }
                this.count += 1;
                return true;
            },
        });

        // No store context (e.g. login pages) or the inbox SPA owns the
        // badge on its own page — nothing to keep live here.
        if (!storeId || document.getElementById('inbox-root')) return;

        connectBadgeWebSocket(storeId);
    });

    function connectBadgeWebSocket(storeId) {
        // Guard against a second connection if this script is re-run
        // (e.g. HTMX swap re-injecting the page scripts while the JS
        // context persists). One live socket is all we need.
        if (window.__inboxBadgeWs) return;
        const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${scheme}://${location.host}/ws/messaging/inbox/?store=${storeId}`;
        let ws = null;
        let reconnectTimer = null;

        function connect() {
            if (ws || window.__inboxBadgeWs) return;
            try {
                ws = new WebSocket(url);
                window.__inboxBadgeWs = ws;
            } catch (err) {
                scheduleReconnect();
                return;
            }
            ws.onmessage = (evt) => {
                let payload;
                try { payload = JSON.parse(evt.data); }
                catch { return; }
                handleEvent(payload);
            };
            ws.onclose = () => {
                if (window.__inboxBadgeWs === ws) window.__inboxBadgeWs = null;
                ws = null;
                scheduleReconnect();
            };
            ws.onerror = () => { /* onclose handles reconnect */ };
        }

        function scheduleReconnect() {
            if (reconnectTimer) return;
            reconnectTimer = setTimeout(() => {
                reconnectTimer = null;
                connect();
            }, 5000);
        }

        function handleEvent(payload) {
            const store = window.Alpine && Alpine.store('inboxBadge');
            if (!store) return;
            // A new inbound message means one more unread store-wide —
            // but only the first time we see its id.
            if (payload && payload.conversation_id && payload.direction === 'inbound') {
                const counted = store.countInbound(payload.id);
                // Play notification sound + browser notification when the
                // user is NOT on the inbox page (the inbox SPA handles
                // its own notifications when it's open).
                if (counted && window.InboxNotifications) {
                    window.InboxNotifications.onIncomingMessage({
                        senderName: 'New message',
                        preview: payload.text || payload.message_type || '',
                        conversationId: payload.conversation_id,
                    });
                }
            }
        }

        connect();
    }
})();
