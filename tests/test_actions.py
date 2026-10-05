from tink_agent.actions import ActionRouter


class FakeKey:
    enter = "ENTER"
    esc = "ESC"
    ctrl = "CTRL"
    shift = "SHIFT"
    cmd = "CMD"
    tab = "TAB"
    up = "UP"
    down = "DOWN"
    left = "LEFT"
    right = "RIGHT"
    space = "SPACE"
    backspace = "BACKSPACE"
    f13 = "F13"


class FakeKeyboard:
    Key = FakeKey

    def __init__(self):
        self.events = []

    def press(self, k): self.events.append(("press", k))
    def release(self, k): self.events.append(("release", k))
    def type(self, s): self.events.append(("type", s))

    class _Pressed:
        def __init__(self, kb, k): self.kb, self.k = kb, k
        def __enter__(self): self.kb.events.append(("hold", self.k)); return self
        def __exit__(self, *a): self.kb.events.append(("unhold", self.k))

    def pressed(self, k): return FakeKeyboard._Pressed(self, k)


def _router(kb):
    return ActionRouter({1: "enter", 2: "escape", 3: "ctrl_c", 4: "noop"}, keyboard=kb)


def test_enter_action():
    kb = FakeKeyboard()
    assert _router(kb).fire_slot(1) == "enter"
    assert ("press", "ENTER") in kb.events


def test_ctrl_c_action_holds_ctrl():
    kb = FakeKeyboard()
    assert _router(kb).fire_slot(3) == "ctrl_c"
    assert ("hold", "CTRL") in kb.events
    assert ("press", "c") in kb.events


def test_noop_and_unmapped():
    kb = FakeKeyboard()
    r = _router(kb)
    assert r.fire_slot(4) == "noop"
    assert r.fire_slot(9) == "unmapped"
    assert kb.events == []


def test_type_text():
    kb = FakeKeyboard()
    _router(kb).type_text("hello")
    assert ("type", "hello") in kb.events


def test_up_action():
    kb = FakeKeyboard()
    r = ActionRouter({5: "up", 6: "down"}, keyboard=kb)
    assert r.fire_slot(5) == "up"
    assert ("press", "UP") in kb.events and ("release", "UP") in kb.events


def test_down_action():
    kb = FakeKeyboard()
    r = ActionRouter({5: "up", 6: "down"}, keyboard=kb)
    assert r.fire_slot(6) == "down"
    assert ("press", "DOWN") in kb.events and ("release", "DOWN") in kb.events


def test_reserved_slots_are_noop():
    kb = FakeKeyboard()
    r = ActionRouter({7: "noop", 8: "noop"}, keyboard=kb)
    assert r.fire_slot(7) == "noop" and r.fire_slot(8) == "noop"
    assert kb.events == []


# --- main-thread dispatch (crash fix: pynput must not touch HIToolbox TSM off
# the main thread; keyboard ops are deferred to an injected dispatcher) ---

def test_fire_slot_defers_keystroke_to_dispatch():
    kb = FakeKeyboard()
    deferred = []
    r = ActionRouter({1: "enter"}, keyboard=kb, dispatch=deferred.append)
    # Returns the action id immediately (used for events/logging)...
    assert r.fire_slot(1) == "enter"
    # ...but the keystroke is NOT executed on the calling thread.
    assert kb.events == []
    assert len(deferred) == 1
    deferred[0]()  # simulate the main thread running it
    assert ("press", "ENTER") in kb.events


def test_type_text_defers_to_dispatch():
    kb = FakeKeyboard()
    deferred = []
    r = ActionRouter({}, keyboard=kb, dispatch=deferred.append)
    r.type_text("hi")
    assert kb.events == []           # not typed on the calling thread
    deferred[0]()
    assert ("type", "hi") in kb.events


def test_noop_and_unmapped_do_not_dispatch():
    deferred = []
    r = ActionRouter({4: "noop"}, keyboard=FakeKeyboard(), dispatch=deferred.append)
    assert r.fire_slot(4) == "noop"
    assert r.fire_slot(9) == "unmapped"
    assert deferred == []            # nothing scheduled for inert slots


def test_default_dispatch_runs_inline():
    # No dispatcher injected -> synchronous (tests / non-GUI). Existing behavior.
    kb = FakeKeyboard()
    ActionRouter({1: "enter"}, keyboard=kb).fire_slot(1)
    assert ("press", "ENTER") in kb.events


def test_error_in_deferred_keystroke_is_captured_not_raised():
    class Boom(FakeKeyboard):
        def press(self, k):
            raise RuntimeError("no accessibility")
    r = ActionRouter({1: "enter"}, keyboard=Boom(), dispatch=lambda fn: fn())
    r.fire_slot(1)                   # must not raise
    assert "no accessibility" in (r.last_error or "")


from tink_agent.actions import ACTION_CATALOG, action_label


def test_catalog_entries_well_formed_and_ids_unique():
    ids = [a["id"] for a in ACTION_CATALOG]
    assert len(ids) == len(set(ids))                 # unique
    for a in ACTION_CATALOG:
        assert a["id"] and a["label"] and a["glyph"]  # all fields present
    assert "noop" in ids


def test_default_slot_actions_are_all_in_catalog():
    from tink_agent.config import Config
    ids = {a["id"] for a in ACTION_CATALOG}
    for action in Config().slot_actions.values():
        assert action in ids


def test_action_label_falls_back_for_unknown():
    assert action_label("enter") == "Enter"
    assert action_label("totally_unknown") == "totally_unknown"


def test_cmd_v_holds_cmd():
    kb = FakeKeyboard()
    r = ActionRouter({1: "cmd_v"}, keyboard=kb)
    assert r.fire_slot(1) == "cmd_v"
    assert ("hold", "CMD") in kb.events
    assert ("press", "v") in kb.events


def test_shift_enter_holds_shift():
    kb = FakeKeyboard()
    ActionRouter({1: "shift_enter"}, keyboard=kb).fire_slot(1)
    assert ("hold", "SHIFT") in kb.events
    assert ("press", "ENTER") in kb.events


def test_esc_esc_presses_escape_twice():
    kb = FakeKeyboard()
    ActionRouter({1: "esc_esc"}, keyboard=kb).fire_slot(1)
    assert kb.events.count(("press", "ESC")) == 2


def test_key_digit_types_char():
    kb = FakeKeyboard()
    ActionRouter({1: "key_2"}, keyboard=kb).fire_slot(1)
    assert ("press", "2") in kb.events and ("release", "2") in kb.events


def test_type_macro_types_text_then_enter():
    kb = FakeKeyboard()
    r = ActionRouter({1: "type:continue"}, keyboard=kb)
    assert r.fire_slot(1) == "type:continue"
    assert ("type", "continue") in kb.events
    assert ("press", "ENTER") in kb.events          # macro submits


def test_unknown_action_is_safe_noop():
    kb = FakeKeyboard()
    r = ActionRouter({1: "bogus"}, keyboard=kb)
    assert r.fire_slot(1) == "bogus"                # returned for logging
    assert kb.events == []                          # but nothing performed


def test_hold_key_press_and_release():
    kb = FakeKeyboard()
    r = ActionRouter({}, keyboard=kb)
    r.hold_key("f13", True)
    r.hold_key("f13", False)
    assert kb.events == [("press", "F13"), ("release", "F13")]


def test_hold_key_unknown_name_falls_back_to_literal():
    kb = FakeKeyboard()
    r = ActionRouter({}, keyboard=kb)
    r.hold_key("§", True)
    assert kb.events == [("press", "§")]
