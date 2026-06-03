from django.urls import path

from .views import EnsureIndexView, SearchView

urlpatterns = [
    path("search", SearchView.as_view(), name="search"),
    path("ensure-index", EnsureIndexView.as_view(), name="ensure-index"),
]
