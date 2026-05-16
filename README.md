# VeSync Enhanced for Home Assistant

A drop-in replacement for Home Assistant's built-in `vesync` integration
that adds first-class support for the **Cosori Dual Blaze (CAF-P583S)**
air fryer and richer entities for any VeSync air fryer.

This is a fork of the official integration; everything that worked
before still works. The new bits are layered on top.

## What's added

For air fryers:

| Entity                                      | Type          | Notes                                                              |
| ------------------------------------------- | ------------- | ------------------------------------------------------------------ |
| `switch.<fryer>_cooking`                    | Switch        | Start with staged settings (on); end the cook (off).               |
| `number.<fryer>_cooking_temperature`        | Number        | 175–400°F native, integer step. Stages or live-updates a cook.     |
| `number.<fryer>_cooking_time`               | Number        | 1–60 min. Stages or live-updates a cook.                           |
| `select.<fryer>_cooking_preset`             | Select        | 11 presets. Picking one stages its default temp/time.              |
| `sensor.<fryer>_cooking_mode`               | Sensor        | Current cooking preset name.                                       |
| `sensor.<fryer>_cook_started`               | Sensor (date) | Cook start timestamp.                                              |
| `sensor.<fryer>_cooking_time_remaining`     | Sensor        | Minutes left in the active cook.                                   |
| `binary_sensor.<fryer>_up_to_temperature`   | Binary        | True while cooking and current temp ≥ setpoint − 10°F (deadband).  |
| `sensor.<fryer>_safe_to_handle_at`          | Sensor (date) | Estimated cooldown ETA via Newton's law from the captured setpoint.|

Behaviour quality-of-life:

- **Setting temperature, time, or preset while cooking** restarts the
  cook with the new value but **preserves remaining time** if you only
  changed the temperature (and vice versa).
- **Picking a preset auto-fills** that preset's default temp and time.
- **Dynamic polling**: every 10 seconds while cooking, every 60 seconds
  idle. No fryer? Same behaviour as upstream.
- **`current_temp` is masked** to `unknown` when the fryer is in
  standby. The API reports a stale frozen value otherwise — masking
  prevents misleading dashboard readings.

## How it works

The Cosori Dual Blaze (CAF-P583S) isn't yet supported by upstream
`pyvesync` on PyPI. Support lives on a feature branch
([`webdjoe/pyvesync#517`](https://github.com/webdjoe/pyvesync/pull/517)),
maintained here as
[`RedsGT/pyvesync@wfon-caf-p583s`](https://github.com/RedsGT/pyvesync/tree/wfon-caf-p583s),
which registers `CAF-P583S-KUS`/`KEU` against the existing
`VeSyncTurboBlazeFryer` class with the full 11-preset recipe set.

To make this durable, `manifest.json` pins pyvesync to the branch via a
git URL rather than a PyPI version:

```json
"requirements": [
  "pyvesync @ git+https://github.com/RedsGT/pyvesync.git@wfon-caf-p583s"
]
```

Home Assistant's requirements installer honors `package @ url` syntax
and resolves it on every integration setup. This means HA core updates
that previously wiped manual patches now reinstall the correct
pyvesync automatically — no patch script, no shell hook, no manual
intervention.

The integration's cooking controls call pyvesync's native
`device.set_mode_from_recipe(...)` and `device.end()` directly through
thin helpers in `common.py` (`fryer_start_cook` / `fryer_end_cook`)
that translate the integration's display preset names ("Air Fry",
"Broil", …) into `AirFryerPresets` recipe objects and override
target temp and cook time with the user's staged values.

## Installation

### Via HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**
2. URL: `https://github.com/RedsGT/hass-vesync-enhanced` — Type: **Integration**
3. Find "VeSync Enhanced" in the integrations list and install
4. Restart Home Assistant

### Manual

Copy `custom_components/vesync/` to your config directory at
`/config/custom_components/vesync/` and restart.

Home Assistant loads custom components in preference to built-in ones
with the same domain — your existing VeSync config flow stays exactly
where it is.

### First start

On first startup after install (or after any HA core update), HA core
will fetch and install pyvesync from the git URL above. This requires:

- Network access from your HA host to `github.com`
- `git` available inside the homeassistant container (it is, by default)

If the install fails — usually a transient network issue — restart HA
core once more.

## Caveats

- **Remote start works.** The `startCook` bypassV2 payload with
  `readyStart=true` is accepted by VeSync's cloud on CAF-P583S
  (tested on firmware v1.0.15).
- **HA restart loses the cooldown ETA tracking.** The in-memory
  cook-end timestamp is reset, and `safe_to_handle_at` will report
  unknown until the next cook ends. Fixable by persisting state, just
  not done yet.
- **Cooldown estimate is a model**, not a measurement — Newton's law
  with `k=0.06/min`, ambient 72°F, safe threshold 110°F. The API
  freezes `currentTemp` after a cook ends, so we can't watch it cool
  in real time.

## Status & roadmap

- ✅ Tested on Cosori CAF-P583S-KUS (Dual Blaze 6.8qt)
- ✅ pyvesync upstream PR open: [webdjoe/pyvesync#517](https://github.com/webdjoe/pyvesync/pull/517) — three commits: device-map registration, full preset set, and a `getAirfyerStatus` typo fix that also unbreaks status polling for the existing CAF-DC601S TurboBlaze
- 🔜 When PR #517 merges and the change lands in a tagged pyvesync
  release on PyPI, flip the manifest pin from the git URL to a normal
  PyPI version (`"pyvesync==<version>"`). The integration's helpers
  and entities don't change — they already use upstream's native
  interface.

## Acknowledgements

- Protocol reverse-engineered from the working script in
  [webdjoe/pyvesync#477](https://github.com/webdjoe/pyvesync/issues/477)
  by [@mikealanni](https://github.com/mikealanni).
- The HA integration code and pyvesync branch work were authored with
  assistance from Claude (Anthropic).

## License

Apache 2.0 (same as upstream Home Assistant).