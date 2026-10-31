"""Context processors available to all project HTML templates."""

from django.conf import settings

from .forms import DataStoreForm


def database_settings(request):
    """Get dict of context variables that should be included in every view"""
    initial = {
        "datastore_host": request.session.get(
            "datastore_host", settings.DEFAULT_DATASTORE
        ),
        "datastore_type": request.session.get("datastore_type", "elasticsearch"),
        "datastore_authenticate": request.session.get("datastore_authenticate", False),
        "datastore_username": request.session.get("datastore_username", ""),
    }
    return {"datastore_form": DataStoreForm(initial=initial)}
