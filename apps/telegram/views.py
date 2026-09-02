from rest_framework.response import Response
from rest_framework.views import APIView

from apps.telegram.client import TelegramClient, TelegramError
from apps.telegram.models import TelegramConnection
from apps.telegram.serializers import DiscoveredChatSerializer, TelegramConnectionSerializer
from apps.telegram.services import send_test_alert


class TelegramTestView(APIView):
    """PRD S38 point 6: sends a synthetic test alert to the authenticated
    operator's Telegram connection, through the same rendering path real
    alerts use. Uses the project's default IsAuthenticated permission --
    this triggers a real external side effect and must not be publicly
    callable. throttle_scope caps this specifically (10/hour, see
    DEFAULT_THROTTLE_RATES) tighter than the general per-user rate, since
    each call is a real Telegram API send, not just a read."""

    throttle_scope = "telegram_test"

    def post(self, request):
        try:
            connection = request.user.telegram_connection
        except TelegramConnection.DoesNotExist:
            return Response({"detail": "No Telegram connection configured for this account."}, status=400)

        if not connection.chat_id:
            return Response({"detail": "Telegram connection has no chat_id set."}, status=400)

        try:
            send_test_alert(connection)
        except TelegramError as exc:
            return Response({"success": False, "detail": str(exc)}, status=502)

        return Response({"success": True})


class TelegramConnectionView(APIView):
    """PRD S38: create/update the operator's Telegram connection and
    per-alert-type toggles. GET returns null (not 404) when none exists yet
    -- "not configured" is a normal, expected state for this page to show,
    not an error."""

    def get(self, request):
        try:
            connection = request.user.telegram_connection
        except TelegramConnection.DoesNotExist:
            return Response(None)
        return Response(TelegramConnectionSerializer(connection).data)

    def put(self, request):
        serializer = TelegramConnectionSerializer(data=request.data)
        if not serializer.is_valid():
            # A plain string {"detail": ...} matches every other error
            # response in this project (Configuration, Telegram test/
            # discover) -- raising here instead would go through the
            # generic DRF exception handler and come back shaped as
            # {"error": {"message": {...}}}, which the frontend's error
            # parsing (a plain string check) doesn't look for.
            detail = "; ".join(f"{field}: {msgs[0]}" for field, msgs in serializer.errors.items())
            return Response({"detail": detail}, status=400)
        connection, _ = TelegramConnection.objects.update_or_create(
            user=request.user, defaults=serializer.validated_data
        )
        return Response(TelegramConnectionSerializer(connection).data)


class TelegramDiscoverChatsView(APIView):
    """PRD S38 point 2 ("Connect the bot to the platform"): lists chats the
    bot has received a message from, so the user never has to hand-decode
    Telegram's raw getUpdates JSON to find their numeric chat_id (the exact
    manual process this project needed in Batch 13, now automated)."""

    def get(self, request):
        try:
            chats = TelegramClient().get_updates()
        except TelegramError as exc:
            return Response({"detail": str(exc)}, status=502)
        return Response(DiscoveredChatSerializer(chats, many=True).data)
