from django.urls import path

from .views import editor_api
from .views.briefs import BriefListView, BriefWizardView
from .views.dashboard import DashboardView
from .views.metadata import MetadataView
from .views.provider_keys import (
    AddedModelView,
    AddedProviderView,
    DeleteModelView,
    DeleteProviderView,
    ProviderKeysView,
    ProviderKeyView,
    RemoveKeyView,
)
from .views.providers import ProvidersView
from .views.runs import RunListView, RunWorkspaceView, VersionCompareView, run_export, run_status
from .views.task_defaults import TaskDefaultsView

app_name = "studio"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("briefs/", BriefListView.as_view(), name="briefs"),
    path("briefs/new/", BriefWizardView.as_view(), name="brief_new"),
    path("briefs/<int:pk>/edit/", BriefWizardView.as_view(), name="brief_edit"),
    path("runs/", RunListView.as_view(), name="runs"),
    path("runs/<int:pk>/", RunWorkspaceView.as_view(), name="run"),
    path("runs/<int:pk>/metadata/", MetadataView.as_view(), name="metadata"),
    path("runs/<int:pk>/status/", run_status, name="run_status"),
    path("runs/<int:pk>/export/<slug:fmt>/", run_export, name="run_export"),
    path(
        "runs/<int:pk>/steps/<slug:step>/compare/<int:a>/<int:b>/",
        VersionCompareView.as_view(),
        name="compare",
    ),
    path("models/", ProvidersView.as_view(), name="providers"),
    # JSON for the step-output editor (M9 phase 5)
    path("editor/images/", editor_api.upload_image, name="editor_upload_image"),
    path("editor/refs/", editor_api.references, name="editor_refs"),
    path("editor/embed/", editor_api.embed_preview, name="editor_embed"),
    # Settings › AI providers (superusers): keys, added providers and models (ADR 0008)
    path("ai-providers/", ProviderKeysView.as_view(), name="provider_keys"),
    path("ai-defaults/", TaskDefaultsView.as_view(), name="task_defaults"),
    path("ai-providers/add/", AddedProviderView.as_view(), name="provider_add"),
    path("ai-providers/models/add/", AddedModelView.as_view(), name="provider_model_add"),
    path("ai-providers/models/<int:pk>/remove/", DeleteModelView.as_view(), name="provider_model_remove"),
    path("ai-providers/<slug:name>/key/", ProviderKeyView.as_view(), name="provider_key"),
    path("ai-providers/<slug:name>/key/remove/", RemoveKeyView.as_view(), name="provider_key_remove"),
    path("ai-providers/<slug:name>/edit/", AddedProviderView.as_view(), name="provider_edit"),
    path("ai-providers/<slug:name>/delete/", DeleteProviderView.as_view(), name="provider_delete"),
]
