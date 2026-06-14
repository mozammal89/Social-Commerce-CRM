# Auth v2 — Modern SaaS Authentication Experience

A redesigned, cohesive authentication suite built on top of Bootstrap 5.

## What is included

### Static assets
- `static/css/auth-design-system.css` — design tokens, layout, form, button, alert, state card, strength meter.
- `static/js/auth.js` — password visibility toggle, loading buttons, strength meter, match indicator, resend cooldown, auto-redirect.

### Layouts
- `templates/layouts/auth_v2.html` — split-screen layout with branded left panel and form panel on the right.

### Reusable partials
- `templates/components/auth_form_field.html` — labeled form field with hint, error, password mode, strength meter, match target.
- `templates/components/auth_state_card.html` — success / warning / danger / info state card.
- `templates/components/auth_sso.html` — SSO buttons + divider.

### Pages (`templates/auth_v2/`)
- `login.html` — Sign in with email or Google.
- `register.html` — Sign up with email or Google, password strength meter, TOS.
- `password_reset.html` — Forgot password.
- `password_reset_done.html` — Check your email (with resend cooldown).
- `password_reset_sent.html` — Alias for `password_reset_done.html`.
- `password_reset_confirm.html` — Set a new password (with strength meter and match indicator).
- `password_reset_complete.html` — Password updated (with auto-redirect).
- `change_password.html` — Authenticated change password.
- `change_password_done.html` — Password changed confirmation.
- `email_verification.html` — Verify your email.
- `resend_verification.html` — Resend verification email.
- `account_locked.html` — Account locked (warning tone).
- `session_expired.html` — Session expired (pre-filled login form).
- `access_denied.html` — 403 access denied.

## Design highlights

- **Split-screen layout** on desktop (≥992px) — branding on the left, form on the right.
- **Single column** on mobile with the brand mark above the form.
- **Modern inputs** — 44px height, 12px radius, accessible focus ring.
- **Password toggle** with `aria-pressed` and dynamic icon.
- **Password strength meter** with four bars and labels (Weak / Fair / Strong / Excellent).
- **Match indicator** for confirm-password fields with live region.
- **Loading buttons** with spinner and disabled state during submit.
- **Modern checkbox** — 20px box, 6px radius, animated check that respects `prefers-reduced-motion`.
- **State cards** for success / warning / danger / info with semantic colors and clear CTAs.
- **Resend cooldown** — buttons disabled with a live countdown.
- **Auto-redirect** with cancel link.
- **Trust indicators** in the branding panel (SOC 2, encryption, GDPR).
- **Accessible focus states** and color contrast ≥ 4.5:1.

## Integration steps

1. **Load the assets.** Add the new CSS to your auth pages and the JS at the bottom of the body. The new `auth_v2.html` layout already references both, so the simplest path is to point your auth URLs at the new templates.

2. **Update URL configuration** (in `config/urls.py` or the relevant `urls.py`) to use the new templates. Example:
   ```python
   path('auth/login/', auth_views.LoginView.as_view(template_name='auth_v2/login.html'), name='login'),
   path('auth/register/', ... 'auth_v2/register.html' ...),
   ```
   Or, if your views use class-based views with `template_name`, just change those.

3. **Form fields preserved.** Every redesigned template keeps all Django template tags and form rendering (`{{ form.username }}`, `{{ form.email }}`, etc.) intact. None of your view code needs to change.

4. **Static collection.** Run `python manage.py collectstatic` so the new files end up under `staticfiles/`.

5. **Optional cleanup.** Once the new pages are in production, you can remove the old `templates/auth/*.html` files and `templates/layouts/auth.html`.

## Browser / accessibility support

- Modern evergreen browsers (Chrome, Edge, Firefox, Safari).
- Tested responsive breakpoints: 320px, 576px, 768px, 992px, 1200px, 1440px.
- WCAG 2.1 AA: focus order, contrast, labels, error announcements, reduced-motion.

## Customization

All design tokens live at the top of `auth-design-system.css`:
- Brand colors (`--brand-600` etc.)
- Ink scale
- Semantic colors
- Radii and shadows
- Spacing rhythm
- Type stack (Inter preferred, falls back to system fonts)

Override them in your own CSS to re-skin the suite without touching components.

## Notes

- The old templates in `templates/auth/` and `templates/layouts/auth.html` are left untouched so the redesign is fully opt-in.
- The new layout is `templates/layouts/auth_v2.html` — pages in `templates/auth_v2/` extend it.
