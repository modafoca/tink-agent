import numpy as np
from tink_agent.config import Config
from tink_agent.detector import ToneDetector, VoiceGate
from tink_agent.actions import ActionRouter
from tink_agent.engine import Engine


class FakeKeyboard:
    class Key:
        enter = "ENTER"; esc = "ESC"; ctrl = "CTRL"
        tab = "TAB"; shift = "SHIFT"; up = "UP"; down = "DOWN"
        f13 = "F13"
    def __init__(self): self.events = []
    def press(self, k): self.events.append(("press", k))
    def release(self, k): self.events.append(("release", k))
    def type(self, s): self.events.append(("type", s))
    class _P:
        def __init__(s, kb, k): s.kb, s.k = kb, k
        def __enter__(s): return s
        def __exit__(s, *a): pass
    def pressed(self, k): return FakeKeyboard._P(self, k)


class FakeTranscriber:
    last_error = None
    def transcribe(self, samples, sr): return "approve this"


class FakeLogger:
    def __init__(self):
        self.calls = []
    def transcript(self, text, app=None): self.calls.append(("voice", text, app))
    def action(self, slot, action, app=None): self.calls.append(("action", slot, action, app))
    def blocked(self, what, app=None): self.calls.append(("blocked", what, app))


def _engine(kb, events, target_app="", frontmost="Terminal com.apple.Terminal",
            logger=None, **cfg):
    c = Config(target_apps=[target_app] if target_app else [], **cfg)
    det = ToneDetector(c.tones, c.tone_rms_min, c.tone_dominance_min,
                       c.tone_debounce_ms, c.sample_rate)
    vg = VoiceGate(c.vad_rms_start, c.vad_rms_end, c.vad_hangover_ms,
                   c.min_utterance_ms, c.sample_rate, c.block_size)
    router = ActionRouter(c.slot_actions, keyboard=kb)
    return Engine(c, det, vg, FakeTranscriber(), router,
                  on_event=lambda k, p: events.append((k, p)),
                  submit_fn=lambda fn: fn(),  # synchronous
                  frontmost_fn=lambda: frontmost, logger=logger)


def _tone_block(freq=1500):
    sr, block = 16000, 800
    t = np.arange(0, block / sr, 1 / sr)[:block]
    return (np.sin(2 * np.pi * freq * t) * 12000).astype(np.int16)


def test_tone_block_fires_keystroke_and_event():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    sr, block = 16000, 800
    t = np.arange(0, block / sr, 1 / sr)[:block]
    tone = (np.sin(2 * np.pi * 1500 * t) * 12000).astype(np.int16)
    eng.handle_block(tone)
    assert ("press", "ENTER") in kb.events
    assert ("tone", 1) in events


def test_speech_then_silence_types_transcript():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    rng = np.random.default_rng(0)
    for _ in range(10):
        eng.handle_block((rng.standard_normal(800) * 3000).astype(np.int16))
    for _ in range(20):
        eng.handle_block((rng.standard_normal(800) * 20).astype(np.int16))
    assert ("type", "approve this") in kb.events
    assert any(k == "transcript" for k, _ in events)


def test_disabled_engine_does_nothing():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    eng.enabled = False
    eng.handle_block(_tone_block())
    assert kb.events == []


def test_target_app_gate_allows_matching_frontmost():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, target_app="Terminal", frontmost="Terminal com.apple.Terminal")
    eng.handle_block(_tone_block())
    assert ("press", "ENTER") in kb.events
    assert ("tone", 1) in events


def test_target_app_gate_blocks_nonmatching_frontmost():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, target_app="Terminal", frontmost="Safari com.apple.Safari")
    eng.handle_block(_tone_block())
    assert kb.events == []  # no keystroke into the wrong app
    assert any(k == "blocked" for k, _ in events)


def test_target_apps_matches_any_in_list():
    from tink_agent.config import Config as Cfg
    kb, events = FakeKeyboard(), []
    c = Cfg(target_apps=["com.apple.Terminal", "com.googlecode.iterm2"])
    det = ToneDetector(c.tones, c.tone_rms_min, c.tone_dominance_min,
                       c.tone_debounce_ms, c.sample_rate)
    vg = VoiceGate(c.vad_rms_start, c.vad_rms_end, c.vad_hangover_ms,
                   c.min_utterance_ms, c.sample_rate, c.block_size)
    eng = Engine(c, det, vg, FakeTranscriber(), ActionRouter(c.slot_actions, keyboard=kb),
                 on_event=lambda k, p: events.append((k, p)), submit_fn=lambda fn: fn(),
                 frontmost_fn=lambda: "iTerm com.googlecode.iterm2")
    eng.handle_block(_tone_block())
    assert ("press", "ENTER") in kb.events  # iTerm is in the allowed list


def test_target_app_gate_blocks_transcript_typing():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, target_app="Terminal", frontmost="Notes com.apple.Notes")
    rng = np.random.default_rng(0)
    for _ in range(10):
        eng.handle_block((rng.standard_normal(800) * 3000).astype(np.int16))
    for _ in range(20):
        eng.handle_block((rng.standard_normal(800) * 20).astype(np.int16))
    assert not any(e[0] == "type" for e in kb.events)
    assert any(k == "blocked" for k, _ in events)


def test_is_capturing_reflects_voicegate_state():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    assert eng.is_capturing is False
    rng = np.random.default_rng(0)
    eng.handle_block((rng.standard_normal(800) * 3000).astype(np.int16))
    assert eng.is_capturing is True  # utterance open
    for _ in range(20):
        eng.handle_block((rng.standard_normal(800) * 20).astype(np.int16))
    assert eng.is_capturing is False  # closed after silence


def test_logs_action_with_frontmost_app():
    kb, events, lg = FakeKeyboard(), [], FakeLogger()
    eng = _engine(kb, events, frontmost="Terminal com.apple.Terminal", logger=lg)
    eng.handle_block(_tone_block())  # slot 1 -> enter
    assert ("action", 1, "enter", "Terminal com.apple.Terminal") in lg.calls


def test_logs_transcript_with_frontmost_app():
    kb, events, lg = FakeKeyboard(), [], FakeLogger()
    eng = _engine(kb, events, frontmost="Notes com.apple.Notes", logger=lg)
    rng = np.random.default_rng(0)
    for _ in range(10):
        eng.handle_block((rng.standard_normal(800) * 3000).astype(np.int16))
    for _ in range(20):
        eng.handle_block((rng.standard_normal(800) * 20).astype(np.int16))
    assert ("voice", "approve this", "Notes com.apple.Notes") in lg.calls


def test_logs_blocked_when_wrong_app():
    kb, events, lg = FakeKeyboard(), [], FakeLogger()
    eng = _engine(kb, events, target_app="Terminal",
                  frontmost="Safari com.apple.Safari", logger=lg)
    eng.handle_block(_tone_block())
    assert any(c[0] == "blocked" for c in lg.calls)


def test_slot4_shift_tab():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    eng.handle_block(_tone_block(3900))  # slot 4 = shift_tab
    assert ("press", "SHIFT") not in kb.events  # shift is held via context mgr
    assert ("press", "TAB") in kb.events
    assert ("tone", 4) in events


def _noise_block(rms):
    rng = np.random.default_rng(0)
    x = rng.standard_normal(800)
    return (x / np.sqrt(np.mean(x * x)) * rms).astype(np.int16)


def _keys(kb):
    return [e for e in kb.events if e[1] == "F13"]


def test_handle_key_held_on_sound_and_released_after_silence():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, handle_key="f13", handle_on_blocks=2, handle_off_blocks=4)
    hiss = _noise_block(50)            # squeeze noise floor: above handle_rms_on, below any tone/VAD floor
    eng.handle_block(hiss)
    assert _keys(kb) == []
    eng.handle_block(hiss)
    assert _keys(kb) == [("press", "F13")]
    for _ in range(3):
        eng.handle_block(np.zeros(800, dtype=np.int16))
    assert _keys(kb) == [("press", "F13")]          # not yet: 3 < handle_off_blocks
    eng.handle_block(np.zeros(800, dtype=np.int16))
    assert _keys(kb) == [("press", "F13"), ("release", "F13")]
    assert ("handle", "held") in events and ("handle", "released") in events


def test_handle_key_not_touched_when_disabled():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)            # handle_key defaults to ""
    for _ in range(5):
        eng.handle_block(_noise_block(50))
    assert _keys(kb) == []


def test_button_tone_releases_handle_key_and_guards_rehold():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, handle_key="f13", handle_on_blocks=2, handle_off_blocks=50)
    for _ in range(3):
        eng.handle_block(_noise_block(50))
    assert _keys(kb) == [("press", "F13")]
    eng.handle_block(_tone_block(1500))   # slot 1 fires
    assert _keys(kb) == [("press", "F13"), ("release", "F13")]
    assert ("action", "enter") in events
    # The tone's tail / decay must not re-hold the key during the guard.
    for _ in range(10):
        eng.handle_block(_noise_block(50))
    assert _keys(kb) == [("press", "F13"), ("release", "F13")]


def test_utterance_containing_a_button_tone_is_dropped():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    for _ in range(10):                   # speech-level noise opens the voice gate
        eng.handle_block(_noise_block(1500))
    eng.handle_block(_tone_block(1500))   # beep inside the utterance
    for _ in range(40):                   # silence closes the gate
        eng.handle_block(np.zeros(800, dtype=np.int16))
    assert ("dropped", "tone in utterance") in events
    assert not any(e[0] == "type" for e in kb.events)
    assert not any(k == "transcript" for k, _ in events)


def test_plain_utterance_is_still_transcribed():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    for _ in range(10):
        eng.handle_block(_noise_block(1500))
    for _ in range(40):
        eng.handle_block(np.zeros(800, dtype=np.int16))
    assert ("transcript", "approve this") in events


def test_noise_burst_fires_action_releases_handle_and_is_not_transcribed():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, handle_key="f13", handle_on_blocks=2, handle_off_blocks=50,
                  noise_action="tab", noise_blocks=4)
    for i in range(8):                     # applause: loud, unvoiced
        eng.handle_block(_noise_block(1500))
    assert ("action", "tab") in events
    assert ("press", "TAB") in kb.events
    assert _keys(kb) == [("press", "F13"), ("release", "F13")]   # woke, then released by the burst
    for _ in range(40):
        eng.handle_block(np.zeros(800, dtype=np.int16))
    assert not any(k == "transcript" for k, _ in events)
    assert _keys(kb) == [("press", "F13"), ("release", "F13")]   # burst tail did not re-hold


def test_noise_burst_disabled_by_default():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events)
    for _ in range(20):
        eng.handle_block(_noise_block(1500))
    assert not any(k in ("noise",) for k, _ in events)


def test_noise_burst_right_after_a_tone_is_the_same_press():
    kb, events = FakeKeyboard(), []
    eng = _engine(kb, events, noise_action="tab", noise_blocks=4)
    eng.handle_block(_tone_block(1500))     # e.g. the bell hit at the start of the applause
    for _ in range(12):
        eng.handle_block(_noise_block(1500))
    assert [p for k, p in events if k == "action"] == ["enter"]   # one fire, not two
