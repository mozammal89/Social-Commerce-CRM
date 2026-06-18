"""
RBAC template tags.

Load with ``{% load rbac %}``.

Tags
----

    {% can "orders.create" %}...{% endcan %}
    {% can "orders.view" order %}...{% endcan %}                {# object-level #}
    {% can_any "orders.create" "orders.update" as can_act %}   {# assignable #}

    {% can_all "orders.create" "orders.update" %}
    {% has_feature "marketing_campaigns" %}
    {% can_access_resource "orders" %}
    {% user_role store as role_name %}

Filters
-------

    {{ request.user|can:"orders.create" }}
"""

from __future__ import annotations

from django import template
from django.utils.safestring import mark_safe

from ..resolver import PermissionResolver


register = template.Library()
_resolver = PermissionResolver()


# ---------------------------------------------------------------------------
# {% can "code" [obj] %}...{% endcan %}
# ---------------------------------------------------------------------------
class CanNode(template.Node):
    def __init__(self, code_expr, obj_expr=None, nodelist_true=None, nodelist_false=None):
        self.code_expr = code_expr
        self.obj_expr = obj_expr
        self.nodelist_true = nodelist_true
        self.nodelist_false = nodelist_false

    def _resolve(self, context, expr):
        try:
            return expr.resolve(context)
        except Exception:
            return None

    def render(self, context):
        request = context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        store = (
            context.get("current_store")
            or context.get("store")
            or getattr(request, "store", None)
        )
        code = self._resolve(context, self.code_expr)
        obj = self._resolve(context, self.obj_expr) if self.obj_expr else None
        ok = _resolver.check(user, store, code, obj=obj)
        if ok:
            return self.nodelist_true.render(context) if self.nodelist_true else ""
        return self.nodelist_false.render(context) if self.nodelist_false else ""


@register.tag("can")
def do_can(parser, token):
    """
    Parse ``{% can "code" [obj] %}...{% else %}...{% endcan %}``.

    The 'else' branch is optional.
    """
    bits = token.split_contents()
    if len(bits) < 2:
        raise template.TemplateSyntaxError(
            "'can' tag requires at least one argument: the permission code."
        )
    code_expr = parser.compile_filter(bits[1])
    obj_expr = parser.compile_filter(bits[2]) if len(bits) > 2 else None
    nodelist_true = parser.parse(("else", "endcan"))
    token2 = parser.next_token()
    nodelist_false = None
    if token2.contents == "else":
        nodelist_false = parser.parse(("endcan",))
        parser.delete_first_token()
    return CanNode(code_expr, obj_expr, nodelist_true, nodelist_false)


# ---------------------------------------------------------------------------
# {% can_any "code1" "code2" %} — returns True if any check passes.
# {% can_all "code1" "code2" %} — returns True if all checks pass.
# ---------------------------------------------------------------------------
@register.simple_tag(takes_context=True)
def can_any(context, *codes):
    request = context.get("request")
    user = getattr(request, "user", None) if request is not None else None
    store = (
        context.get("current_store")
        or context.get("store")
        or getattr(request, "store", None)
    )
    return any(_resolver.check(user, store, c) for c in codes)


@register.simple_tag(takes_context=True)
def can_all(context, *codes):
    request = context.get("request")
    user = getattr(request, "user", None) if request is not None else None
    store = (
        context.get("current_store")
        or context.get("store")
        or getattr(request, "store", None)
    )
    return all(_resolver.check(user, store, c) for c in codes)


# ---------------------------------------------------------------------------
# {% has_feature "marketing_campaigns" %}
# ---------------------------------------------------------------------------
@register.simple_tag(takes_context=True)
def has_feature(context, code):
    request = context.get("request")
    user = getattr(request, "user", None) if request is not None else None
    store = (
        context.get("current_store")
        or context.get("store")
        or getattr(request, "store", None)
    )
    return _resolver.check_feature(user, store, code)


# ---------------------------------------------------------------------------
# {% can_access_resource "orders" %}
# Equivalent to can "orders.view"; provided for readability.
# ---------------------------------------------------------------------------
@register.simple_tag(takes_context=True)
def can_access_resource(context, resource_code):
    request = context.get("request")
    user = getattr(request, "user", None) if request is not None else None
    store = (
        context.get("current_store")
        or context.get("store")
        or getattr(request, "store", None)
    )
    return _resolver.check(user, store, f"{resource_code}.view")


# ---------------------------------------------------------------------------
# {% user_role [store] as role_name %}
# Returns the name of the user's highest-level role in the given store.
# ---------------------------------------------------------------------------
@register.simple_tag(takes_context=True)
def user_role(context, store=None):
    request = context.get("request")
    user = getattr(request, "user", None) if request is not None else None
    store = (
        store
        or context.get("current_store")
        or context.get("store")
        or getattr(request, "store", None)
    )
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    from ..models import StoreMembership

    membership = (
        StoreMembership.objects.filter(
            user=user, store=store, is_active=True,
        )
        .select_related("role")
        .order_by("-role__level")
        .first()
    )
    return membership.role.name if membership else ""


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
@register.filter
def can(user, code):
    """``{{ request.user|can:"orders.create" }}`` — True/False."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    # No store in template context? Try the request via the user.
    # Templates that need store-aware checks should use the tag form.
    return getattr(user, "has_permission", lambda c, **kw: False)(code)


@register.filter
def has_feature_filter(user, code):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return getattr(user, "has_feature", lambda c, **kw: False)(code)