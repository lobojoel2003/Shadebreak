from django.contrib import admin

from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "direction",
        "kind",
        "to_number",
        "from_number",
        "status",
        "send_at",
        "sent_at",
    )
    list_filter = ("direction", "kind", "status", "crew")
    search_fields = ("body", "to_number", "from_number", "provider_id")
    raw_id_fields = ("workday", "worker", "checkin")
    date_hierarchy = "created_at"
