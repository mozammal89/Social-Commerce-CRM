# Deployment Guide

This guide helps you deploy the Social Commerce CRM on a new server or PC.

## Common Issues & Solutions

### 1. 403 Forbidden Error

**Symptom**: You see a "403 Forbidden" error when accessing the application from a browser.

**Root Cause**: Django's CSRF protection rejects requests from unknown origins.

**Solution**: Add your access URL to `CSRF_TRUSTED_ORIGINS` in your `.env` file:

```bash
# For local development (already configured by default)
CSRF_TRUSTED_ORIGINS=http://localhost,http://localhost:8000,http://127.0.0.1,http://127.0.0.1:8000

# For IP access (add your server's IP)
CSRF_TRUSTED_ORIGINS=http://192.168.1.100,http://192.168.1.100:8000

# For domain access (with SSL)
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

**Important**: URLs must include the scheme (`http://` or `https://`) and NO trailing slashes.

### 2. Automatic HTTPS Redirect in Chrome

**Symptom**: Chrome automatically redirects all requests to HTTPS, even when you're using HTTP.

**Root Cause**: The `SECURE_SSL_REDIRECT=True` setting or HSTS (HTTP Strict Transport Security) cache in Chrome.

**Solution A - If you have SSL enabled:**
- Keep `SECURE_SSL_REDIRECT=True`
- Ensure you have valid SSL certificates configured

**Solution B - If you DON'T have SSL (most common during development):**
1. Set these in your `.env` file:
   ```bash
   SECURE_SSL_REDIRECT=False
   SECURE_HSTS_SECONDS=0
   SECURE_HSTS_INCLUDE_SUBDOMAINS=False
   SECURE_HSTS_PRELOAD=False
   SESSION_COOKIE_SECURE=False
   CSRF_COOKIE_SECURE=False
   ```

2. **Clear Chrome's HSTS cache** (Chrome remembers the HTTPS requirement!):
   - Go to `chrome://net-internals/#hsts`
   - Under "Delete domain security policies", enter your domain/IP
   - Click "Delete"

3. Clear Chrome's cookies for your site:
   - Go to `chrome://settings/content/all`
   - Find your site and remove cookies/storage

### 3. ALLOWED_HOSTS Configuration

If you see a "Invalid HTTP_HOST" error, add your domain/IP to `ALLOWED_HOSTS`:

```bash
# In .env
ALLOWED_HOSTS=localhost,127.0.0.1,your-server-ip,yourdomain.com
```

## First-Time Setup

1. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Update `.env` with your settings:**
   ```bash
   DEBUG=True  # Set to False in production
   SECRET_KEY=generate-a-random-secret-key
   DJANGO_SETTINGS_MODULE=config.settings.local  # or production for production

   # Database settings
   DB_NAME=social_commerce_crm
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_HOST=localhost  # or db for Docker
   DB_PORT=5432

   # IMPORTANT: Add your access URLs here
   CSRF_TRUSTED_ORIGINS=http://your-ip,http://your-domain
   ALLOWED_HOSTS=your-ip,your-domain,localhost
   ```

3. **Generate a secret key:**
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

4. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

5. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```

6. **Run the server:**
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

## Docker Deployment

1. **Build and start containers:**
   ```bash
   docker-compose up -d
   ```

2. **Access the application:**
   - HTTP: http://localhost
   - Direct Django: http://localhost:8000

3. **View logs:**
   ```bash
   docker-compose logs -f django
   ```

## Security Checklist for Production

Before going to production, ensure:

- [ ] `DEBUG=False`
- [ ] Generated strong `SECRET_KEY`
- [ ] SSL certificate installed and configured
- [ ] `SECURE_SSL_REDIRECT=True` (only after SSL is working!)
- [ ] `SESSION_COOKIE_SECURE=True`
- [ ] `CSRF_COOKIE_SECURE=True`
- [ ] `CSRF_TRUSTED_ORIGINS` includes your production domain
- [ ] `ALLOWED_HOSTS` includes your production domain
- [ ] Database credentials are strong
- [ ] PostgreSQL is used (not SQLite)
- [ ] Static files are being served properly
- [ ] Media files are being served properly

## Troubleshooting

### "DisallowedHost" Error
Add your host to `ALLOWED_HOSTS` in `.env`.

### CSRF Token Missing or Incorrect
Add your origin to `CSRF_TRUSTED_ORIGINS` in `.env`.

### Chrome Redirects to HTTPS Despite Settings
Clear Chrome's HSTS cache at `chrome://net-internals/#hsts`.

### Database Connection Error
Ensure PostgreSQL is running and credentials in `.env` match database settings.
