"""
Factory classes for Store model.
"""

import factory
from factory import fuzzy
from apps.stores.models import Store
from tests.factories import UserFactory


class StoreFactory(factory.django.DjangoModelFactory):
    """Factory for creating Store instances."""

    class Meta:
        model = Store

    name = factory.Faker("company")
    description = factory.Faker("text", max_nb_chars=200)
    status = fuzzy.FuzzyChoice([status[0] for status in Store.STATUS_CHOICES])

    @factory.post_generation
    def owners(self, create, extracted, **kwargs):
        """Add owners to store."""
        if not create:
            return

        if extracted:
            for owner in extracted:
                self.owners.add(owner)
        else:
            self.owners.add(UserFactory(role=User.UserRole.STORE_OWNER))


class ActiveStoreFactory(StoreFactory):
    """Factory for creating active stores."""

    status = "active"
