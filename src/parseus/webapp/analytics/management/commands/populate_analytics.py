from django.core import management
from django.core.management.base import BaseCommand

from parseus.webapp.analytics.utility_analytics import upload_analytic_config


class Command(BaseCommand):
    help = "Setup the database and prepopulate the analytic records"

    def handle(self, *args, **options):
        # migrate
        try:
            management.call_command("migrate")
            self.stdout.write(self.style.SUCCESS("Finished migrate"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"migrate error: {e}"))
            return

        # Analytics are sourced from the descriptor registry.
        try:
            upload_analytic_config()
            self.stdout.write(self.style.SUCCESS("Finished populating analytics"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"populate analytics error: {e}"))
            return
