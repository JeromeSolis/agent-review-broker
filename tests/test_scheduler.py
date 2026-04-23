from datetime import UTC, datetime, timedelta

from broker.models import PaperPhase
from broker.scheduler.state_machine import current_phase, time_into_lifecycle


def test_phase_discussion_at_zero():
    now = datetime.now(UTC)
    assert current_phase(now, now=now) == PaperPhase.DISCUSSION


def test_phase_discussion_at_47h():
    released = datetime.now(UTC) - timedelta(hours=47)
    assert current_phase(released) == PaperPhase.DISCUSSION


def test_phase_verdict_at_49h():
    released = datetime.now(UTC) - timedelta(hours=49)
    assert current_phase(released) == PaperPhase.VERDICT


def test_phase_published_past_72h():
    released = datetime.now(UTC) - timedelta(hours=73)
    assert current_phase(released) == PaperPhase.PUBLISHED


def test_time_into_lifecycle_handles_naive_datetime():
    released = (datetime.now(UTC) - timedelta(hours=10)).replace(tzinfo=None)
    elapsed = time_into_lifecycle(released)
    # Just confirm it doesn't raise and returns a sensible value.
    assert elapsed.total_seconds() > 9 * 3600
