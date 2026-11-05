from django.contrib import admin

from .models import Conversation


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "turns", "created_at", "updated_at")
    readonly_fields = ("id", "messages", "transcript", "turns", "busy_since", "created_at", "updated_at")
