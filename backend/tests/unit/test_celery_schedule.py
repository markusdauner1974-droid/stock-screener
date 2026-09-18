from app.celery_app import celery_app
from app.tasks.market_queues import SHARED_DATA_FETCH_QUEUE


def test_cot_schedule_runs_weekdays_at_1700_eastern():
    entry = celery_app.conf.beat_schedule["cot-refresh-weekday"]
    schedule = entry["schedule"]

    assert entry["task"] == "app.interfaces.tasks.cot_tasks.refresh_cot"
    assert entry["options"]["queue"] == SHARED_DATA_FETCH_QUEUE
    assert schedule._orig_hour == 17
    assert schedule._orig_minute == 0
    assert schedule._orig_day_of_week == "1-5"
    assert str(schedule.tz) == "America/New_York"
    assert celery_app.conf.task_routes[entry["task"]] == {
        "queue": SHARED_DATA_FETCH_QUEUE
    }
    assert "app.interfaces.tasks.cot_tasks" in celery_app.conf.include
