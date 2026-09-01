"""Pure logic of the system-audio router (hardware calls stay untested)."""

from packages.audio.routing import AGGREGATE_UID, pick_real_device

DEVICES = [
    {"id": 1, "uid": "buds-uid", "name": "OnePlus Nord Buds"},
    {"id": 2, "uid": "BlackHole2ch_UID", "name": "BlackHole 2ch"},
    {"id": 3, "uid": AGGREGATE_UID, "name": "Confab + OnePlus Nord Buds"},
    {"id": 4, "uid": "speakers-uid", "name": "MacBook Pro Speakers"},
]


def test_current_output_is_the_device_to_pair():
    assert pick_real_device("buds-uid", DEVICES)["name"] == "OnePlus Nord Buds"
    assert pick_real_device("speakers-uid", DEVICES)["name"] == "MacBook Pro Speakers"


def test_blackhole_as_output_has_no_real_device():
    # User picked BlackHole directly — pairing it with itself would be silence.
    assert pick_real_device("BlackHole2ch_UID", DEVICES) is None


def test_our_own_aggregate_is_not_a_real_device():
    # Stale state: default is already Confab's aggregate but it needs a rebuild;
    # the caller resolves the true device from the sub-list, not from here.
    assert pick_real_device(AGGREGATE_UID, DEVICES) is None


def test_unknown_or_missing_default_matches_nothing():
    assert pick_real_device("gone-uid", DEVICES) is None
    assert pick_real_device(None, DEVICES) is None
