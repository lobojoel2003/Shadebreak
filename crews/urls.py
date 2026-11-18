from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("days/<int:pk>/", views.workday_detail, name="workday"),
    path("days/<int:pk>/refresh/", views.workday_refresh, name="workday_refresh"),
    path("days/<int:pk>/add-worker/", views.workday_add_worker, name="workday_add_worker"),
    path("assignments/<int:pk>/", views.assignment_update, name="assignment_update"),
    path("checkins/<int:pk>/", views.checkin_update, name="checkin_update"),
    path("crew/", views.worker_list, name="worker_list"),
    path("crew/new/", views.worker_form, name="worker_create"),
    path("crew/<int:pk>/", views.worker_form, name="worker_edit"),
    path("crew/<int:pk>/deactivate/", views.worker_deactivate, name="worker_deactivate"),
    path("sites/", views.site_list, name="site_list"),
    path("sites/new/", views.site_form, name="site_create"),
    path("sites/<int:pk>/", views.site_form, name="site_edit"),
    path("sites/<int:pk>/archive/", views.site_deactivate, name="site_deactivate"),
    path("sites/<int:pk>/schedule/", views.site_schedule_day, name="site_schedule_day"),
    path("settings/", views.crew_settings, name="crew_settings"),
    path("switch-crew/", views.switch_crew, name="switch_crew"),
    path("plan/", views.plan_page, name="plan_page"),
    path("plan.pdf", views.heat_plan, name="heat_plan"),
    path("signup/", views.signup, name="signup"),
    path("welcome/", views.onboarding, name="onboarding"),
    path("healthz", views.healthz, name="healthz"),
    path("version", views.version, name="version"),
]
