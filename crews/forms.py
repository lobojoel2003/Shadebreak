from __future__ import annotations

import zoneinfo

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import Assignment, Crew, JobSite, Worker
from .phones import normalize_phone

COMMON_TIMEZONES = [
    ("America/New_York", _("Eastern (New York)")),
    ("America/Chicago", _("Central (Chicago)")),
    ("America/Denver", _("Mountain (Denver)")),
    ("America/Phoenix", _("Arizona (Phoenix, no daylight saving)")),
    ("America/Los_Angeles", _("Pacific (Los Angeles)")),
    ("America/Anchorage", _("Alaska (Anchorage)")),
    ("Pacific/Honolulu", _("Hawaii (Honolulu)")),
    ("America/Puerto_Rico", _("Atlantic (Puerto Rico)")),
    ("Pacific/Guam", _("Chamorro (Guam)")),
]

WEEKDAY_CHOICES = [
    ("0", _("Mon")),
    ("1", _("Tue")),
    ("2", _("Wed")),
    ("3", _("Thu")),
    ("4", _("Fri")),
    ("5", _("Sat")),
    ("6", _("Sun")),
]


def timezone_choices(current: str | None = None):
    choices = list(COMMON_TIMEZONES)
    known = {value for value, _label in choices}
    if current and current not in known and current in zoneinfo.available_timezones():
        choices.append((current, current))
    return choices


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kwargs):
        super().__init__(format="%H:%M", **kwargs)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class PhoneField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)
        self.widget.attrs.update({"inputmode": "tel", "autocomplete": "tel", "placeholder": "(602) 555-0142"})

    def clean(self, value):
        return normalize_phone(super().clean(value) or "")


class CrewForm(forms.ModelForm):
    lead_phone = PhoneField(
        label=_("Crew lead mobile"),
        help_text=_("Gets an alert when a check-in is missed or someone needs help."),
    )

    class Meta:
        model = Crew
        fields = [
            "name",
            "lead_name",
            "lead_phone",
            "timezone",
            "language",
            "emergency_number",
            "sms_enabled",
            "water_reminders",
        ]
        widgets = {"timezone": forms.Select}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["timezone"].widget.choices = timezone_choices(
            self.instance.timezone if self.instance else None
        )


class SignupForm(UserCreationForm):
    crew_name = forms.CharField(label=_("Crew or company name"), max_length=120)
    lead_name = forms.CharField(label=_("Your name"), max_length=120)
    timezone = forms.ChoiceField(label=_("Time zone"), choices=COMMON_TIMEZONES, initial="America/Phoenix")

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            crew = Crew.objects.create(
                name=self.cleaned_data["crew_name"],
                lead_name=self.cleaned_data["lead_name"],
                timezone=self.cleaned_data["timezone"],
            )
            crew.leads.add(user)
        return user


class SiteForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        label=_("Work days"), choices=WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    latitude = forms.DecimalField(label=_("Latitude"), max_digits=7, decimal_places=4, required=False)
    longitude = forms.DecimalField(label=_("Longitude"), max_digits=8, decimal_places=4, required=False)

    class Meta:
        model = JobSite
        fields = [
            "name",
            "address",
            "latitude",
            "longitude",
            "exposure",
            "workload",
            "clothing",
            "shift_start",
            "shift_end",
            "weekdays",
            "water_location",
            "shade_location",
            "nearest_hospital",
            "notes",
            "active",
        ]
        widgets = {
            "shift_start": TimeInput(),
            "shift_end": TimeInput(),
            "exposure": forms.RadioSelect,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, crew: Crew, **kwargs):
        self.crew = crew
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["weekdays"] = list(self.instance.weekdays)
        else:
            self.initial.setdefault("weekdays", list("01234"))
            del self.fields["active"]  # new sites start active

    def clean_weekdays(self):
        return "".join(sorted(self.cleaned_data["weekdays"]))

    def clean(self):
        cleaned = super().clean()
        lat, lon = cleaned.get("latitude"), cleaned.get("longitude")
        if (lat is None) != (lon is None):
            raise forms.ValidationError(_("Enter both latitude and longitude, or neither."))
        if lat is None and not cleaned.get("address"):
            raise forms.ValidationError(_("Enter an address or use your location."))
        if lat is None:
            from .services.geocode import geocode

            found = geocode(cleaned["address"])
            if not found:
                raise forms.ValidationError(
                    _("We could not find that address. Use your location or enter latitude and longitude.")
                )
            cleaned["latitude"], cleaned["longitude"] = found
            self.instance.latitude, self.instance.longitude = found
        return cleaned

    def save(self, commit=True):
        site = super().save(commit=False)
        site.crew = self.crew
        if self.instance.pk and {"latitude", "longitude"} & set(self.changed_data):
            site.nws_grid_id, site.nws_grid_x, site.nws_grid_y, site.nws_place = "", None, None, ""
            site.timezone = ""
        if commit:
            site.save()
        return site


class WorkerForm(forms.ModelForm):
    phone = PhoneField(label=_("Mobile number"))

    class Meta:
        model = Worker
        fields = [
            "name",
            "phone",
            "language",
            "experience",
            "start_date",
            "site",
            "buddy",
            "sms_opt_in",
            "active",
            "notes",
        ]
        widgets = {"start_date": DateInput(), "experience": forms.RadioSelect}

    def __init__(self, *args, crew: Crew, **kwargs):
        self.crew = crew
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = crew.sites.filter(active=True)
        buddies = crew.workers.filter(active=True)
        if self.instance.pk:
            buddies = buddies.exclude(pk=self.instance.pk)
        else:
            del self.fields["active"]  # new workers start active
        self.fields["buddy"].queryset = buddies
        self.fields["language"].widget = forms.RadioSelect(choices=self.fields["language"].choices)

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if phone and self.crew.workers.filter(phone=phone).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Another worker on this crew already has this number."))
        return phone

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("sms_opt_in") and not cleaned.get("phone"):
            self.add_error("phone", _("Add a mobile number to send texts."))
        return cleaned

    def save(self, commit=True):
        worker = super().save(commit=False)
        worker.crew = self.crew
        if commit:
            previous = (
                Worker.objects.filter(pk=worker.pk).values_list("buddy_id", flat=True).first()
                if worker.pk
                else None
            )
            worker.save()
            # Keep standing buddies mutual.
            if previous and previous != worker.buddy_id:
                Worker.objects.filter(pk=previous, buddy=worker).update(buddy=None)
            if worker.buddy_id:
                Worker.objects.filter(buddy=worker.buddy).exclude(pk=worker.pk).update(buddy=None)
                Worker.objects.filter(pk=worker.buddy_id).update(buddy=worker)
        return worker


class AssignmentForm(forms.ModelForm):
    EXPOSURE_CHOICES = [("", _("Follow schedule"))] + [(str(p), f"{p}%") for p in (20, 40, 50, 60, 80, 100)]
    exposure_override = forms.TypedChoiceField(
        label=_("Time in heat"), choices=EXPOSURE_CHOICES, coerce=int, empty_value=None, required=False
    )

    class Meta:
        model = Assignment
        fields = ["status", "buddy", "exposure_override"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workday = self.instance.workday
        self.fields["buddy"].queryset = Worker.objects.filter(
            assignments__workday=workday, assignments__status=Assignment.Status.SCHEDULED
        ).exclude(pk=self.instance.worker_id)
        self.fields["buddy"].empty_label = _("Pick automatically")

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.buddy_manual = assignment.buddy_id is not None
        if commit:
            assignment.save()
        return assignment
