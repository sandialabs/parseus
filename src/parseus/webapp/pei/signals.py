import os

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch.dispatcher import receiver

from .models import PeatConfig, PeatDevice, PeatPull, PeatScan
from .tasks import peat_results_cleanup


@receiver(post_save, sender=PeatConfig)
def update_config_file(sender, instance: PeatConfig, created, **kwargs):
    if created:
        instance._set_hosts()
    instance._update_config_file()


@receiver(post_delete, sender=PeatConfig)
def delete_file(sender, instance, using, **kwargs):
    if os.path.isfile(instance.filename.path):
        os.remove(instance.filename.path)


@receiver(post_save, sender=PeatDevice)
@receiver(post_delete, sender=PeatDevice)
def trigger_peat_config_save(sender, instance: PeatDevice, **kwargs):
    instance.config.save()


@receiver(pre_delete, sender=PeatPull)
@receiver(pre_delete, sender=PeatScan)
def pre_delete_peat_run(sender, instance, **kwargs):
    instance.stop()  # Stop celery task and running process.
    peat_results_folder = None
    if sender == PeatPull:
        parent_run_dir = settings.PEAT_PULL_DIR
    elif sender == PeatScan:
        parent_run_dir = settings.PEAT_SCAN_DIR
    if instance.run_dir:
        peat_results_folder = str(parent_run_dir / instance.run_dir)
    peat_results_cleanup(result_path=peat_results_folder)
