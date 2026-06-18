"""
Tests for the AuditLog admin's read-only enforcement and CSV export.

The admin must:
- Refuse to add new rows.
- Refuse to change existing rows.
- Refuse to delete rows.
- Provide a CSV export action that produces a valid CSV with all rows.
"""

from __future__ import annotations

import csv
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.permissions.admin import AuditLogAdmin
from apps.permissions.models import AuditLog


@pytest.fixture
def audit_request(db, django_user_model):
    """A logged-in superuser request for admin actions."""
    rf = RequestFactory()
    user = django_user_model.objects.create_superuser(
        email="audit-admin@example.com", password="pw"
    )
    req = rf.get("/")
    req.user = user
    return req


@pytest.fixture
def audit_log_rows(db):
    """Three AuditLog rows for export testing."""
    rows = []
    for i in range(3):
        rows.append(
            AuditLog.objects.create(
                action=f"action_{i}",
                target_type="Role",
                target_id=str(i),
                ip_address=f"10.0.0.{i}",
                request_id=f"req-{i}",
            )
        )
    return rows


@pytest.mark.django_db
class TestAuditAdminReadOnly:
    def test_admin_disallows_add(self, audit_request):
        admin = AuditLogAdmin(AuditLog, AdminSite())
        assert admin.has_add_permission(audit_request) is False

    def test_admin_disallows_change(self, audit_request, audit_log_rows):
        admin = AuditLogAdmin(AuditLog, AdminSite())
        assert admin.has_change_permission(audit_request) is False
        # Even when an object is provided.
        assert admin.has_change_permission(audit_request, obj=audit_log_rows[0]) is False

    def test_admin_disallows_delete(self, audit_request, audit_log_rows):
        admin = AuditLogAdmin(AuditLog, AdminSite())
        assert admin.has_delete_permission(audit_request) is False
        assert admin.has_delete_permission(audit_request, obj=audit_log_rows[0]) is False


@pytest.mark.django_db
class TestAuditAdminCSVExport:
    def test_csv_export_emits_header_and_rows(self, audit_request, audit_log_rows):
        admin = AuditLogAdmin(AuditLog, AdminSite())
        response = admin.export_csv(audit_request, AuditLog.objects.all())
        body = response.content.decode("utf-8")
        reader = csv.reader(io.StringIO(body))
        rows = list(reader)
        # Header + 3 data rows.
        assert len(rows) == 4
        header = rows[0]
        assert "created_at" in header
        assert "action" in header
        assert "target_type" in header
        assert "actor_email" in header

    def test_csv_export_filters_queryset(self, audit_request, audit_log_rows):
        admin = AuditLogAdmin(AuditLog, AdminSite())
        # Only export action_1.
        qs = AuditLog.objects.filter(action="action_1")
        response = admin.export_csv(audit_request, qs)
        body = response.content.decode("utf-8")
        reader = csv.reader(io.StringIO(body))
        rows = list(reader)
        # 1 header + 1 data row.
        assert len(rows) == 2
        assert rows[1][1] == "action_1"

    def test_csv_response_content_type(self, audit_request, audit_log_rows):
        admin = AuditLogAdmin(AuditLog, AdminSite())
        response = admin.export_csv(audit_request, AuditLog.objects.all())
        assert response["Content-Type"] == "text/csv"
        assert "attachment" in response["Content-Disposition"]
        assert "audit_log.csv" in response["Content-Disposition"]


@pytest.mark.django_db
class TestAuditLogAppendOnly:
    """Sanity tests for the model-level append-only invariant."""

    def test_save_on_existing_raises(self, db, audit_log_rows):
        log = audit_log_rows[0]
        from apps.permissions.exceptions import AuditLogImmutable
        with pytest.raises(AuditLogImmutable):
            log.save()

    def test_delete_raises(self, db, audit_log_rows):
        log = audit_log_rows[0]
        from apps.permissions.exceptions import AuditLogImmutable
        with pytest.raises(AuditLogImmutable):
            log.delete()

    def test_queryset_delete_not_protected_by_model(self, db, audit_log_rows):
        """Document the Django ORM behavior: queryset.delete() bypasses
        model.delete(), so we rely on the admin-level guard to prevent
        bulk deletes."""
        from apps.permissions.exceptions import AuditLogImmutable
        # Bulk delete via queryset does NOT trigger model.delete().
        # This test asserts the actual Django ORM behavior so future devs
        # understand the protection boundary.
        # Note: AuditLog has FK to actor (User SET_NULL) — bulk delete
        # is therefore safe to call at the ORM level (won't cascade).
        try:
            AuditLog.objects.all().delete()
        except Exception as e:
            # If anything raises, document what raised.
            pytest.fail(f"queryset.delete() unexpectedly raised: {e}")
