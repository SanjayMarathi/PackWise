import uuid

from django.db import models


class Conversation(models.Model):
    """One chat with the assistant.

    ``messages`` is the exact Claude API history (content blocks, including
    thinking blocks and tool calls/results). It is **append-only** and resent
    verbatim on every request: Claude binds its thinking blocks to the exact
    conversation prefix, so editing or dropping earlier entries would
    invalidate them. ``transcript`` is the simplified view the browser renders
    (text and result cards).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    messages = models.JSONField(default=list)
    transcript = models.JSONField(default=list)
    turns = models.PositiveIntegerField(default=0)
    # Set while a turn is being answered, so two requests can't interleave appends.
    busy_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Conversation {self.pk} ({self.turns} turns)"
