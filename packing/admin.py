from django.contrib import admin

from .models import BoxRecommendation


@admin.register(BoxRecommendation)
class BoxRecommendationAdmin(admin.ModelAdmin):
    list_display = ("order", "rank", "box", "box_cost", "utilization_percentage", "is_selected", "created_at")
    list_filter = ("is_selected", "strategy")
    raw_id_fields = ("order", "box")
