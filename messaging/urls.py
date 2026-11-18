from django.urls import path

from . import views

urlpatterns = [
    path("sms/twilio/", views.twilio_inbound, name="sms_twilio"),
    path("sms/gateway/", views.gateway_inbound, name="sms_gateway"),
    path("messages/", views.message_log, name="message_log"),
]
