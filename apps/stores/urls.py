"""
URL configuration for stores app.
"""

from django.urls import path
from apps.stores.views import (
    StoreListView,
    StoreDetailView,
    manage_store_staff,
    MyStoresView,
)

app_name = "stores"

urlpatterns = [
    path("", StoreListView.as_view(), name="store_list"),
    path("my-stores/", MyStoresView.as_view(), name="my_stores"),
    path("<uuid:id>/", StoreDetailView.as_view(), name="store_detail"),
    path("<uuid:store_id>/staff/", manage_store_staff, name="manage_staff"),
]
