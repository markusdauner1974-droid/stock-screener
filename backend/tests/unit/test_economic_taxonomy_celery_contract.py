from app.celery_app import celery_app

TASK_PREFIX = "app.tasks.economic_taxonomy_tasks."


def test_economic_taxonomy_tasks_are_imported_and_routed_to_existing_queue():
    assert "app.tasks.economic_taxonomy_tasks" in celery_app.conf.include
    expected = {
        TASK_PREFIX + name
        for name in (
            "discover_economic_taxonomy_work",
            "process_economic_taxonomy_work",
            "deliver_taxonomy_outbox",
            "refresh_economic_taxonomy_generation",
            "apply_economic_theme_lifecycle",
            "calculate_economic_theme_metrics",
        )
    }
    assert expected <= set(celery_app.conf.task_routes)
    assert {celery_app.conf.task_routes[name]["queue"] for name in expected} == {
        "celery"
    }


def test_economic_taxonomy_beat_contract_uses_existing_worker_queue():
    schedule = celery_app.conf.beat_schedule
    expected = {
        "economic-taxonomy-discovery",
        "economic-taxonomy-processing",
        "economic-taxonomy-delivery",
        "economic-taxonomy-refresh",
        "economic-taxonomy-lifecycle",
        "economic-taxonomy-metrics",
    }
    assert expected <= set(schedule)
    assert {schedule[name]["options"]["queue"] for name in expected} == {"celery"}
    assert schedule["economic-taxonomy-discovery"]["schedule"].minute == {
        0,
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
    }
    assert schedule["economic-taxonomy-processing"]["schedule"].minute == set(
        range(60)
    )
    assert schedule["economic-taxonomy-delivery"]["schedule"].minute == set(range(60))
    assert schedule["economic-taxonomy-refresh"]["schedule"].minute == set(range(60))
    assert schedule["economic-taxonomy-lifecycle"]["schedule"].hour == {2}
    assert schedule["economic-taxonomy-lifecycle"]["schedule"].minute == {10}
