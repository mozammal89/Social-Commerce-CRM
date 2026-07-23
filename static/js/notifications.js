/**
 * Inbox notification service — sound + browser notifications.
 *
 * Design decisions:
 * - **Sounds** are synthesized at runtime via the Web Audio API (no MP3
 *   files to download/host). Two distinct tones:
 *     • incoming  — a gentle two-note rising chime (C5 → E5)
 *     • outgoing  — a short soft blip (G4)
 * - **Browser notifications** use the native Notification API. Shown
 *   only when the tab is hidden so the user isn't spammed while actively
 *   chatting. Clicking a notification focuses the window.
 * - **Preferences** are persisted in localStorage (no backend changes
 *   needed). Keys are namespaced under ``inbox_`` to avoid collisions.
 * - The module is framework-agnostic (plain JS). The inbox Alpine SPA
 *   and the global inbox_badge.js both call the same hooks, so sounds
 *   fire whether or not the user is on the inbox page.
 *
 * Public API:
 *   window.InboxNotifications.playIncoming(opts)
 *   window.InboxNotifications.playOutgoing()
 *   window.InboxNotifications.showBrowserNotification(title, body, opts)
 *   window.InboxNotifications.getPrefs()
 *   window.InboxNotifications.setPref(key, value)
 *   window.InboxNotifications.requestPermission()
 *   window.InboxNotifications.permissionState()   // 'granted'|'denied'|'default'|'unsupported'
 *
 * Hooks (called from inbox.js / inbox_badge.js):
 *   window.InboxNotifications.onIncomingMessage({ senderName, preview, conversationId })
 *   window.InboxNotifications.onOutgoingMessage()
 */
(function () {
    'use strict';

    const STORAGE_PREFIX = 'inbox_';
    const DEFAULT_PREFS = {
        sound_enabled: true,          // master sound toggle
        sound_volume: 0.5,            // 0.0 – 1.0
        sound_incoming: true,         // play on new inbound message
        sound_outgoing: false,        // play when agent sends a reply
        browser_notifications: false, // native OS notifications
        permission_prompt_dismissed: false, // don't re-ask after user dismisses
    };

    // ------------------------------------------------------------------
    // Preference storage (localStorage-backed)
    // ------------------------------------------------------------------
    function getPrefs() {
        const prefs = { ...DEFAULT_PREFS };
        for (const key of Object.keys(DEFAULT_PREFS)) {
            const raw = localStorage.getItem(STORAGE_PREFIX + key);
            if (raw !== null) {
                try {
                    prefs[key] = JSON.parse(raw);
                } catch {
                    prefs[key] = raw;
                }
            }
        }
        return prefs;
    }

    function setPref(key, value) {
        if (!(key in DEFAULT_PREFS)) return;
        localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
        // Live-apply certain prefs
        if (key === 'sound_volume') _masterGain = null; // force re-create gain node
    }

    // ------------------------------------------------------------------
    // Web Audio — synthesized tones
    // ------------------------------------------------------------------
    let _audioCtx = null;
    let _masterGain = null;

    function _getCtx() {
        if (!_audioCtx) {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return null;
            _audioCtx = new AC();
        }
        // Resume if suspended (browsers auto-suspend until a user gesture).
        if (_audioCtx.state === 'suspended') {
            _audioCtx.resume().catch(() => {});
        }
        return _audioCtx;
    }

    function _getMasterGain() {
        const ctx = _getCtx();
        if (!ctx) return null;
        if (!_masterGain) {
            _masterGain = ctx.createGain();
            const prefs = getPrefs();
            _masterGain.gain.value = prefs.sound_volume;
            _masterGain.connect(ctx.destination);
        }
        return _masterGain;
    }

    /**
     * Play a simple tone with an ADSR envelope.
     * @param freq      Frequency in Hz.
     * @param start     Start time offset (seconds) from now.
     * @param duration  Tone duration (seconds).
     * @param type      Oscillator type ('sine'|'triangle'|'square'|'sawtooth').
     * @param peakGain  Peak amplitude 0–1 (pre-master-volume).
     */
    function _playTone(freq, start, duration, type, peakGain) {
        const ctx = _getCtx();
        const master = _getMasterGain();
        if (!ctx || !master) return;

        const t0 = ctx.currentTime + start;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = type;
        osc.frequency.value = freq;

        // ADSR envelope — smooth attack/release avoids harsh clicks.
        gain.gain.setValueAtTime(0, t0);
        gain.gain.linearRampToValueAtTime(peakGain, t0 + 0.01);   // 10 ms attack
        gain.gain.exponentialRampToValueAtTime(0.001, t0 + duration); // exp decay

        osc.connect(gain);
        gain.connect(master);
        osc.start(t0);
        osc.stop(t0 + duration + 0.05);
    }

    /** Rising two-note chime (C5 523.25 → E5 659.25) for incoming. */
    function _playIncomingTone() {
        const prefs = getPrefs();
        if (!prefs.sound_enabled || !prefs.sound_incoming) return;
        // Two overlapping sine notes for a pleasant "ding-dong".
        _playTone(523.25, 0.00, 0.15, 'sine', 0.6);
        _playTone(659.25, 0.10, 0.25, 'sine', 0.5);
    }

    /** Short blip (A4 440.00) for outgoing — louder + longer. */
    function _playOutgoingTone() {
        const prefs = getPrefs();
        if (!prefs.sound_enabled || !prefs.sound_outgoing) return;
        _playTone(440.00, 0.00, 0.15, 'sine', 0.7);
    }

    // ------------------------------------------------------------------
    // Browser (native OS) notifications
    // ------------------------------------------------------------------
    function _isSupported() {
        return typeof window !== 'undefined' && 'Notification' in window;
    }

    function permissionState() {
        if (!_isSupported()) return 'unsupported';
        return Notification.permission; // 'granted' | 'denied' | 'default'
    }

    async function requestPermission() {
        if (!_isSupported()) return 'unsupported';
        try {
            const result = await Notification.requestPermission();
            // Persist the user's choice so the prompt UI can stop asking.
            setPref('browser_notifications', result === 'granted');
            return result;
        } catch {
            return 'denied';
        }
    }

    /** True when the current tab is hidden (document.hidden) — the only
     *  time browser notifications are useful. */
    function _tabHidden() {
        return document.visibilityState === 'hidden' || document.hidden;
    }

    function showBrowserNotification(title, body, opts) {
        opts = opts || {};
        const prefs = getPrefs();
        if (!prefs.browser_notifications) return;
        if (!_isSupported() || Notification.permission !== 'granted') return;
        // Only show a native notification when the tab is NOT visible —
        // if the user is actively in the inbox, the in-app UI + sound is
        // enough.
        if (!_tabHidden()) return;

        try {
            const n = new Notification(title, {
                body: body || '',
                icon: opts.icon || '',
                tag: opts.tag || 'inbox-message',
                badge: opts.badge || '',
                silent: true, // we play our own sound
            });
            // Focus the window on click.
            n.onclick = function () {
                window.focus();
                this.close();
                if (opts.onClick) opts.onClick();
            };
            // Auto-close after 6 seconds so they don't pile up.
            setTimeout(() => { try { n.close(); } catch {} }, 6000);
        } catch {
            // Some browsers throw if the icon fails to load — ignore.
        }
    }

    // ------------------------------------------------------------------
    // Public hooks — called from inbox.js + inbox_badge.js
    // ------------------------------------------------------------------

    /**
     * Called when a new INBOUND message arrives.
     * Plays the incoming sound (if enabled) and shows a browser
     * notification (if the tab is hidden + enabled).
     *
     * @param {object} opts  { senderName, preview, conversationId, channelName }
     */
    function onIncomingMessage(opts) {
        opts = opts || {};
        // Sound — always plays (respecting prefs), even when tab is visible,
        // because the user may have another window focused.
        _playIncomingTone();

        // Browser notification — only when tab is hidden.
        if (_tabHidden()) {
            const sender = opts.senderName || 'New message';
            const preview = opts.preview || '';
            showBrowserNotification(sender, preview, {
                tag: 'inbox-' + (opts.conversationId || 'msg'),
                icon: opts.icon || '',
            });
        }
    }

    /**
     * Called when the agent sends a reply. Plays the outgoing blip.
     */
    function onOutgoingMessage() {
        _playOutgoingTone();
    }

    // ------------------------------------------------------------------
    // Export
    // ------------------------------------------------------------------
    window.InboxNotifications = {
        // Sound
        playIncoming: _playIncomingTone,
        playOutgoing: _playOutgoingTone,
        // Browser notifications
        showBrowserNotification,
        requestPermission,
        permissionState,
        // Preferences
        getPrefs,
        setPref,
        // Hooks (high-level — used by inbox.js + inbox_badge.js)
        onIncomingMessage,
        onOutgoingMessage,
        // Constants exposed for the UI
        DEFAULT_PREFS,
    };
})();
