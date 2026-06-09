#!/bin/bash

# Django Management Script
# This script provides convenient commands for managing the Django application

function show_help() {
    echo "Social Commerce CRM - Django Management Script"
    echo ""
    echo "Usage: ./scripts/manage.sh [command]"
    echo ""
    echo "Commands:"
    echo "  migrate         Run database migrations"
    echo "  makemigrations  Create new migrations"
    echo "  shell           Open Django shell"
    echo "  shell_plus      Open Django shell_plus (requires django-extensions)"
    echo "  collectstatic   Collect static files"
    echo "  createsuperuser Create a superuser"
    echo "  runserver       Run development server"
    echo "  test            Run tests"
    echo "  test_coverage   Run tests with coverage"
    echo "  lint            Run linters (ruff, black, isort)"
    echo "  format          Format code (black, isort)"
    echo "  clean           Clean up temporary files"
    echo "  help            Show this help message"
}

function migrate() {
    echo "Running database migrations..."
    python manage.py migrate
}

function makemigrations() {
    echo "Creating new migrations..."
    python manage.py makemigrations
}

function shell() {
    echo "Opening Django shell..."
    python manage.py shell
}

function shell_plus() {
    echo "Opening Django shell_plus..."
    python manage.py shell_plus
}

function collectstatic() {
    echo "Collecting static files..."
    python manage.py collectstatic --noinput
}

function createsuperuser() {
    echo "Creating superuser..."
    python manage.py createsuperuser
}

function runserver() {
    echo "Starting development server..."
    python manage.py runserver
}

function test() {
    echo "Running tests..."
    pytest
}

function test_coverage() {
    echo "Running tests with coverage..."
    pytest --cov=apps --cov-report=html --cov-report=term
}

function lint() {
    echo "Running linters..."
    ruff check .
    black --check .
    isort --check-only .
}

function format() {
    echo "Formatting code..."
    ruff check --fix .
    black .
    isort .
}

function clean() {
    echo "Cleaning up temporary files..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    find . -type f -name "*.pyd" -delete
    find . -type f -name ".DS_Store" -delete
    rm -rf htmlcov/
    rm -rf .pytest_cache/
    rm -rf .ruff_cache/
    rm -rf .mypy_cache/
    rm -rf staticfiles/
    echo "Cleanup complete."
}

# Parse command
case "${1:-help}" in
    migrate)
        migrate
        ;;
    makemigrations)
        makemigrations
        ;;
    shell)
        shell
        ;;
    shell_plus)
        shell_plus
        ;;
    collectstatic)
        collectstatic
        ;;
    createsuperuser)
        createsuperuser
        ;;
    runserver)
        runserver
        ;;
    test)
        test
        ;;
    test_coverage)
        test_coverage
        ;;
    lint)
        lint
        ;;
    format)
        format
        ;;
    clean)
        clean
        ;;
    help|*)
        show_help
        ;;
esac