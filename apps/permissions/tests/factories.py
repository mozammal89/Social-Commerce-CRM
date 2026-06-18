"""
Test factories for the permissions app.

Reuse the existing project factories (tests/factories.py) where possible.
This module adds permissions-specific factories.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.permissions.models import (
    Feature,
    Permission,
    Resource,
    Role,
    RolePermission,
    StoreMembership,
    Subscription,
    SubscriptionPlan,
    PlanFeature,
)


class ResourceFactory(DjangoModelFactory):
    class Meta:
        model = Resource
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"resource_{n}")
    name = factory.LazyAttribute(lambda o: o.code.title())
    category = "test"
    description = ""
    is_active = True
    actions = ["view"]


class PermissionFactory(DjangoModelFactory):
    class Meta:
        model = Permission
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"resource_{n}.view")
    resource = factory.SubFactory(ResourceFactory)
    action = "view"
    name = factory.LazyAttribute(lambda o: o.code)
    description = ""
    is_system = True


class RoleFactory(DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("slug", "store")

    slug = factory.Sequence(lambda n: f"role_{n}")
    name = factory.LazyAttribute(lambda o: o.slug.title())
    description = ""
    level = 0
    is_system = False
    is_active = True
    store = None


class FeatureFactory(DjangoModelFactory):
    class Meta:
        model = Feature
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"feature_{n}")
    name = factory.LazyAttribute(lambda o: o.code.title())
    description = ""
    category = "test"


class SubscriptionPlanFactory(DjangoModelFactory):
    class Meta:
        model = SubscriptionPlan
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Plan {n}")
    slug = factory.Sequence(lambda n: f"plan-{n}")
    description = ""
    price = 19
    currency = "USD"
    billing_period = "monthly"
    max_users = 5
    max_stores = 1
    max_products = 500
    max_orders_per_month = 1000
    max_warehouses = 1
    is_active = True
    is_public = True
    sort_order = 100
    trial_days = 14


class PlanFeatureFactory(DjangoModelFactory):
    class Meta:
        model = PlanFeature

    plan = factory.SubFactory(SubscriptionPlanFactory)
    feature = factory.SubFactory(FeatureFactory)
    limit_value = None


class StoreMembershipFactory(DjangoModelFactory):
    class Meta:
        model = StoreMembership

    user = None  # required from tests
    store = None
    role = factory.SubFactory(RoleFactory)
    is_active = True
