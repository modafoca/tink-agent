from __future__ import annotations

# Catalog of selectable per-slot actions: the single source of truth shared by
# the router (what an id does, below) and the Button Actions UI (label + glyph).
# `type:<text>` ids type the literal text then press Enter (submit).
ACTION_CATALOG = [
    {"id": "enter",         "label": "Enter",                  "glyph": "⏎"},
    {"id": "escape",        "label": "Escape",                 "glyph": "⎋"},
    {"id": "esc_esc",       "label": "Double Esc (clear)",     "glyph": "⎋⎋"},
    {"id": "ctrl_c",        "label": "Ctrl + C (interrupt)",   "glyph": "⌃C"},
    {"id": "ctrl_d",        "label": "Ctrl + D",               "glyph": "⌃D"},
    {"id": "tab",           "label": "Tab",                    "glyph": "⇥"},
    {"id": "shift_tab",     "label": "Shift + Tab (mode)",     "glyph": "⇤"},
    {"id": "shift_enter",   "label": "Shift + Enter (newline)","glyph": "⇧⏎"},
    {"id": "up",            "label": "Arrow Up",               "glyph": "↑"},
    {"id": "down",          "label": "Arrow Down",             "glyph": "↓"},
    {"id": "left",          "label": "Arrow Left",             "glyph": "←"},
    {"id": "right",         "label": "Arrow Right",            "glyph": "→"},
    {"id": "space",         "label": "Space",                  "glyph": "␣"},
    {"id": "backspace",     "label": "Backspace",              "glyph": "⌫"},
    {"id": "cmd_v",         "label": "Paste",                  "glyph": "⌘V"},
    {"id": "key_1",         "label": 'Type "1"',     "glyph": "1"},
    {"id": "key_2",         "label": 'Type "2"',     "glyph": "2"},
    {"id": "key_3",         "label": 'Type "3"',     "glyph": "3"},
    {"id": "type:yes",      "label": 'Send "yes"',       "glyph": "y"},
    {"id": "type:continue", "label": 'Send "continue"',  "glyph": "»"},
    {"id": "type:/clear",   "label": "Send /clear",            "glyph": "/"},
    {"id": "type:/compact", "label": "Send /compact",          "glyph": "/"},
    {"id": "noop",          "label": "No action",              "glyph": "–"},
]

_CATALOG_BY_ID = {a["id"]: a for a in ACTION_CATALOG}


def action_label(action_id: str) -> str:
    a = _CATALOG_BY_ID.get(action_id)
    return a["label"] if a else (action_id or "No action")


class ActionRouter:
    def __init__(self, slot_actions, keyboard=None, dispatch=None):
        self.slot_actions = dict(slot_actions)
        self._kb = keyboard  # injected (tests) or lazy pynput controller
        # All pynput calls must run on the main thread: on macOS pynput queries
        # the keyboard layout via HIToolbox TSM, which traps (SIGTRAP via
        # libdispatch) when invoked off the main thread under a running NSApp.
        # fire_slot runs on the audio callback thread and type_text on the
        # transcription worker thread, so the menu bar injects a main-thread
        # dispatcher. Default = run inline (tests / non-GUI).
        self._dispatch = dispatch or (lambda fn: fn())
        self.last_error: str | None = None

    @property
    def kb(self):
        if self._kb is None:
            from pynput import keyboard
            ctrl = keyboard.Controller()
            ctrl.Key = keyboard.Key  # attach enum for uniform access
            self._kb = ctrl
        return self._kb

    def hold_key(self, name: str, down: bool) -> None:
        """Press (down=True) or release a named key, e.g. "f13", for push-to-talk.
        Runs on the main thread like every other keystroke."""
        def _do(_):
            kb = self.kb
            key = getattr(kb.Key, name, None) or name
            (kb.press if down else kb.release)(key)
        self._dispatch(lambda: self._run(_do, None))

    def fire_slot(self, slot: int) -> str:
        action = self.slot_actions.get(slot)
        if action is None:
            return "unmapped"
        if action == "noop":
            return "noop"
        # Defer the actual keystroke to the main thread; return the action id
        # now so the caller can emit events / log without waiting.
        self._dispatch(lambda a=action: self._run(self._perform, a))
        return action

    def _run(self, fn, arg) -> None:
        """Execute a keyboard side-effect (on the main thread), trapping errors
        (e.g. missing Accessibility) so they never crash the calling thread."""
        try:
            fn(arg)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)

    def _perform(self, action: str) -> None:
        kb = self.kb
        Key = kb.Key
        if action == "enter":
            kb.press(Key.enter); kb.release(Key.enter)
        elif action == "escape":
            kb.press(Key.esc); kb.release(Key.esc)
        elif action == "ctrl_c":
            with kb.pressed(Key.ctrl):
                kb.press("c"); kb.release("c")
        elif action == "tab":
            kb.press(Key.tab); kb.release(Key.tab)
        elif action == "shift_tab":
            with kb.pressed(Key.shift):
                kb.press(Key.tab); kb.release(Key.tab)
        elif action == "up":
            kb.press(Key.up); kb.release(Key.up)
        elif action == "down":
            kb.press(Key.down); kb.release(Key.down)
        elif action == "esc_esc":
            kb.press(Key.esc); kb.release(Key.esc)
            kb.press(Key.esc); kb.release(Key.esc)
        elif action == "ctrl_d":
            with kb.pressed(Key.ctrl):
                kb.press("d"); kb.release("d")
        elif action == "shift_enter":
            with kb.pressed(Key.shift):
                kb.press(Key.enter); kb.release(Key.enter)
        elif action == "left":
            kb.press(Key.left); kb.release(Key.left)
        elif action == "right":
            kb.press(Key.right); kb.release(Key.right)
        elif action == "space":
            kb.press(Key.space); kb.release(Key.space)
        elif action == "backspace":
            kb.press(Key.backspace); kb.release(Key.backspace)
        elif action == "cmd_v":
            with kb.pressed(Key.cmd):
                kb.press("v"); kb.release("v")
        elif action in ("key_1", "key_2", "key_3"):
            ch = action[-1]
            kb.press(ch); kb.release(ch)
        elif action.startswith("type:"):
            self._do_type(action[len("type:"):])
            kb.press(Key.enter); kb.release(Key.enter)

    def type_text(self, text: str) -> None:
        if not text:
            return
        self._dispatch(lambda t=text: self._run(self._do_type, t))

    def _do_type(self, text: str) -> None:
        self.kb.type(text)
