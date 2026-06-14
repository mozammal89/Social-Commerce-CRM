"""
Django Management Command: Seed

Run seeders to populate the database with sample data.

Usage:
    python manage.py seed                    # Run all seeders
    python manage.py seed accounts           # Run specific seeder
    python manage.py seed accounts products   # Run multiple seeders
    python manage.py seed --flush             # Clear all data before seeding
    python manage.py seed --verbosity=0      # Silent mode
    python manage.py seed --verbosity=2      # Verbose mode
"""

from django.core.management.base import BaseCommand
from django.core.management import call_command
from typing import Optional


class Command(BaseCommand):
    help = "Run seeders to populate database with sample data"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.verbosity = 1

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "seeders",
            nargs="*",
            type=str,
            help="Specific seeders to run (runs all if not specified). "
            "Available: accounts, customers, products, orders, stores",
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Flush all data before seeding (WARNING: deletes all data)",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all available seeders",
        )
        parser.add_argument(
            "--seed-verbosity",
            type=int,
            default=1,
            choices=[0, 1, 2],
            dest="verbosity",
            help="Verbosity level: 0=silent, 1=normal, 2=verbose",
        )

    def handle(self, *args, **options):
        """Handle the command execution."""
        from apps.core.seeders import get_all_seeders, run_seeder, run_all_seeders

        self.verbosity = options.get("verbosity", 1)

        # List available seeders
        if options.get("list"):
            self.list_seeders()
            return

        # Flush data if requested
        if options.get("flush"):
            self.flush_data()

        # Get specified seeders or run all
        specified_seeders = options.get("seeders", [])

        if specified_seeders:
            # Validate seeder names
            available_seeders = get_all_seeders()
            invalid = [s for s in specified_seeders if s not in available_seeders]

            if invalid:
                self.stderr.write(
                    self.style.ERROR(f"Invalid seeder(s): {', '.join(invalid)}")
                )
                self.stderr.write(
                    f"Available: {', '.join(sorted(available_seeders.keys()))}"
                )
                return

            # Run specified seeders
            results = {}
            for seeder_name in specified_seeders:
                success = run_seeder(seeder_name, verbosity=self.verbosity)
                results[seeder_name] = success

            # Print summary
            self.print_summary(results)

        else:
            # Run all seeders
            if self.verbosity > 0:
                self.stdout.write(
                    self.style.SUCCESS("No seeders specified. Running all seeders...")
                )

            results = run_all_seeders(verbosity=self.verbosity)

    def list_seeders(self):
        """List all available seeders."""
        from apps.core.seeders import get_all_seeders

        seeders = get_all_seeders()
        self.stdout.write(self.style.SUCCESS("Available seeders:"))
        for name in sorted(seeders.keys()):
            seeder_class = seeders[name]
            description = getattr(seeder_class, "description", "No description")
            self.stdout.write(f"  • {name}: {description}")

    def flush_data(self):
        """Flush all data from the database."""
        if self.verbosity > 0:
            self.stdout.write(
                self.style.WARNING("Flushing all data... (this cannot be undone)")
            )

        call_command("flush", interactive=False, verbosity=self.verbosity)

        if self.verbosity > 0:
            self.stdout.write(self.style.SUCCESS("All data flushed successfully"))

    def print_summary(self, results: dict):
        """Print summary of seeding results."""
        if self.verbosity == 0:
            return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("📊 Seeder Summary"))
        self.stdout.write(f"{'='*60}")

        successful = sum(1 for v in results.values() if v)
        total = len(results)
        self.stdout.write(f"Completed: {successful}/{total}")

        for seeder_name, success in results.items():
            if success:
                self.stdout.write(
                    self.style.SUCCESS(f"  ✅ {seeder_name}")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"  ❌ {seeder_name}")
                )
