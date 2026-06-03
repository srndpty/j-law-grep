from django.urls import path

from .views import EnsureIndexView, LawsView, SearchView

urlpatterns = [
    path("search", SearchView.as_view(), name="search"),
    path("laws", LawsView.as_view(), name="laws"),
    path("ensure-index", EnsureIndexView.as_view(), name="ensure-index"),
]
