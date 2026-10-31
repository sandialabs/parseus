"""Models that you can view and modify on the admin page."""

from django.contrib import admin

from .models import *

# Register your models here.
admin.site.register(PeatDevice)
admin.site.register(PeatConfig)
admin.site.register(PeatPull)
admin.site.register(PeatScan)
