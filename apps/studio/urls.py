from django.urls import path

from .views import StudioOverviewView

app_name = "studio"

urlpatterns = [
    path("", StudioOverviewView.as_view(), name="overview"),
]
