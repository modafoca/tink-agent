# EP-2350 FX Mic (2026 model) + Wispr Flow notes

Working setup on a Teenage Engineering EP-2350 **FX Mic** (the 2026 re-release,
firmware 1.0.9), using this branch's handle-as-push-to-talk feature.

## Differences from the original Ting

- Buttons: **small orange** = effect preset (no LED = clean, plays no samples),
  **white** = sample select, **grey** = play sample.
- The **large orange handle** is the control you squeeze to speak. Its position
  is not sent to the Mac; Tink infers speech from the line-out audio.
- USB-C port is under the removable lower lid. The drive mounts as
  `FX MIC DISK`, not `TINGDISK`.
- Firmware 1.0.9 did **not** import `1.wav`..`4.wav` / `config.json` from the
  disk, even after a cold boot with batteries out. Custom tones were therefore
  unusable; the factory samples are used instead.
- Factory samples that are clean enough to detect: slot 1 **horn ≈ 380 Hz**,
  slot 4 **censor beep = 1000 Hz**. Slots 2 (claps) and 3 (bell) are not tones.
- White resets to slot 1 on every boot.
- The line-out is digitally silent while the handle is squeezed unless there is
  sound, so a pure "handle held" detector flaps. Hence the hybrid hold: key down
  on the first non-tone sound, key up after `handle_off_blocks` of silence or on
  any button tone.
- The button above the USB-C port does not power the unit off while on USB
  power; only pulling the batteries guarantees a reboot.

## Config

See `examples/config.ep-2350-fx-mic-wispr.json`:

- `handle_key: "f13"` holds F13 while the mic is live. Wispr Flow's push-to-talk
  is set to F13 (key code 105).
- `handle_rms_on: 80.0`, `handle_rms_off: 55.0`: calibrated start/release
  thresholds for this FX Mic + Cubilux setup. See the calibration notes below.
- `handle_on_blocks: 2`, `handle_off_blocks: 50`: start after 100 ms above
  the start threshold, release after 2.5 seconds below the release threshold
  (800-sample blocks at 16 kHz).
- `stt_command: ["true"]` disables local STT; Wispr does the typing.
- `tones`: 1000 Hz and 380 Hz both map to `enter`; the rest are decoy bins.
- `target_apps`: Terminal and the Claude desktop app.

Audio path: Ting line-out → Cubilux HLMS-C4 **Line IN** (not MIC IN; the Ting
is a 2 VRMS line output).

## Handle calibration (Oct 5 2026)

With the earlier 6/3 RMS thresholds, background noise could start Flow without
speaking and keep F13 held after the handle was released. An initial idle check
measured below 0.5 RMS, but a later check with the handle released during the
problem measured 23–38 RMS. Normal speech had a median around 188 RMS. The cause
of the changing noise floor was not established.

The example now uses **80 RMS to start** and **55 RMS to release**, retaining the
2.5-second release delay. Live testing confirmed that squeezing and speaking
started Flow and releasing the handle stopped it. These are setup-specific
values, not universal defaults; existing user configs are not migrated.

If false starts or stuck recordings return:

1. Measure the released-handle noise while Flow is in the failing state, then
   measure normal speech with the handle held. Use the same audio input and
   gain for both checks.
2. Keep the release threshold above the observed idle noise and the start
   threshold above release but comfortably below normal speech. If the levels
   overlap, check the input, cable, gain, and mic state before tuning further.
3. Update `handle_rms_on` and `handle_rms_off` in
   `~/.tink-agent/config.json` and restart Tink. Release the handle and stop any
   active Flow recording before restarting, so a previously held shortcut does
   not leave a recording running.
4. Verify both directions: squeeze and speak to start, release and wait about
   2.5 seconds to stop, then leave the handle released to check for false starts.

This is an audio-triggered shortcut, not a physical button signal. A quiet held
handle may not start Flow until speech begins; a long enough quiet pause can
release the shortcut even while the handle remains held. Flow's microphone
Auto-detect selects its input; Tink's F13 events control this recording path.

## Bell as a third action (Sep 24 2026)

Slot 3's ringside bell is inharmonic: partials at ~3949 Hz and ~5363 Hz that
beat against each other, so per-block tonality wobbles 0.05–0.5 and the level
briefly dips under the detector floor. Two detector changes make it usable:

- `tone_tonality_min_by_slot` lets one bin (3949 Hz) use a lower tonality
  threshold (0.25) without loosening the horn/beep bins. Speech never reaches
  that bin with any tonality.
- A press now ends only after 8 consecutive sub-floor blocks (400 ms), so the
  beating ring does not re-fire after a dip.

Slot 2 ("claps", ~4 s of applause) is not a tone, so the tone detector cannot
use it. It is handled by `NoiseBurstDetector` instead: applause is loud and
*unvoiced* for seconds at a time, whereas speech shows pitch in nearly every
half second (longest unvoiced run in my speech recordings: 3 blocks; applause:
50–64). `noise_action` fires after 12 consecutive loud, unvoiced, non-tone
blocks (0.6 s). The burst is treated like a tone: it releases the push-to-talk
key, is never sent to the STT, and any fires within one continuous sound count
as one press (the sample also contains a bell hit).

Mapping: horn (slot 1) and beep (slot 4) → Enter, bell (slot 3) and applause
(slot 2) → Tab. Tab-then-Enter is one white press either way.
