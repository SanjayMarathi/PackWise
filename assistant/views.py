from datetime import timedelta
from itertools import chain

from django.conf import settings
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import ConflictError, ServiceUnavailableError
from common.serializers import StrictFieldsMixin

from . import agent
from .models import Conversation

# A turn whose worker died never clears its busy flag; treat it as abandoned after this long.
STALE_BUSY_AFTER = timedelta(minutes=3)


class ChatRequestSerializer(StrictFieldsMixin, serializers.Serializer):
    message = serializers.CharField(trim_whitespace=True, help_text="What the user typed.")
    conversation_id = serializers.UUIDField(required=False, allow_null=True, help_text="Omit to start a new chat.")

    def validate_message(self, value):
        limit = settings.PACKWISE_ASSISTANT["MAX_MESSAGE_CHARS"]
        if len(value) > limit:
            raise serializers.ValidationError(f"Keep messages under {limit} characters.")
        return value


def _config():
    return settings.PACKWISE_ASSISTANT


class NDJSONRenderer(JSONRenderer):
    """Lets clients send ``Accept: application/x-ndjson`` for the chat stream.

    Without it, DRF's content negotiation answers 406 before the view runs. Error
    responses (400/409/503) rendered through it are still a single JSON object.
    """

    media_type = "application/x-ndjson"
    format = "ndjson"


class AssistantStatusView(APIView):
    @extend_schema(
        tags=["assistant"],
        summary="Whether the AI assistant is configured",
        responses=inline_serializer(
            "AssistantStatus", {"enabled": serializers.BooleanField(), "model": serializers.CharField()}
        ),
    )
    def get(self, request):
        return Response({"enabled": agent.assistant_enabled(), "model": _config()["MODEL"]})


class AssistantChatView(APIView):
    throttle_scope = "assistant"  # every turn calls a paid model, so the limit is tighter than the API's
    renderer_classes = [JSONRenderer, NDJSONRenderer]

    @extend_schema(
        tags=["assistant"],
        summary="Send a message to the AI assistant (streamed reply)",
        description=(
            "Streams `application/x-ndjson`: one JSON event per line. Event types: `conversation` (its id), "
            "`status` (a tool is running), `text` (answer text, incremental), `card` (structured result, "
            "e.g. a box recommendation), `error`, `done`. The assistant calls the same services as the API: "
            "catalogue lookups, the 3D packing engine, and order creation."
        ),
        request=ChatRequestSerializer,
        responses={
            200: OpenApiResponse(OpenApiTypes.STR, description="NDJSON event stream"),
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
            429: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request):
        if not agent.assistant_enabled():
            raise ServiceUnavailableError(
                "The AI assistant is not configured on this server (missing ANTHROPIC_API_KEY).",
                code="assistant_unavailable",
            )
        params = ChatRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        conversation_id = params.validated_data.get("conversation_id")
        if conversation_id:
            conversation = get_object_or_404(Conversation, pk=conversation_id)
        else:
            conversation = Conversation.objects.create()

        if conversation.turns >= _config()["MAX_TURNS"]:
            raise ConflictError("This conversation is full. Start a new chat.", code="conversation_full")

        # Claim the conversation atomically. Two overlapping turns would interleave their appends.
        now = timezone.now()
        claimed = (
            Conversation.objects.filter(pk=conversation.pk)
            .filter(Q(busy_since__isnull=True) | Q(busy_since__lt=now - STALE_BUSY_AFTER))
            .update(busy_since=now)
        )
        if not claimed:
            raise ConflictError("Still answering your previous message.", code="conversation_busy")
        conversation.refresh_from_db()

        events = chain(
            [{"type": "conversation", "id": str(conversation.pk)}],
            agent.run_turn(conversation, params.validated_data["message"]),
            [{"type": "done"}],
        )
        response = StreamingHttpResponse(agent.encode_events(events), content_type="application/x-ndjson")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # ask proxies not to buffer the stream
        return response


class ConversationView(APIView):
    @extend_schema(
        tags=["assistant"],
        summary="A conversation's transcript (to restore the chat after a page reload)",
        responses={200: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
    )
    def get(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        return Response(
            {
                "id": str(conversation.pk),
                "turns": conversation.turns,
                "max_turns": _config()["MAX_TURNS"],
                "transcript": conversation.transcript,
            }
        )
