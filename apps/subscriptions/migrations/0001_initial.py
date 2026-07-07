# Generated migration for moving subscription models from permissions app

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('permissions', '0006_alter_subscription_stripe_customer_id_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # Create Feature model in subscriptions app state
                migrations.CreateModel(
                    name='Feature',
                    fields=[
                        ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ('code', models.CharField(max_length=64, unique=True)),
                        ('name', models.CharField(max_length=128)),
                        ('description', models.TextField(blank=True)),
                        ('category', models.CharField(db_index=True, max_length=64)),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'ordering': ('category', 'code'),
                        'abstract': False,
                    },
                ),
                # Create SubscriptionPlan model
                migrations.CreateModel(
                    name='SubscriptionPlan',
                    fields=[
                        ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ('name', models.CharField(max_length=64)),
                        ('slug', models.SlugField(unique=True)),
                        ('description', models.TextField(blank=True)),
                        ('price', models.DecimalField(decimal_places=2, max_digits=10)),
                        ('currency', models.CharField(default='USD', max_length=3)),
                        ('billing_period', models.CharField(choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')], default='monthly', max_length=8)),
                        ('max_users', models.PositiveIntegerField(default=5)),
                        ('max_stores', models.PositiveIntegerField(default=1)),
                        ('max_products', models.PositiveIntegerField(default=500)),
                        ('max_orders_per_month', models.PositiveIntegerField(default=1000)),
                        ('max_warehouses', models.PositiveIntegerField(default=1)),
                        ('is_active', models.BooleanField(default=True)),
                        ('is_public', models.BooleanField(default=True, help_text='Hide internal/legacy plans from the catalog.')),
                        ('sort_order', models.PositiveSmallIntegerField(default=100)),
                        ('trial_days', models.PositiveSmallIntegerField(default=14)),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        ('features', models.ManyToManyField(related_name='plans', through='subscriptions.PlanFeature', to='subscriptions.feature')),
                    ],
                    options={
                        'ordering': ('sort_order', 'price'),
                        'abstract': False,
                    },
                ),
                # Create PlanFeature model
                migrations.CreateModel(
                    name='PlanFeature',
                    fields=[
                        ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ('plan', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='plan_features', to='subscriptions.subscriptionplan')),
                        ('feature', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='plan_features', to='subscriptions.feature')),
                        ('limit_value', models.PositiveIntegerField(blank=True, help_text='NULL = unlimited within the feature.', null=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'abstract': False,
                    },
                ),
                # Create Subscription model
                migrations.CreateModel(
                    name='Subscription',
                    fields=[
                        ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ('store', models.OneToOneField(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name='subscription', to='stores.store')),
                        ('tenant', models.OneToOneField(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name='subscription', to='accounts.tenant')),
                        ('plan', models.ForeignKey(on_delete=models.deletion.PROTECT, related_name='subscriptions', to='subscriptions.subscriptionplan')),
                        ('status', models.CharField(choices=[('trialing', 'Trialing'), ('active', 'Active'), ('past_due', 'Past Due'), ('canceled', 'Canceled'), ('expired', 'Expired')], default='trialing', max_length=12)),
                        ('starts_at', models.DateTimeField()),
                        ('ends_at', models.DateTimeField(blank=True, null=True)),
                        ('trial_ends_at', models.DateTimeField(blank=True, null=True)),
                        ('current_period_start', models.DateTimeField(blank=True, null=True)),
                        ('current_period_end', models.DateTimeField(blank=True, null=True)),
                        ('stripe_customer_id', models.CharField(blank=True, max_length=64, null=True)),
                        ('stripe_subscription_id', models.CharField(blank=True, max_length=64, null=True)),
                        ('metadata', models.JSONField(blank=True, default=dict)),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'abstract': False,
                    },
                ),
                # Create SubscriptionEvent model
                migrations.CreateModel(
                    name='SubscriptionEvent',
                    fields=[
                        ('id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ('subscription', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='events', to='subscriptions.subscription')),
                        ('event_type', models.CharField(db_index=True, max_length=32)),
                        ('occurred_at', models.DateTimeField()),
                        ('metadata', models.JSONField(blank=True, default=dict)),
                        ('actor', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='subscription_events', to='accounts.user')),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        'ordering': ('-occurred_at',),
                        'abstract': False,
                    },
                ),
            ],
            database_operations=[
                # No database changes - tables already exist
            ],
        ),
    ]
