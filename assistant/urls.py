from django.urls import path

from .views import AssistantChatView, AssistantStatusView, ConversationView

urlpatterns = [
    path("assistant/status/", AssistantStatusView.as_view(), name="assistant-status"),
    path("assistant/chat/", AssistantChatView.as_view(), name="assistant-chat"),
    path("assistant/conversations/<uuid:conversation_id>/", ConversationView.as_view(), name="assistant-conversation"),
]
