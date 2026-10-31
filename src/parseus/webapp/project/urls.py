"""URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from parseus.webapp.registry import iter_installed_app_descriptors

from . import views

urlpatterns = [
    # Home page
    path("", views.home, name="home"),
    # Administration pages
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("login/modal/", views.CustomLoginView.as_view(), name="login_modal"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Database pages
    path("database/", views.DataStoreView.as_view(), name="database"),
    path("database/status/", views.get_database_status, name="database_status"),
]

# Mount each installed Parseus feature app from the pluggable-app registry so
# routing stays in lockstep with INSTALLED_APPS. Apps that are not installed are
# simply skipped instead of raising at import time.
for descriptor in iter_installed_app_descriptors():
    urlpatterns.append(
        path(
            descriptor.url_prefix,
            include(
                (descriptor.urlconf, descriptor.namespace),
                namespace=descriptor.namespace,
            ),
        )
    )

# Serve static and media files during development.
# During production, the web server would take care of it.
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
