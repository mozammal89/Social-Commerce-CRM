"""
Base Seeder Class - Abstract base class for all seeders.

All seeders should inherit from BaseSeeder and implement the run() method.
This base class provides common functionality for deterministic data seeding.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from django.db import transaction


class BaseSeeder(ABC):
    """
    Abstract base class for all seeders.

    Provides common functionality for seeding data including:
    - Transaction support for atomic operations
    - Common utility methods
    - Logging capabilities

    Attributes:
        verbosity (int): Output verbosity level (0=silent, 1=normal, 2=verbose).
    """

    def __init__(self, verbosity: int = 1):
        """
        Initialize the seeder.

        Args:
            verbosity (int): Output verbosity level (0=silent, 1=normal, 2=verbose).
        """
        self.verbosity = verbosity

    @abstractmethod
    def run(self) -> None:
        """
        Run the seeder. Must be implemented by subclasses.

        This method should contain all the logic for seeding data.
        It will be called within a transaction for atomicity.
        """
        pass

    def log(self, message: str, level: int = 1) -> None:
        """
        Log a message if verbosity allows.

        Args:
            message (str): The message to log.
            level (int): Minimum verbosity level required to show this message.
        """
        if self.verbosity >= level:
            print(f"  {message}")

    def safe_run(self) -> bool:
        """
        Run the seeder with transaction safety.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            with transaction.atomic():
                self.run()
                return True
        except Exception as e:
            self.log(f"❌ Error during seeding: {str(e)}")
            return False
