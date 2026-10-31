"""General routing."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="home"),
    path("modules", views.get_peat_modules, name="peat-modules"),
    path(
        "modules/<str:module_name>/defaults/",
        views.get_peat_module_defaults,
        name="peat-module-defaults",
    ),
    path("config/", views.PeatConfigListView.as_view(), name="peatconfig-list"),
    path(
        "config/upload/", views.PeatConfigCreateView.as_view(), name="peatconfig-form"
    ),
    path("config/create/", views.PeatBuilderView.as_view(), name="peatconfig-builder"),
    path(
        "config/details/<slug:pk>",
        views.PeatConfigDetailView.as_view(),
        name="peatconfig-details",
    ),
    path("config/scan", views.peatScanConfigView, name="peatscan-config"),
    path(
        "config/<int:pk>/edit/",
        views.PeatConfigUpdateView.as_view(),
        name="peatconfig-update",
    ),
    path(
        "device/<int:pk>/edit/",
        views.PeatDeviceUpdateView.as_view(),
        name="peatdevice-update",
    ),
    path("pull/", views.PeatPullView.as_view(), name="peat-pull"),
    path("scan/", views.PeatScanView.as_view(), name="peat-scan"),
    path("<str:method>/objects/", views.get_run_objects, name="peatrun-objs"),
    path(
        "scan/details/<slug:pk>",
        views.PeatScanDetailView.as_view(),
        name="peatScan-details",
    ),
    path(
        "pull/details/<slug:pk>",
        views.PeatPullDetailView.as_view(),
        name="peatPull-details",
    ),
    path("results/", views.PeatResultsView.as_view(), name="peatresults"),
    path("run/stop/", views.peat_run_stop, name="peatRun-stop"),
    path("run/download/", views.peat_run_download, name="peatRun-download"),
    path(
        "run/file/<str:method>/<slug:pk>/",
        views.peat_run_file,
        name="peatRun-file",
    ),
]
