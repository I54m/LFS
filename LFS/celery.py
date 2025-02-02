from __future__ import absolute_import, unicode_literals
import os
# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'LFS.settings')
# os.environ["DJANGO_SETTINGS_MODULE"] = "LFS.settings"

from celery import Celery
from celery.schedules import crontab
from django.conf import settings

app = Celery('LFS')  

# Configure Celery using settings from Django settings.py.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load tasks from all registered Django app configs.
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

#TODO Test periodic tasks are actually running

@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    from filehost import tasks

    sender.add_periodic_task(
        crontab(minute=0, hour=0),
        tasks.expire_files(),
    )
    
    sender.add_periodic_task(
        crontab(minute=0, hour=0, day_of_week="Monday"),
        tasks.cleanup_orphaned_files_async(),
    )

    sender.add_periodic_task(
        crontab(minute=0),
        tasks.maintain_oembed_cache,
    )    
