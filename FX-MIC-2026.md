# EP-2350 FX Mic (2026 model) + Wispr Flow notes

Working setup on a Teenage Engineering EP-2350 **FX Mic** (the 2026 re-release,
firmware 1.0.9), using this branch's handle-as-push-to-talk feature.

## Differences from the original Ting

- Buttons: **orange** = effect preset (no LED = clean, plays no samples),
  **white** = sample select, **grey** = play sample.
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
- `stt_command: ["true"]` disables local STT; Wispr does the typing.
- `tones`: 1000 Hz and 380 Hz both map to `enter`; the rest are decoy bins.
- `target_apps`: Terminal and the Claude desktop app.

Audio path: Ting line-out → Cubilux HLMS-C4 **Line IN** (not MIC IN; the Ting
is a 2 VRMS line output).

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
