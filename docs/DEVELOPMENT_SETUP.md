# Social Commerce CRM - Development Setup Guide

This guide provides detailed instructions for setting up the development environment for the Social Commerce CRM project.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.12 or higher**
  ```bash
  python --version
  ```

- **PostgreSQL 16**
  ```bash
  psql --version
  ```

- **Redis 7**
  ```bash
  redis-server --version
  ```

- **Git**
  ```bash
  git --version
  ```

- **Docker and Docker Compose** (optional but recommended)
  ```bash
  docker --version
  docker-compose --version
  ```

## Installation Steps

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Social-Commerce-CRM
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements/dev.txt
```

### 4. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
DEBUG=True
SECRET_KEY=your-local-secret-key-here
DJANGO_SETTINGS_MODULE=config.settings.local

DATABASE_URL=postgresql://crm_user:crm_password@localhost:5432/crm_db_dev
REDIS_URL=redis://localhost:6379/1

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### 5. Set Up PostgreSQL

Create a PostgreSQL database:

```sql
CREATE DATABASE crm_db_dev;
CREATE USER crm_user WITH PASSWORD 'crm_password';
GRANT ALL PRIVILEGES ON DATABASE crm_db_dev TO crm_user;
```

### 6. Set Up Redis

Start Redis server:

```bash
redis-server
```

### 7. Run Database Migrations

```bash
python manage.py migrate
```

### 8. Create a Superuser

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin account.

### 9. Collect Static Files (optional for development)

```bash
python manage.py collectstatic --noinput
```

## Running the Development Server

### Start Django Development Server

```bash
python manage.py runserver
```

The API will be available at:
- API: http://localhost:8000
- Admin: http://localhost:8000/admin
- API Docs (Swagger): http://localhost:8000/api/docs
- API Docs (ReDoc): http://localhost:8000/api/redoc

### Start Celery Worker

In a new terminal:

```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
celery -A config worker -l info
```

### Start Celery Beat Scheduler

In another new terminal:

```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### Start Flower (Celery Monitoring)

In another new terminal:

```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
celery -A config flower
```

Access Flower at: http://localhost:5555

## Using Docker (Recommended)

If you prefer using Docker, follow these steps:

### 1. Build and Start Services

```bash
docker-compose up -d
```

This will start:
- PostgreSQL database
- Redis cache
- Django application
- Celery worker
- Celery beat scheduler
- Flower monitoring
- Nginx reverse proxy

### 2. Run Migrations

```bash
docker-compose exec django python manage.py migrate
```

### 3. Create Superuser

```bash
docker-compose exec django python manage.py createsuperuser
```

### 4. View Logs

```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f django
docker-compose logs -f celery_worker
```

### 5. Stop Services

```bash
docker-compose down
```

### 6. Remove Volumes (wipe data)

```bash
docker-compose down -v
```

## Development Workflow

### Code Quality Tools

Format your code before committing:

```bash
black .
isort .
ruff check --fix .
```

Run type checking:

```bash
mypy apps/
```

### Running Tests

Run all tests:

```bash
pytest
```

Run tests with coverage:

```bash
pytest --cov=apps --cov-report=html
```

Run specific tests:

```bash
pytest tests/test_user_model.py -v
```

### Using the Management Script

The project includes a convenient management script:

```bash
./scripts/manage.sh help
```

Available commands:
- `migrate` - Run database migrations
- `makemigrations` - Create new migrations
- `shell` - Open Django shell
- `shell_plus` - Open Django shell_plus
- `collectstatic` - Collect static files
- `createsuperuser` - Create a superuser
- `runserver` - Run development server
- `test` - Run tests
- `test_coverage` - Run tests with coverage
- `lint` - Run linters
- `format` - Format code
- `clean` - Clean up temporary files

### Pre-commit Hooks

Install pre-commit hooks:

```bash
pre-commit install
```

The hooks will run automatically before each commit.

## Troubleshooting

### Database Connection Issues

If you encounter database connection errors:

1. Ensure PostgreSQL is running
2. Check your `.env` file has correct database credentials
3. Verify the database exists: `psql -U crm_user -d crm_db_dev`

### Redis Connection Issues

If Redis connection fails:

1. Ensure Redis is running: `redis-server`
2. Test connection: `redis-cli ping`
3. Check `.env` file has correct Redis URL

### Celery Tasks Not Running

If Celery tasks aren't executing:

1. Check Celery worker is running
2. Ensure Celery beat scheduler is running
3. Check Flower dashboard for task status
4. Verify Redis connection

### Static Files Not Loading

If static files aren't loading:

1. Run `python manage.py collectstatic`
2. Check `STATIC_URL` and `STATIC_ROOT` settings
3. Ensure directories have proper permissions

### Import Errors

If you encounter import errors:

1. Ensure virtual environment is activated
2. Install dependencies: `pip install -r requirements/dev.txt`
3. Check `DJANGO_SETTINGS_MODULE` environment variable

## IDE Configuration

### VS Code

Install these extensions:
- Python
- Pylance
- Black Formatter
- Ruff
- Docker

Create `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "./venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  }
}
```

### PyCharm

1. Open the project directory
2. Configure Python interpreter to use the virtual environment
3. Enable Black and Ruff as external tools
4. Configure pytest as the default test runner

## Next Steps

Once your development environment is set up:

1. Read the [README.md](README.md) for project overview
2. Explore the API documentation at `/api/docs/`
3. Review the code structure in the `apps/` directory
4. Start implementing business logic following the established patterns
5. Write tests for your code
6. Ensure code quality tools pass before committing

## Additional Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Celery Documentation](https://docs.celeryproject.org/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/docs/)