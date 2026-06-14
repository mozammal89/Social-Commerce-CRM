"""
Core Seeder System - Central registry for all application seeders.

This module provides a unified interface for running seeders individually
or all at once. Each seeder should inherit from BaseSeeder and register itself.

Usage:
    # Run all seeders
    python manage.py seed

    # Run specific seeder
    python manage.py seed accounts
    python manage.py seed products
    python manage.py seed customers

    # Run multiple seeders
    python manage.py seed accounts products customers
"""

from .base import BaseSeeder

__all__ = ["BaseSeeder"]


def get_all_seeders():
    """
    Get all registered seeders.

    Returns:
        dict: Dictionary mapping seeder names to seeder classes.
    """
    from . import accounts
    from . import customers
    from . import products
    from . import orders
    from . import stores

    return {
        "accounts": accounts.AccountSeeder,
        "customers": customers.CustomerSeeder,
        "products": products.ProductSeeder,
        "orders": orders.OrderSeeder,
        "stores": stores.StoreSeeder,
    }


def run_seeder(seeder_name, verbosity=1):
    """
    Run a single seeder by name.

    Args:
        seeder_name (str): Name of the seeder to run.
        verbosity (int): Output verbosity level (0=silent, 1=normal, 2=verbose).

    Returns:
        bool: True if seeder ran successfully, False otherwise.
    """
    seeders = get_all_seeders()

    if seeder_name not in seeders:
        available = ", ".join(sorted(seeders.keys()))
        print(f"❌ Seeder '{seeder_name}' not found. Available: {available}")
        return False

    seeder_class = seeders[seeder_name]
    seeder = seeder_class(verbosity=verbosity)

    try:
        if verbosity > 0:
            print(f"\n{'='*60}")
            print(f"🌱 Running {seeder_name.title()} Seeder")
            print(f"{'='*60}")

        seeder.run()

        if verbosity > 0:
            print(f"✅ {seeder_name.title()} seeder completed successfully")

        return True

    except Exception as e:
        if verbosity > 0:
            print(f"❌ {seeder_name.title()} seeder failed: {str(e)}")
        return False


def run_all_seeders(verbosity=1):
    """
    Run all registered seeders.

    Args:
        verbosity (int): Output verbosity level (0=silent, 1=normal, 2=verbose).

    Returns:
        dict: Dictionary with seeder names as keys and success status as values.
    """
    seeders = get_all_seeders()
    results = {}

    if verbosity > 0:
        print(f"\n{'='*60}")
        print(f"🌱 Running All Seeders")
        print(f"{'='*60}\n")

    for seeder_name in sorted(seeders.keys()):
        results[seeder_name] = run_seeder(seeder_name, verbosity=verbosity)

    if verbosity > 0:
        print(f"\n{'='*60}")
        print("📊 Seeder Summary")
        print(f"{'='*60}")
        successful = sum(1 for v in results.values() if v)
        total = len(results)
        print(f"Completed: {successful}/{total}")
        for seeder_name, success in results.items():
            status = "✅" if success else "❌"
            print(f"  {status} {seeder_name}")

    return results
