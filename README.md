# Social Commerce CRM - Django SaaS Foundation

A production-ready Django 5.x foundation for a Social Commerce CRM platform, following modern Django best practices, clean architecture principles, and designed for long-term maintainability and scalability.

## 🏗️ Architecture Overview

This project provides a solid foundation for building a multi-tenant Social Commerce CRM SaaS platform with:

- **Multi-tenancy**: Store-based data isolation
- **Authentication**: JWT-based authentication with custom User model
- **API**: RESTful API with automatic documentation
- **Background Tasks**: Celery + Redis for async processing
- **Monitoring**: Health checks, logging, and metrics
- **Security**: Rate limiting, CSRF protection, secure headers
- **Code Quality**: Pre-configured linting, formatting, and testing tools

## 📋 Tech Stack

- **Backend**: Django 5.x, Django REST Framework, Python 3.12+
- **Database**: PostgreSQL 16
- **Cache & Broker**: Redis 7
- **Task Queue**: Celery + Celery Beat
- **API Docs**: drf-spectacular (OpenAPI 3.0)
- **Security**: django-axes for rate limiting
- **Containerization**: Docker + Docker Compose
- **Web Server**: Gunicorn + Nginx
- **Testing**: pytest + factory-boy + faker
- **Code Quality**: ruff, black, isort, mypy, pre-commit

## 🚀 Quick Start

### Prerequisites

- Python 3.12 or higher
- PostgreSQL 16
- Redis 7
- Docker and Docker Compose (optional)

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Social-Commerce-CRM
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements/dev.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

6. **Create a superuser**
   ```bash
   python manage.py createsuperuser
   ```

7. **Start the development server**
   ```bash
   python manage.py runserver
   ```

8. **Start Celery worker** (in another terminal)
   ```bash
   celery -A config worker -l info
   ```

9. **Start Celery beat** (in another terminal)
   ```bash
   celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
   ```

### Docker Setup

1. **Build and start all services**
   ```bash
   docker-compose up -d
   ```

2. **Run migrations**
   ```bash
   docker-compose exec django python manage.py migrate
   ```

3. **Create a superuser**
   ```bash
   docker-compose exec django python manage.py createsuperuser
   ```

4. **Access the application**
   - API: http://localhost:8000
   - Admin: http://localhost:8000/admin
   - API Docs (Swagger): http://localhost:8000/api/docs
   - API Docs (ReDoc): http://localhost:8000/api/redoc
   - Flower (Celery Monitoring): http://localhost:5555

## 📁 Project Structure

```
Social-Commerce-CRM/
├── config/                 # Project configuration
│   ├── settings/          # Environment-specific settings
│   │   ├── base.py       # Base settings
│   │   ├── local.py      # Local development
│   │   ├── staging.py    # Staging environment
│   │   └── production.py # Production environment
│   ├── urls.py           # Root URL configuration
│   ├── wsgi.py           # WSGI configuration
│   ├── asgi.py           # ASGI configuration
│   └── celery.py         # Celery configuration
├── apps/                  # Django applications
│   ├── accounts/        # User authentication & management
│   ├── stores/          # Multi-tenancy store management
│   ├── common/          # Shared models & utilities
│   ├── core/            # Core functionality (health checks)
│   ├── customers/       # CRM customer records
│   ├── products/        # Catalog
│   ├── orders/          # Order management
│   ├── marketing/       # Campaigns & promo codes
│   ├── reports/         # Analytics
│   ├── permissions/     # RBAC, roles, plans, audit logging
│   ├── audit/           # Audit trail
│   ├── settings/        # Store settings
│   ├── help/            # Help / support content
│   └── dashboard/       # Home dashboard
├── tests/                # Test suite
├── requirements/         # Python dependencies
│   ├── base.txt         # Core dependencies
│   ├── local.txt        # Local development
│   ├── dev.txt          # Development tools
│   └── production.txt   # Production dependencies
├── docker/              # Docker configuration
│   └── nginx.conf       # Nginx configuration
├── docs/                # Documentation
├── scripts/             # Utility scripts
├── templates/           # HTML templates
├── static/              # Static files
├── media/               # User uploaded media
├── manage.py            # Django management script
├── Dockerfile           # Docker image
├── docker-compose.yml   # Docker services
├── pytest.ini           # Pytest configuration
├── pyproject.toml       # Project configuration
├── ruff.toml           # Ruff linter configuration
└── .pre-commit-config.yaml # Pre-commit hooks
```

## 🔑 Key Features

### Custom User Model

- UUID primary key
- Email-based authentication
- Role-based permissions (Admin, Store Owner, Store Manager, Store Staff, Customer)
- Phone number support
- Avatar support
- Login tracking

### Multi-Tenancy

- Store-based tenant isolation
- Automatic tenant filtering
- Soft delete support
- Tenant ownership validation

### Authorization & Permissions (`apps.permissions`)

- 5-layer access control: Subscription plan → Store membership → Role → Permission override → Object-level
- Single-source-of-truth permission registry; `sync_permissions` syncs the DB
- System roles (Store Owner, Manager, Viewer, …) + per-store custom roles
- DENY modifier wins over GRANT (privilege-escalation guard)
- Subscription feature gating (Marketing campaigns, Multi-warehouse, …)
- Append-only `AuditLog` for every role / membership / override change
- Version-stamp cache invalidation (no need to enumerate Redis keys)
- Template tags (`{% can %}`, `{% can_any %}`, `{% has_feature %}`), function-view decorators, CBV mixins, and DRF permission classes all share one resolver
- JWT fast-path: RBAC claims embedded in access token, short-circuit when fresh
- **Full step-by-step guide:** [`docs/RBAC_USER_GUIDE.md`](docs/RBAC_USER_GUIDE.md)
- Quick reference: [`apps/permissions/README.md`](apps/permissions/README.md)

### API Endpoints

#### Authentication (`/api/v1/auth/`)
- `POST /register/` - User registration
- `POST /login/` - JWT token generation
- `POST /token/refresh/` - Refresh JWT token
- `POST /logout/` - Logout (blacklist token)
- `GET /me/` - Get current user
- `GET /profile/` - Get user profile
- `PATCH /profile/` - Update user profile
- `POST /change-password/` - Change password

#### Stores (`/api/v1/stores/`)
- `GET /` - List user's stores
- `POST /` - Create store
- `GET /my-stores/` - List owned stores
- `GET /{id}/` - Get store details
- `PATCH /{id}/` - Update store
- `DELETE /{id}/` - Delete store (soft delete)
- `POST /{store_id}/staff/` - Manage store staff

#### Health Checks (`/api/v1/health/`)
- `GET /` - Simple health check
- `GET /detailed/` - Detailed health status (database, Redis, Celery)

#### API Documentation
- `/api/docs/` - Swagger UI
- `/api/redoc/` - ReDoc
- `/api/schema/` - OpenAPI schema

## 🛠️ Development Tools

### Code Quality

```bash
# Format code
black .
isort .

# Lint code
ruff check .

# Type checking
mypy apps/

# Run pre-commit hooks
pre-commit run --all-files
```

### Testing

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=apps --cov-report=html

# Run specific test file
pytest tests/test_user_model.py

# Run with verbose output
pytest -v
```

### Management Script

```bash
# Using the management script
./scripts/manage.sh migrate
./scripts/manage.sh makemigrations
./scripts/manage.sh shell
./scripts/manage.sh test
./scripts/manage.sh lint
./scripts/manage.sh format
./scripts/manage.sh clean
```

## 🔒 Security Features

- **Authentication**: JWT tokens with refresh token rotation
- **Rate Limiting**: django-axes for login attempt tracking
- **CSRF Protection**: Cross-site request forgery protection
- **Secure Headers**: HSTS, XSS protection, content type nosniff
- **Password Validation**: Strong password requirements
- **Soft Delete**: Data retention with deletion tracking

## 📊 Monitoring & Logging

### Logging
- Console logging
- File logging with rotation
- Error-specific logging
- Application and request logging

### Health Checks
- Application status
- Database connectivity
- Redis connectivity
- Celery worker status

### Celery Monitoring
- Flower dashboard at `http://localhost:5555`
- Task monitoring and statistics
- Real-time task tracking

## 🚢 Deployment

### Environment Setup

1. **Set environment variables**
   ```bash
   export DJANGO_SETTINGS_MODULE=config.settings.production
   export DEBUG=False
   ```

2. **Install production dependencies**
   ```bash
   pip install -r requirements/production.txt
   ```

3. **Run production migrations**
   ```bash
   python manage.py migrate --settings=config.settings.production
   ```

4. **Collect static files**
   ```bash
   python manage.py collectstatic --settings=config.settings.production --noinput
   ```

5. **Start Gunicorn**
   ```bash
   gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4
   ```

### Docker Deployment

```bash
# Build production image
docker-compose -f docker-compose.yml build

# Start production services
docker-compose -f docker-compose.yml up -d

# Check logs
docker-compose logs -f django
```

## 📝 Configuration

### Settings Files

- **base.py**: Shared settings across all environments
- **local.py**: Local development overrides
- **staging.py**: Staging environment configuration
- **production.py**: Production environment configuration

### Environment Variables

See `.env.example` for all available environment variables.

## 🧪 Testing Strategy

- **Unit Tests**: Model and utility function testing
- **Integration Tests**: API endpoint testing
- **Fixtures**: factory-boy for test data generation
- **Coverage**: Minimum 80% code coverage

## 🤝 Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Submit a pull request

## 📄 License

This project is proprietary software. All rights reserved.

## 🆘 Support

For issues and questions, please contact the development team.

## 🗺️ Roadmap

This foundation is ready for the following Social Commerce CRM features:

- Customer management
- Product catalog
- Order management
- Inventory tracking
- Payment integration
- Shipping management
- Social media integration
- Analytics and reporting
- Multi-channel selling

---

**Note**: This project foundation provides the architecture and infrastructure needed for a Social Commerce CRM platform. Business logic and domain-specific features should be implemented following the established patterns and conventions.