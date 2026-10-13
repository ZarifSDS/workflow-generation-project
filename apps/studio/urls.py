from django.urls import path

from .views.briefs import BriefListView, BriefWizardView
from .views.dashboard import DashboardView
from .views.metadata import MetadataView
from .views.providers import ProvidersView
from .views.runs import RunListView, RunWorkspaceView, VersionCompareView

app_name = "studio"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("briefs/", BriefListView.as_view(), name="briefs"),
    path("briefs/new/", BriefWizardView.as_view(), name="brief_new"),
    path("briefs/<int:pk>/edit/", BriefWizardView.as_view(), name="brief_edit"),
    path("runs/", RunListView.as_view(), name="runs"),
    path("runs/<int:pk>/", RunWorkspaceView.as_view(), name="run"),
    path("runs/<int:pk>/metadata/", MetadataView.as_view(), name="metadata"),
    path(
        "runs/<int:pk>/steps/<slug:step>/compare/<int:a>/<int:b>/",
        VersionCompareView.as_view(),
        name="compare",
    ),
    path("models/", ProvidersView.as_view(), name="providers"),
]
