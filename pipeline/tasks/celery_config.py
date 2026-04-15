"""
Celery configuration.
Imported by celery_app.py via config_from_object.
"""
from celery.schedules import crontab

# Serialization
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "Asia/Riyadh"
enable_utc = True

# Don't store results indefinitely — keep for 24 hours
result_expires = 86400

# Retry on connection loss
broker_connection_retry_on_startup = True

# Beat schedule — periodic tasks
beat_schedule = {
    # MOH publishes a new Statistical Yearbook once a year (~Q1).
    # Check every Monday at 06:00 Riyadh time so we pick it up quickly.
    "scrape-moh-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=6, minute=0, day_of_week="monday"),
        "args": ["MOH"],
        "options": {"queue": "pipeline"},
    },
    # GASTAT releases health stats bulletins more frequently.
    # Check every day at 07:00 Riyadh time.
    "scrape-gastat-daily": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=7, minute=0),
        "args": ["GASTAT"],
        "options": {"queue": "pipeline"},
    },
    # NHIC — quality indicators, hospital performance reports. Weekly on Sunday.
    "scrape-nhic-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=7, minute=0, day_of_week="sunday"),
        "args": ["NHIC"],
        "options": {"queue": "pipeline"},
    },
    # SHC — health policy reports, PHC data. Weekly on Sunday.
    "scrape-shc-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=8, minute=0, day_of_week="sunday"),
        "args": ["SHC"],
        "options": {"queue": "pipeline"},
    },
    # SFDA — pharma/drug statistics, food safety reports. Weekly on Sunday.
    "scrape-sfda-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=9, minute=0, day_of_week="sunday"),
        "args": ["SFDA"],
        "options": {"queue": "pipeline"},
    },
    # SCHS — detailed health statistics bulletins. Weekly on Sunday.
    "scrape-schs-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=10, minute=0, day_of_week="sunday"),
        "args": ["SCHS"],
        "options": {"queue": "pipeline"},
    },
    # CCHI/CHI — Council of Health Insurance annual reports + research papers. Weekly on Sunday.
    "scrape-cchi-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=11, minute=0, day_of_week="sunday"),
        "args": ["CCHI"],
        "options": {"queue": "pipeline"},
    },
    # WEQAYA — Saudi CDC disease surveillance and health status reports. Weekly on Sunday.
    "scrape-weqaya-weekly": {
        "task": "pipeline.tasks.pipeline_tasks.scrape_and_index",
        "schedule": crontab(hour=12, minute=0, day_of_week="sunday"),
        "args": ["WEQAYA"],
        "options": {"queue": "pipeline"},
    },
}

# Route all pipeline tasks to a dedicated queue so they don't
# block other potential tasks in the future.
task_routes = {
    "pipeline.tasks.pipeline_tasks.*": {"queue": "pipeline"},
}
