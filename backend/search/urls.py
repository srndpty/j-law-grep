from django.urls import path

from .views import EnsureIndexView, LawDocumentView, LawsView, SearchView

urlpatterns = [
    path("search", SearchView.as_view(), name="search"),
    path("laws", LawsView.as_view(), name="laws"),
    path("laws/<str:law_id>", LawDocumentView.as_view(), name="law-document"),
    path("ensure-index", EnsureIndexView.as_view(), name="ensure-index"),
]
