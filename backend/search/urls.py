from django.urls import path

from .views import ReindexView, SearchView

urlpatterns = [
    path("search", SearchView.as_view(), name="search"),
    path("reindex", ReindexView.as_view(), name="reindex"),
]
