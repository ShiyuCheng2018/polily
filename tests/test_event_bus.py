# tests/test_event_bus.py
"""v0.8.0 Task 10: EventBus publish/subscribe + topic constants."""
from polily.core.events import (
    TOPIC_LANGUAGE_CHANGED,
    TOPIC_MONITOR_UPDATED,
    TOPIC_POSITION_UPDATED,
    TOPIC_SCAN_UPDATED,
    TOPIC_WALLET_UPDATED,
    EventBus,
)


def test_subscribe_receives_published_payload():
    bus = EventBus()
    received = []

    def handler(payload):
        received.append(payload)

    bus.subscribe(TOPIC_SCAN_UPDATED, handler)
    bus.publish(TOPIC_SCAN_UPDATED, {"scan_id": "x1"})

    assert received == [{"scan_id": "x1"}]


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received = []
    def h(p): received.append(p)

    bus.subscribe(TOPIC_WALLET_UPDATED, h)
    bus.unsubscribe(TOPIC_WALLET_UPDATED, h)
    bus.publish(TOPIC_WALLET_UPDATED, {"balance": 100})
    assert received == []


def test_publish_with_no_subscribers_is_noop():
    bus = EventBus()
    bus.publish(TOPIC_MONITOR_UPDATED, {})  # must not raise


def test_handler_exception_does_not_break_other_handlers():
    bus = EventBus()
    calls = []
    def bad(p): raise RuntimeError("boom")
    def good(p): calls.append(p)

    bus.subscribe(TOPIC_POSITION_UPDATED, bad)
    bus.subscribe(TOPIC_POSITION_UPDATED, good)
    bus.publish(TOPIC_POSITION_UPDATED, {"x": 1})
    assert calls == [{"x": 1}]


def test_topics_are_strings():
    for t in (TOPIC_SCAN_UPDATED, TOPIC_WALLET_UPDATED,
              TOPIC_MONITOR_UPDATED, TOPIC_POSITION_UPDATED,
              TOPIC_LANGUAGE_CHANGED):
        assert isinstance(t, str) and len(t) > 0


def test_language_changed_payload_delivers_language_field():
    bus = EventBus()
    received = []
    bus.subscribe(TOPIC_LANGUAGE_CHANGED, received.append)
    bus.publish(TOPIC_LANGUAGE_CHANGED, {"language": "en"})
    assert received == [{"language": "en"}]
