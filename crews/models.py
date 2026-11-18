from __future__ import annotations

import zoneinfo
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from heat import risk as heat_risk
from heat.units import c_to_f

from .phones import display_phone, normalize_phone

LANGUAGE_CHOICES = [("en", "English"), ("es", "Español")]


def validate_timezone(value: str) -> None:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(_("Unknown time zone.")) from exc


def validate_weekdays(value: str) -> None:
    if not value or any(ch not in "0123456" for ch in value) or len(set(value)) != len(value):
        raise ValidationError(_("Pick at least one work day."))


class RiskLevel(models.IntegerChoices):
    LOW = 0, _("Low")
    CAUTION = 1, _("Caution")
    HIGH = 2, _("High")
    VERY_HIGH = 3, _("Very high")
    EXTREME = 4, _("Extreme")


class Workload(models.TextChoices):
    LIGHT = "light", _("Light: walking, light hand work, driving equipment")
    MODERATE = "moderate", _("Moderate: mowing, pruning, steady hand and arm work")
    HEAVY = "heavy", _("Heavy: digging, shoveling, carrying, roofing")
    VERY_HEAVY = "very_heavy", _("Very heavy: fast shoveling, heavy lifting, hauling")


class Exposure(models.TextChoices):
    SUN = "sun", _("Full sun")
    PARTIAL = "partial", _("Partly shaded")
    SHADE = "shade", _("Mostly shaded")


class Clothing(models.TextChoices):
    STANDARD = "standard", _("Regular work clothes or cloth coveralls")
    DOUBLE = "double", _("Double-layer woven coveralls")
    POLYOLEFIN = "polyolefin", _("Polyolefin coveralls (for example Tyvek)")
    VAPOR_BARRIER = "vapor_barrier", _("Vapor-barrier chemical suits")


class Experience(models.TextChoices):
    NEW = "new", _("New to hot outdoor work")
    RETURNING = "returning", _("Done hot work before, but new to the crew or back from time off")
    ACCLIMATIZED = "acclimatized", _("Already working in the heat")


class Crew(models.Model):
    name = models.CharField(_("crew name"), max_length=120)
    language = models.CharField(_("plan language"), max_length=2, choices=LANGUAGE_CHOICES, default="en")
    timezone = models.CharField(
        _("time zone"), max_length=64, default="America/Phoenix", validators=[validate_timezone]
    )
    leads = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="crews", blank=True)
    lead_name = models.CharField(_("crew lead name"), max_length=120, blank=True)
    lead_phone = models.CharField(
        _("crew lead mobile"),
        max_length=20,
        blank=True,
        help_text=_("Gets an alert when a check-in is missed or someone needs help."),
    )
    lead_opted_out = models.BooleanField(
        default=False, help_text="The crew lead replied STOP; no texts go to the lead's number."
    )
    emergency_number = models.CharField(_("emergency number"), max_length=20, default="911")
    sms_enabled = models.BooleanField(_("send text messages"), default=True)
    water_reminders = models.BooleanField(_("hourly water reminders at High heat and above"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("crew")
        verbose_name_plural = _("crews")

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.lead_phone:
            self.lead_phone = normalize_phone(self.lead_phone)

    @property
    def tz(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.timezone)

    def today(self) -> date:
        return timezone.now().astimezone(self.tz).date()


class JobSite(models.Model):
    crew = models.ForeignKey(Crew, on_delete=models.CASCADE, related_name="sites")
    name = models.CharField(_("site name"), max_length=120)
    address = models.CharField(_("address"), max_length=255, blank=True)
    latitude = models.DecimalField(
        _("latitude"),
        max_digits=7,
        decimal_places=4,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        _("longitude"),
        max_digits=8,
        decimal_places=4,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    exposure = models.CharField(
        _("sun exposure"), max_length=10, choices=Exposure.choices, default=Exposure.SUN
    )
    workload = models.CharField(
        _("typical workload"), max_length=12, choices=Workload.choices, default=Workload.MODERATE
    )
    clothing = models.CharField(
        _("clothing"), max_length=16, choices=Clothing.choices, default=Clothing.STANDARD
    )
    shift_start = models.TimeField(_("shift starts"), default=time(6, 0))
    shift_end = models.TimeField(_("shift ends"), default=time(14, 30))
    weekdays = models.CharField(_("work days"), max_length=7, default="01234", validators=[validate_weekdays])
    water_location = models.CharField(_("where the water is"), max_length=200, blank=True)
    shade_location = models.CharField(_("where the shade is"), max_length=200, blank=True)
    nearest_hospital = models.CharField(_("nearest hospital or urgent care"), max_length=255, blank=True)
    notes = models.TextField(_("notes for the plan"), blank=True)
    active = models.BooleanField(_("active"), default=True)

    # Cached from the NWS /points endpoint.
    timezone = models.CharField(max_length=64, blank=True, validators=[validate_timezone])
    nws_grid_id = models.CharField(max_length=8, blank=True)
    nws_grid_x = models.PositiveIntegerField(null=True, blank=True)
    nws_grid_y = models.PositiveIntegerField(null=True, blank=True)
    nws_place = models.CharField(max_length=120, blank=True)
    elevation_m = models.FloatField(null=True, blank=True)
    forecast_updated_at = models.DateTimeField(null=True, blank=True)
    forecast_error = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("job site")
        verbose_name_plural = _("job sites")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("site_edit", args=[self.pk])

    def clean(self) -> None:
        if self.shift_start == self.shift_end:
            raise ValidationError({"shift_end": _("The shift must end at a different time.")})

    @property
    def tz(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.timezone or self.crew.timezone)

    @property
    def weekday_list(self) -> list[int]:
        return [int(ch) for ch in self.weekdays]

    def works_on(self, day: date) -> bool:
        return str(day.weekday()) in self.weekdays

    @property
    def workload_short(self) -> str:
        return str(
            {
                Workload.LIGHT: _("Light work"),
                Workload.MODERATE: _("Moderate work"),
                Workload.HEAVY: _("Heavy work"),
                Workload.VERY_HEAVY: _("Very heavy work"),
            }.get(self.workload, self.workload)
        )

    @property
    def clothing_adjustment_c(self) -> float:
        return heat_risk.CLOTHING_ADJUSTMENT_C[heat_risk.Clothing(self.clothing)]

    @property
    def has_grid(self) -> bool:
        return bool(self.nws_grid_id) and self.nws_grid_x is not None and self.nws_grid_y is not None


class Worker(models.Model):
    crew = models.ForeignKey(Crew, on_delete=models.CASCADE, related_name="workers")
    name = models.CharField(_("name"), max_length=120)
    phone = models.CharField(_("mobile number"), max_length=20, blank=True)
    language = models.CharField(_("language"), max_length=2, choices=LANGUAGE_CHOICES, default="en")
    experience = models.CharField(
        _("heat experience"), max_length=16, choices=Experience.choices, default=Experience.NEW
    )
    start_date = models.DateField(_("first day on this crew"), default=date.today)
    site = models.ForeignKey(
        JobSite,
        verbose_name=_("usual site"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regulars",
    )
    buddy = models.ForeignKey(
        "self",
        verbose_name=_("buddy"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    sms_opt_in = models.BooleanField(
        _("agreed to get text messages"),
        default=False,
        help_text=_("Only text people who said yes. Replying STOP turns texts off."),
    )
    active = models.BooleanField(_("active"), default=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("worker")
        verbose_name_plural = _("workers")
        constraints = [
            models.UniqueConstraint(
                fields=["crew", "phone"],
                condition=~models.Q(phone=""),
                name="unique_worker_phone_per_crew",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        self.phone = normalize_phone(self.phone)
        if self.buddy_id and self.buddy_id == self.pk:
            raise ValidationError({"buddy": _("A worker cannot be their own buddy.")})

    @property
    def experience_short(self) -> str:
        return str(
            {
                Experience.NEW: _("New to heat work"),
                Experience.RETURNING: _("Returning or new to crew"),
                Experience.ACCLIMATIZED: _("Acclimatized"),
            }.get(self.experience, self.experience)
        )

    @property
    def phone_display(self) -> str:
        return display_phone(self.phone)

    @property
    def can_text(self) -> bool:
        return bool(self.phone) and self.sms_opt_in and self.active

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else ""


class HourlyForecast(models.Model):
    class Source(models.TextChoices):
        NWS = "nws", "National Weather Service"
        SAMPLE = "sample", _("Sample data")

    site = models.ForeignKey(JobSite, on_delete=models.CASCADE, related_name="forecasts")
    start = models.DateTimeField()
    temperature_c = models.FloatField()
    dewpoint_c = models.FloatField()
    relative_humidity = models.FloatField()
    wind_speed_ms = models.FloatField()
    sky_cover = models.FloatField(null=True, blank=True)
    precip_probability = models.FloatField(null=True, blank=True)
    solar_wm2 = models.FloatField(default=0)
    heat_index_f = models.FloatField()
    wbgt_c = models.FloatField()
    wbgt_shade_c = models.FloatField()
    wbgt_source = models.CharField(max_length=10, default="estimated")
    risk = models.PositiveSmallIntegerField(choices=RiskLevel.choices)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.NWS)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["site", "start"]
        constraints = [
            models.UniqueConstraint(fields=["site", "start"], name="unique_forecast_hour"),
        ]
        indexes = [models.Index(fields=["site", "start"])]

    def __str__(self) -> str:
        return f"{self.site} {self.start:%Y-%m-%d %H:%M}Z"

    @property
    def temperature_f(self) -> float:
        return c_to_f(self.temperature_c)

    @property
    def wbgt_f(self) -> float:
        return c_to_f(self.wbgt_c)

    @property
    def wbgt_shade_f(self) -> float:
        return c_to_f(self.wbgt_shade_c)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=1)


class WorkDay(models.Model):
    site = models.ForeignKey(JobSite, on_delete=models.CASCADE, related_name="workdays")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    workers = models.ManyToManyField(
        Worker, through="Assignment", through_fields=("workday", "worker"), related_name="workdays"
    )
    peak_risk = models.PositiveSmallIntegerField(choices=RiskLevel.choices, null=True, blank=True)
    peak_wbgt_c = models.FloatField(null=True, blank=True)
    peak_heat_index_f = models.FloatField(null=True, blank=True)
    peak_at = models.DateTimeField(null=True, blank=True)
    planned_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["date", "site__name"]
        constraints = [models.UniqueConstraint(fields=["site", "date"], name="unique_site_day")]

    def __str__(self) -> str:
        return f"{self.site} · {self.date:%Y-%m-%d}"

    def get_absolute_url(self) -> str:
        return reverse("workday", args=[self.pk])

    @property
    def crew(self) -> Crew:
        return self.site.crew

    @property
    def shift_start(self) -> datetime:
        return datetime.combine(self.date, self.start_time, tzinfo=self.site.tz)

    @property
    def shift_end(self) -> datetime:
        end = datetime.combine(self.date, self.end_time, tzinfo=self.site.tz)
        if end <= self.shift_start:  # night shift that ends after midnight
            end += timedelta(days=1)
        return end

    @property
    def is_heat_day(self) -> bool:
        return self.peak_risk is not None and self.peak_risk >= RiskLevel.CAUTION

    @property
    def peak_wbgt_f(self) -> float | None:
        return c_to_f(self.peak_wbgt_c) if self.peak_wbgt_c is not None else None


class Assignment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Scheduled")
        ABSENT = "absent", _("Absent")
        SENT_HOME = "sent_home", _("Sent home or to care")

    workday = models.ForeignKey(WorkDay, on_delete=models.CASCADE, related_name="assignments")
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="assignments")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    buddy = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name="buddy_assignments"
    )
    buddy_manual = models.BooleanField(default=False)
    first_week = models.BooleanField(default=False)
    acclimatization_day = models.PositiveSmallIntegerField(null=True, blank=True)
    acclimatization_days = models.PositiveSmallIntegerField(null=True, blank=True)
    exposure_percent = models.PositiveSmallIntegerField(default=100)
    exposure_override = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_("Leave empty to follow the acclimatization schedule."),
    )
    planned_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["worker__name"]
        constraints = [
            models.UniqueConstraint(fields=["workday", "worker"], name="unique_assignment"),
        ]

    def __str__(self) -> str:
        return f"{self.worker} @ {self.workday}"

    @property
    def present(self) -> bool:
        return self.status == self.Status.SCHEDULED

    @property
    def acclimatizing(self) -> bool:
        return self.exposure_percent < 100

    @property
    def needs_extra_care(self) -> bool:
        return self.first_week or self.acclimatizing

    @property
    def reduced_today(self) -> bool:
        """Acclimatizing and actually stopping before the end of the shift."""
        return bool(self.acclimatizing and self.planned_end and self.planned_end < self.workday.shift_end)

    @property
    def ramp_steps(self) -> list[str]:
        if not self.acclimatization_days or not self.acclimatization_day:
            return []
        return [
            "done"
            if step < self.acclimatization_day
            else ("today" if step == self.acclimatization_day else "")
            for step in range(1, self.acclimatization_days + 1)
        ]


class Break(models.Model):
    class Reason(models.TextChoices):
        WORK_REST = "work_rest", _("Work/rest limit")
        TWO_HOUR = "two_hour", _("15 minutes every 2 hours")
        NEW_WORKERS = "new_workers", _("Extra rest for new workers")
        STOP = "stop", _("Too hot for this work")

    workday = models.ForeignKey(WorkDay, on_delete=models.CASCADE, related_name="breaks")
    end = models.DateTimeField()
    minutes = models.PositiveSmallIntegerField()
    new_worker_minutes = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=12, choices=Reason.choices)
    risk = models.PositiveSmallIntegerField(choices=RiskLevel.choices)
    wbgt_c = models.FloatField()
    heat_index_f = models.FloatField()
    stop = models.BooleanField(default=False)
    new_worker_stop = models.BooleanField(default=False)

    class Meta:
        ordering = ["end"]

    def __str__(self) -> str:
        return f"{self.minutes} min ending {self.end:%H:%M}"

    @property
    def start(self) -> datetime:
        return self.end - timedelta(minutes=self.minutes)

    @property
    def new_worker_start(self) -> datetime:
        return self.end - timedelta(minutes=self.new_worker_minutes)

    @property
    def earliest_start(self) -> datetime:
        return self.end - timedelta(minutes=max(self.minutes, self.new_worker_minutes))

    @property
    def crew_wide(self) -> bool:
        return self.minutes > 0

    @property
    def wbgt_f(self) -> float:
        return c_to_f(self.wbgt_c)


class CheckIn(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        OK = "ok", _("OK")
        HELP = "help", _("Needs help")
        MISSED = "missed", _("No reply")

    workday = models.ForeignKey(WorkDay, on_delete=models.CASCADE, related_name="checkins")
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="checkins")
    buddy = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name="checkins_asked"
    )
    due_at = models.DateTimeField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    response = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["due_at", "worker__name"]
        indexes = [models.Index(fields=["status", "due_at"])]

    def __str__(self) -> str:
        return f"Check on {self.worker} at {self.due_at:%H:%M}"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def is_due(self) -> bool:
        return self.due_at <= timezone.now()
