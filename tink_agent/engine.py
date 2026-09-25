from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor


class Engine:
    def __init__(self, config, detector, voicegate, transcriber, router,
                 on_event=None, submit_fn=None, frontmost_fn=None, logger=None):
        self.config = config
        self.detector = detector
        self.voicegate = voicegate
        self.transcriber = transcriber
        self.router = router
        self.logger = logger
        self.enabled = config.enabled
        self._tone_in_utt = False   # a button tone fired inside the open utterance
        self._post_tone = 0         # blocks left to keep the voice gate closed after a tone
        self._handle_held = False
        self._handle_run = 0        # consecutive blocks on the "other" side of the threshold
        self._handle_guard = 0      # blocks to ignore after a button tone
        self._on_event = on_event or (lambda kind, payload: None)
        # Optional safety guard: when config.target_app is set, actions/typing
        # only fire if the frontmost app's name or bundle id contains it.
        # frontmost_fn() -> str is injectable for tests; defaults to NSWorkspace.
        self._frontmost_fn = frontmost_fn or _default_frontmost
        if submit_fn is not None:
            self._submit = submit_fn
        else:
            self._pool = ThreadPoolExecutor(max_workers=1)
            self._submit = lambda fn: self._pool.submit(fn)

    @property
    def is_capturing(self) -> bool:
        """True while an utterance is open (used by the menu bar indicator)."""
        return bool(getattr(self.voicegate, "active", False))

    def _front(self) -> str:
        try:
            return self._frontmost_fn() or ""
        except Exception:  # noqa: BLE001 — never let the guard crash the path
            return ""

    def _target_ok(self, front: str) -> bool:
        targets = [t.strip().lower()
                   for t in (self.config.target_apps or []) if t and t.strip()]
        if not targets:
            return True
        f = front.lower()
        return any(t in f for t in targets)

    def handle_block(self, block):
        if not self.enabled:
            return
        slot = self.detector.process(block)
        self._update_handle(block, slot)
        if slot is not None:
            front = self._front()
            if self._target_ok(front):
                action = self.router.fire_slot(slot)
                self._on_event("tone", slot)
                self._on_event("action", action)
                if self.logger:
                    self.logger.action(slot, action, front)
            else:
                self._on_event("blocked", slot)
                if self.logger:
                    self.logger.blocked(f"slot{slot}", front)
        if slot is not None:
            self._tone_in_utt = True
            self._post_tone = 16  # ~800 ms at 50 ms blocks: covers the beep's decay
        gate_closed = self.detector.tone_active or self._post_tone > 0
        if self._post_tone > 0:
            self._post_tone -= 1
        utterance = self.voicegate.process(block, gate_closed)
        if utterance is not None:
            if self._tone_in_utt:
                self._on_event("dropped", "tone in utterance")
            else:
                self._submit(lambda u=utterance: self._handle_utterance(u))
            self._tone_in_utt = False
        elif not self.voicegate.active and self._post_tone == 0:
            self._tone_in_utt = False

    def _update_handle(self, block, slot=None):
        """Hold handle_key while the Ting is 'live': down on the first non-tone sound
        (the squeeze hiss or speech), up after handle_off_blocks of silence or as soon
        as a button tone fires. Tone blocks never count as sound."""
        key = getattr(self.config, "handle_key", "")
        if not key:
            return
        import numpy as _np
        b = _np.asarray(block, dtype=_np.float64).reshape(-1)
        rms = float(_np.sqrt(_np.mean(b * b))) if b.size else 0.0
        tone = self.detector.tone_active or slot is not None
        if slot is not None:
            self._handle_guard = 20  # ~1 s: ignore the beep's tail as "sound"
            if self._handle_held:
                self._handle_held = False; self._handle_run = 0
                self.router.hold_key(key, False)
                self._on_event("handle", "released")
                if self.logger: self.logger.action("handle", f"{key}:up", self._front())
            return
        if self._handle_guard > 0:
            self._handle_guard -= 1
            return
        if not self._handle_held:
            self._handle_run = self._handle_run + 1 if (rms >= self.config.handle_rms_on and not tone) else 0
            if self._handle_run >= self.config.handle_on_blocks:
                self._handle_held = True; self._handle_run = 0
                self.router.hold_key(key, True)
                self._on_event("handle", "held")
                if self.logger: self.logger.action("handle", f"{key}:down", self._front())
        else:
            self._handle_run = self._handle_run + 1 if rms < self.config.handle_rms_off else 0
            if self._handle_run >= self.config.handle_off_blocks:
                self._handle_held = False; self._handle_run = 0
                self.router.hold_key(key, False)
                self._on_event("handle", "released")
                if self.logger: self.logger.action("handle", f"{key}:up", self._front())

    def _handle_utterance(self, utterance):
        text = self.transcriber.transcribe(utterance, self.config.sample_rate)
        if not text:
            if self.transcriber.last_error:
                self._on_event("error", self.transcriber.last_error)
            return
        front = self._front()
        if not self._target_ok(front):
            self._on_event("blocked", text)
            if self.logger:
                self.logger.blocked(text, front)
            return
        self.router.type_text(text)
        self._on_event("transcript", text)
        if self.logger:
            self.logger.transcript(text, front)


def _default_frontmost() -> str:
    """Frontmost app identity (name + bundle id) via AppKit, or "" if unavailable."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        return f"{app.localizedName() or ''} {app.bundleIdentifier() or ''}"
    except Exception:  # noqa: BLE001
        return ""
