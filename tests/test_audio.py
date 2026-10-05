import numpy as np
import pytest
from tink_agent.audio import (
    resolve_device, DeviceNotFound, AudioCapture,
    input_device_names, device_menu_items, device_name_from_title,
    NOT_CONNECTED_SUFFIX,
)


def _devices():
    return [
        {"name": "MacBook Air Microphone", "max_input_channels": 1},
        {"name": "USB Audio Device", "max_input_channels": 1},
        {"name": "Some Speakers", "max_input_channels": 0},
    ]


def test_resolve_finds_by_name_substring():
    assert resolve_device("USB Audio Device", query_fn=_devices) == 1


def test_resolve_ignores_output_only_devices():
    devs = [{"name": "USB Audio Device", "max_input_channels": 0}]
    with pytest.raises(DeviceNotFound):
        resolve_device("USB Audio Device", query_fn=lambda: devs)


def test_resolve_missing_raises():
    with pytest.raises(DeviceNotFound):
        resolve_device("Nonexistent", query_fn=_devices)


def test_capture_forwards_blocks_as_int16_1d():
    received = []

    class FakeStream:
        def __init__(self, **kw): self.kw = kw
        def start(self): self.kw["callback"](
            np.zeros((self.kw["blocksize"], 1), dtype=np.int16), self.kw["blocksize"], None, None)
        def stop(self): pass
        def close(self): pass

    cap = AudioCapture("USB Audio Device", 16000, 800, on_block=received.append,
                       stream_factory=lambda **kw: FakeStream(**kw),
                       resolve_fn=lambda name: 1)
    cap.start()
    assert received and received[0].ndim == 1 and received[0].dtype == np.int16
    cap.stop()


def test_capture_reports_portaudio_status_and_still_forwards_block():
    # PortAudio signals input overflow / device errors via `status`. Silently
    # dropping it hid device drops that truncate audio; surface it but keep
    # forwarding the (possibly partial) block.
    received, statuses = [], []

    class FakeStream:
        def __init__(self, **kw): self.kw = kw
        def start(self):
            self.kw["callback"](
                np.zeros((self.kw["blocksize"], 1), dtype=np.int16),
                self.kw["blocksize"], None, "input overflow")
        def stop(self): pass
        def close(self): pass

    cap = AudioCapture("USB Audio Device", 16000, 800, on_block=received.append,
                       stream_factory=lambda **kw: FakeStream(**kw),
                       resolve_fn=lambda name: 1, on_status=statuses.append)
    cap.start()
    assert statuses == ["input overflow"]   # surfaced
    assert len(received) == 1                # block still delivered
    cap.stop()


def test_input_device_names_filters_dedupes_and_sorts():
    devs = [
        {"name": "USB Audio Device", "max_input_channels": 1},
        {"name": "Some Speakers", "max_input_channels": 0},
        {"name": "MacBook Air Microphone", "max_input_channels": 1},
        {"name": "USB Audio Device", "max_input_channels": 2},  # duplicate name
    ]
    assert input_device_names(query_fn=lambda: devs) == [
        "MacBook Air Microphone",
        "USB Audio Device",
    ]


def test_input_device_names_empty_when_no_inputs():
    devs = [{"name": "Speakers", "max_input_channels": 0}]
    assert input_device_names(query_fn=lambda: devs) == []


def test_device_menu_items_selects_connected():
    items, idx = device_menu_items("USB Audio Device",
                                   ["MacBook Air Microphone", "USB Audio Device"])
    assert items == ["MacBook Air Microphone", "USB Audio Device"]
    assert idx == 1


def test_device_menu_items_appends_not_connected_placeholder():
    items, idx = device_menu_items("USB Audio Device", ["MacBook Air Microphone"])
    assert items == ["MacBook Air Microphone",
                     "USB Audio Device" + NOT_CONNECTED_SUFFIX]
    assert idx == 1


def test_device_menu_items_no_saved_name():
    items, idx = device_menu_items("", ["MacBook Air Microphone"])
    assert items == ["MacBook Air Microphone"]
    assert idx == -1


def test_device_menu_items_substring_match_is_connected():
    # saved name is a substring of a connected device -> selected, not "(not connected)"
    items, idx = device_menu_items("USB Audio Device", ["USB Audio Device Pro"])
    assert items == ["USB Audio Device Pro"]
    assert idx == 0


def test_device_name_from_title_round_trip_and_placeholder():
    assert device_name_from_title("USB Audio Device") == "USB Audio Device"
    assert device_name_from_title("USB Audio Device" + NOT_CONNECTED_SUFFIX) is None


def test_capture_stalled_when_blocks_stop_arriving():
    from tink_agent.audio import AudioCapture
    class FakeStream:
        def __init__(self, **kw): self.cb = kw["callback"]
        def start(self): pass
        def stop(self): pass
        def close(self): pass
    cap = AudioCapture("dev", 16000, 800, on_block=lambda b: None,
                       stream_factory=FakeStream, resolve_fn=lambda n: 0)
    assert not cap.stalled()                 # not started: nothing to watch
    cap.start()
    assert not cap.stalled(3.0, now=cap.last_block_at + 1.0)
    assert cap.stalled(3.0, now=cap.last_block_at + 3.5)
    cap._callback(np.zeros((800, 1), dtype=np.int16), 800, None, None)
    assert not cap.stalled(3.0, now=cap.last_block_at + 1.0)


def test_device_present_by_name():
    from tink_agent.audio import device_present
    devs = [{"name": "CUBILUX HLMS-C4 Line IN", "max_input_channels": 2},
            {"name": "Speakers", "max_input_channels": 0}]
    assert device_present("CUBILUX HLMS-C4 Line IN", query_fn=lambda: devs)
    assert not device_present("USB Audio Device", query_fn=lambda: devs)
