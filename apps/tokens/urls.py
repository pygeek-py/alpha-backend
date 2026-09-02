from django.urls import path

from apps.tokens.views import LiveFeedView, TokenDetailView, TokenHistoryView

urlpatterns = [
    path("live-feed/", LiveFeedView.as_view(), name="tokens-live-feed"),
    path("<int:token_id>/detail/", TokenDetailView.as_view(), name="tokens-detail"),
    path("<int:token_id>/history/", TokenHistoryView.as_view(), name="tokens-history"),
]
