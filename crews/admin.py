from django.contrib import admin

from .models import Assignment, Break, CheckIn, Crew, HourlyForecast, JobSite, WorkDay, Worker


@admin.register(Crew)
class CrewAdmin(admin.ModelAdmin):
    list_display = ("name", "lead_name", "timezone", "language", "sms_enabled")
    filter_horizontal = ("leads",)
    search_fields = ("name", "lead_name")


@admin.register(JobSite)
class JobSiteAdmin(admin.ModelAdmin):
    list_display = ("name", "crew", "nws_place", "exposure", "workload", "active", "forecast_updated_at")
    list_filter = ("active", "exposure", "workload", "crew")
    search_fields = ("name", "address")
    readonly_fields = (
        "nws_grid_id",
        "nws_grid_x",
        "nws_grid_y",
        "nws_place",
        "elevation_m",
        "forecast_updated_at",
    )


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ("name", "crew", "phone", "language", "experience", "start_date", "sms_opt_in", "active")
    list_filter = ("crew", "language", "experience", "active", "sms_opt_in")
    search_fields = ("name", "phone")
    raw_id_fields = ("buddy",)


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    raw_id_fields = ("worker", "buddy")


class BreakInline(admin.TabularInline):
    model = Break
    extra = 0


@admin.register(WorkDay)
class WorkDayAdmin(admin.ModelAdmin):
    list_display = ("date", "site", "peak_risk", "planned_at")
    list_filter = ("site__crew", "peak_risk")
    date_hierarchy = "date"
    inlines = [AssignmentInline, BreakInline]


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = ("due_at", "worker", "buddy", "status", "responded_at", "escalated_at")
    list_filter = ("status",)
    raw_id_fields = ("workday", "worker", "buddy")


@admin.register(HourlyForecast)
class HourlyForecastAdmin(admin.ModelAdmin):
    list_display = (
        "site",
        "start",
        "temperature_c",
        "relative_humidity",
        "heat_index_f",
        "wbgt_c",
        "risk",
        "source",
    )
    list_filter = ("site", "risk", "source")
    date_hierarchy = "start"
