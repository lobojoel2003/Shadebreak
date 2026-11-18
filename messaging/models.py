from django.db import models
from django.utils.translation import gettext_lazy as _


class Message(models.Model):
    class Direction(models.TextChoices):
        OUTBOUND = "out", _("Sent")
        INBOUND = "in", _("Received")

    class Kind(models.TextChoices):
        BRIEFING = "briefing", _("Morning briefing")
        BREAK = "break", _("Break reminder")
        WATER = "water", _("Water reminder")
        CHECKIN = "checkin", _("Buddy check-in")
        ESCALATION = "escalation", _("Alert to crew lead")
        REPLY = "reply", _("Reply")
        INBOUND = "inbound", _("Incoming text")

    class Status(models.TextChoices):
        QUEUED = "queued", _("Scheduled")
        SENDING = "sending", _("Sending")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        EXPIRED = "expired", _("Skipped (too late)")
        RECEIVED = "received", _("Received")

    crew = models.ForeignKey("crews.Crew", on_delete=models.CASCADE, null=True, related_name="messages")
    workday = models.ForeignKey(
        "crews.WorkDay", on_delete=models.CASCADE, null=True, blank=True, related_name="messages"
    )
    worker = models.ForeignKey(
        "crews.Worker", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )
    checkin = models.ForeignKey(
        "crews.CheckIn", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )
    # A check-in prompt can ask about several people at once (one text per buddy).
    checkins = models.ManyToManyField("crews.CheckIn", blank=True, related_name="prompts")
    direction = models.CharField(max_length=3, choices=Direction.choices, default=Direction.OUTBOUND)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    to_number = models.CharField(max_length=20, blank=True)
    from_number = models.CharField(max_length=20, blank=True)
    body = models.TextField()
    language = models.CharField(max_length=2, default="en")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    send_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    provider_id = models.CharField(max_length=64, blank=True)
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "send_at"])]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.kind} {self.to_number or self.from_number}"

    @property
    def when(self):
        return self.sent_at or self.send_at or self.created_at
