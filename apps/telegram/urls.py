from django.urls import path

from apps.telegram.views import TelegramConnectionView, TelegramDiscoverChatsView, TelegramTestView

urlpatterns = [
    path("test/", TelegramTestView.as_view(), name="telegram-test"),
    path("connection/", TelegramConnectionView.as_view(), name="telegram-connection"),
    path("discover-chats/", TelegramDiscoverChatsView.as_view(), name="telegram-discover-chats"),
]
