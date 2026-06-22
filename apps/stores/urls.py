"""
URL configuration for stores app.
"""

from django.urls import path
from apps.stores.views import (
    StoreListView,
    StoreDetailView,
    manage_store_staff,
    MyStoresView,
    create_store_template,
    store_list_template,
    store_detail_template,
    store_edit_template,
)

app_name = "stores"

urlpatterns = [
    path("", StoreListView.as_view(), name="store_list"),
    path("list/", store_list_template, name="store_list_html"),
    path("create/", create_store_template, name="create"),
    path("my-stores/", MyStoresView.as_view(), name="my_stores"),
    path("<uuid:store_id>/view/", store_detail_template, name="store_detail_html"),
    path("<uuid:store_id>/edit/", store_edit_template, name="store_edit_html"),
    path("<uuid:id>/", StoreDetailView.as_view(), name="store_detail"),
    path("<uuid:store_id>/staff/", manage_store_staff, name="manage_staff"),
]
