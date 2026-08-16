import pytest
from django.core.management import call_command
from django_q.models import Schedule


@pytest.mark.django_db
def test_schedule_convert_prices_creates_one_daily_recovery_schedule():
    Schedule.objects.create(
        func="games.tasks.convert_prices",
        name="Update converted prices",
        schedule_type=Schedule.MINUTES,
    )

    call_command("schedule_convert_prices")
    call_command("schedule_convert_prices")

    schedules = Schedule.objects.filter(name="Recover library price conversions")
    assert schedules.count() == 1
    task = schedules.get()
    assert task.func == "games.tasks.recover_library_price_conversions"
    assert task.schedule_type == Schedule.DAILY
    assert not Schedule.objects.filter(
        func="games.tasks.convert_prices",
    ).exists()
