from __future__ import annotations
import sys
import numpy as np
import time


class DeviceNotFound(Exception):
    pass


def _default_on_status(status: str) -> None:
    # Goes to stderr -> the LaunchAgent run log (~/Library/Logs/TinkAgent.log),
    # so input overflow / device drops that truncate audio become visible.
    print(f"[audio] stream status: {status}", file=sys.stderr, flush=True)


def resolve_device(name: str, query_fn=None) -> int:
    if query_fn is None:
        import sounddevice as sd
        query_fn = sd.query_devices
    devices = query_fn()
    for idx, dev in enumerate(devices):
        if name.lower() in dev["name"].lower() and dev.get("max_input_channels", 0) > 0:
            return idx
    raise DeviceNotFound(f"No input device matching {name!r}")


def reinitialize() -> None:
    """Force PortAudio to re-enumerate devices.

    PortAudio caches the device list at initialization, so a hot-plugged or
    unplugged device is not reflected by query_devices() until it is
    re-initialized. The caller MUST stop any open stream first — terminating
    PortAudio under a live stream is undefined."""
    import sounddevice as sd
    sd._terminate()
    sd._initialize()


NOT_CONNECTED_SUFFIX = " (not connected)"


def input_device_names(query_fn=None) -> list[str]:
    """Names of available input devices, deduped (order-preserving) and sorted
    case-insensitively. query_fn injectable for tests."""
    if query_fn is None:
        import sounddevice as sd
        query_fn = sd.query_devices
    seen = []
    for dev in query_fn():
        name = dev["name"]
        if dev.get("max_input_channels", 0) > 0 and name not in seen:
            seen.append(name)
    return sorted(seen, key=str.lower)


def device_menu_items(saved_name: str, connected_names: list[str]) -> tuple[list[str], int]:
    """(dropdown titles, index to select) for the audio-source popup. A saved
    device that isn't currently connected is appended as a '(not connected)'
    placeholder and selected, so the choice survives unplug/replug.
    Presence is decided by the same case-insensitive substring rule
    resolve_device uses, so the UI status matches what capture will actually
    resolve."""
    items = list(connected_names)
    if saved_name:
        for i, name in enumerate(items):
            if saved_name.lower() in name.lower():
                return items, i
        items.append(f"{saved_name}{NOT_CONNECTED_SUFFIX}")
        return items, len(items) - 1
    return items, -1


def device_name_from_title(title: str) -> str | None:
    """Real device name for a chosen popup title, or None if it's the
    '(not connected)' placeholder (meaning: no change)."""
    if title.endswith(NOT_CONNECTED_SUFFIX):
        return None
    return title


class AudioCapture:
    def __init__(self, device_name, sample_rate, block_size, on_block,
                 stream_factory=None, resolve_fn=None, on_status=None):
        self.device_name = device_name
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.on_block = on_block
        self._resolve = resolve_fn or resolve_device
        self._stream_factory = stream_factory
        self._on_status = on_status or _default_on_status
        self._stream = None
        self.last_block_at = None   # time.monotonic() of the last delivered block

    def _make_stream(self, device_index):
        if self._stream_factory is not None:
            factory = self._stream_factory
        else:
            import sounddevice as sd
            factory = sd.InputStream
        return factory(device=device_index, channels=1, samplerate=self.sample_rate,
                       blocksize=self.block_size, dtype="int16", callback=self._callback)

    def _callback(self, indata, frames, time_info, status):
        if status:
            # input overflow / device error — report but still forward the block
            try:
                self._on_status(str(status))
            except Exception:  # noqa: BLE001 — logging must never break capture
                pass
        self.last_block_at = time.monotonic()
        self.on_block(np.asarray(indata, dtype=np.int16).reshape(-1))

    def start(self):
        idx = self._resolve(self.device_name)
        self._stream = self._make_stream(idx)
        self._stream.start()
        self.last_block_at = time.monotonic()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def stalled(self, max_silence_s: float = 3.0, now=None) -> bool:
        """True when the stream is open but no block has arrived for a while:
        CoreAudio stops calling back when the input device is unplugged."""
        if self._stream is None or self.last_block_at is None:
            return False
        now = time.monotonic() if now is None else now
        return (now - self.last_block_at) > max_silence_s


def device_present(name: str, query_fn=None) -> bool:
    """Whether an input device matching `name` is currently connected."""
    try:
        resolve_device(name, query_fn)
        return True
    except DeviceNotFound:
        return False
