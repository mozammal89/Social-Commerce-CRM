/* =====================================================================
   Auth interactions
   - Password visibility toggle
   - Loading button state
   - Password strength meter
   - Resend email cooldown
   - Auto-redirect with cancel
   - Match indicator for confirm-password fields
   ===================================================================== */
(function () {
    "use strict";

    // ------------------------------------------------------------------
    // Password visibility toggle
    // ------------------------------------------------------------------
    function initPasswordToggles(root) {
        const toggles = (root || document).querySelectorAll("[data-toggle='password']");
        toggles.forEach(function (btn) {
            if (btn.__bound) return;
            btn.__bound = true;

            // Find sibling input
            const group = btn.closest(".input-group--password");
            const input = group ? group.querySelector("input") : null;
            if (!input) return;

            const iconShow  = btn.querySelector("[data-show]");
            const iconHide  = btn.querySelector("[data-hide]");

            btn.addEventListener("click", function () {
                const isHidden = input.type === "password";
                input.type = isHidden ? "text" : "password";
                btn.setAttribute("aria-pressed", isHidden ? "true" : "false");
                btn.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
                if (iconShow && iconHide) {
                    iconShow.classList.toggle("d-none", isHidden);
                    iconHide.classList.toggle("d-none", !isHidden);
                }
                input.focus();
            });
        });
    }

    // ------------------------------------------------------------------
    // Loading buttons
    // ------------------------------------------------------------------
    function initLoadingButtons(root) {
        const forms = (root || document).querySelectorAll("form");
        forms.forEach(function (form) {
            if (form.__loadingBound) return;
            form.__loadingBound = true;

            form.addEventListener("submit", function () {
                const btns = form.querySelectorAll("[data-loading]");
                btns.forEach(function (btn) { btn.classList.add("is-loading"); });
            });
        });
    }

    // ------------------------------------------------------------------
    // Password strength meter
    // ------------------------------------------------------------------
    function scorePassword(value) {
        if (!value) return 0;
        let score = 0;
        if (value.length >= 8) score++;
        if (value.length >= 12) score++;
        if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score++;
        if (/\d/.test(value)) score++;
        if (/[^A-Za-z0-9]/.test(value)) score++;
        // Normalize to 0..4
        if (value.length < 6) score = Math.min(score, 1);
        if (score >= 5) score = 4;
        return Math.max(0, Math.min(4, score));
    }

    const strengthLabels = ["", "Weak", "Fair", "Strong", "Excellent"];

    function initStrengthMeters(root) {
        const meters = (root || document).querySelectorAll("[data-strength-bar]");
        meters.forEach(function (bar) {
            if (bar.__bound) return;
            bar.__bound = true;

            const field = bar.closest(".form-field");
            const input = field ? field.querySelector("input[type='password']") : null;
            const label = field ? field.querySelector("[data-strength-label]") : null;
            const meter = bar.closest(".password-meter");
            if (!input) return;

            function update() {
                const v = input.value;
                const s = scorePassword(v);
                if (meter) meter.setAttribute("data-strength", s > 0 ? s : "");
                if (label) {
                    if (v.length === 0) {
                        label.textContent = label.dataset.placeholder || "Use 8+ characters with a number and symbol";
                        label.removeAttribute("data-tone");
                    } else {
                        label.textContent = "Strength: " + strengthLabels[s];
                        label.setAttribute("data-tone", s <= 1 ? "weak" : (s <= 2 ? "fair" : "strong"));
                    }
                }
            }

            input.addEventListener("input", update);
            update();
        });
    }

    // ------------------------------------------------------------------
    // Match indicator for confirm-password fields
    // ------------------------------------------------------------------
    function initMatchIndicators(root) {
        const confirms = (root || document).querySelectorAll("[data-match-target]");
        confirms.forEach(function (input) {
            if (input.__bound) return;
            input.__bound = true;

            const targetSel = input.getAttribute("data-match-target");
            const target = targetSel ? document.querySelector(targetSel) : null;
            const feedback = input.closest(".form-field").querySelector("[data-match-feedback]");
            if (!target) return;

            function update() {
                if (!feedback) return;
                if (!input.value) {
                    feedback.textContent = "";
                    input.removeAttribute("aria-invalid");
                } else if (input.value === target.value) {
                    feedback.textContent = "Passwords match";
                    feedback.style.color = "var(--success-600)";
                    input.removeAttribute("aria-invalid");
                } else {
                    feedback.textContent = "Passwords don't match";
                    feedback.style.color = "var(--danger-600)";
                    input.setAttribute("aria-invalid", "true");
                }
            }

            input.addEventListener("input", update);
            target.addEventListener("input", update);
            update();
        });
    }

    // ------------------------------------------------------------------
    // Resend email cooldown
    // ------------------------------------------------------------------
    function initResendCooldowns(root) {
        const buttons = (root || document).querySelectorAll("[data-resend]");
        buttons.forEach(function (btn) {
            if (btn.__bound) return;
            btn.__bound = true;

            const seconds = parseInt(btn.getAttribute("data-resend") || "30", 10);
            const countdown = btn.querySelector("[data-countdown]");
            const time = countdown ? countdown.querySelector("[data-time]") : null;
            if (!countdown || !time) return;

            function start() {
                btn.setAttribute("disabled", "true");
                countdown.hidden = false;
                countdown.setAttribute("data-active", "true");
                let remaining = seconds;
                time.textContent = remaining;

                const handle = setInterval(function () {
                    remaining--;
                    if (remaining <= 0) {
                        clearInterval(handle);
                        countdown.hidden = true;
                        countdown.setAttribute("data-active", "false");
                        btn.removeAttribute("disabled");
                    } else {
                        time.textContent = remaining;
                    }
                }, 1000);
            }

            // Server may mark as just-sent; we only start if not disabled already
            if (btn.hasAttribute("data-resend-start")) start();

            btn.addEventListener("click", function (e) {
                if (btn.hasAttribute("disabled")) { e.preventDefault(); return; }
                // Allow the form to submit; start cooldown immediately for UX
                start();
            });
        });
    }

    // ------------------------------------------------------------------
    // Auto-redirect
    // ------------------------------------------------------------------
    function initAutoRedirect(root) {
        const el = (root || document).querySelector("[data-redirect]");
        if (!el || el.__bound) return;
        el.__bound = true;

        const seconds = parseInt(el.getAttribute("data-redirect") || "3", 10);
        const target  = el.getAttribute("data-redirect-to");
        if (!target) return;
        el.hidden = false;

        const time = el.querySelector("[data-time]");
        if (time) time.textContent = seconds;

        let remaining = seconds;
        const handle = setInterval(function () {
            remaining--;
            if (time) time.textContent = Math.max(remaining, 0);
            if (remaining <= 0) {
                clearInterval(handle);
                window.location.href = target;
            }
        }, 1000);

        const cancel = el.querySelector("[data-redirect-cancel]");
        if (cancel) {
            cancel.addEventListener("click", function (e) {
                e.preventDefault();
                clearInterval(handle);
                el.hidden = true;
            });
        }
    }

    // ------------------------------------------------------------------
    // Bootstrap
    // ------------------------------------------------------------------
    function initAll(root) {
        initPasswordToggles(root);
        initLoadingButtons(root);
        initStrengthMeters(root);
        initMatchIndicators(root);
        initResendCooldowns(root);
        initAutoRedirect(root);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { initAll(document); });
    } else {
        initAll(document);
    }

    // Re-init for HTMX swaps if used
    document.body && document.body.addEventListener && document.body.addEventListener("htmx:afterSwap", function (e) {
        initAll(e.target);
    });

    // Expose for debugging
    window.AuthUI = { initAll: initAll };
})();
