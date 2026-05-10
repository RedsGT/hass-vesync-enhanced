# VeSync Enhanced for Home Assistant

A drop-in replacement for Home Assistant's built-in `vesync` integration
that adds first-class support for the **Cosori Dual Blaze (CAF-P583S)**
air fryer and richer entities for any VeSync air fryer.

This is a fork of the official integration; everything that worked
before still works. The new bits are layered on top.

## What's added

For air fryers:

| Entity                              | Type           | Notes                                                              |
| ----------------------------------- | -------------- | ------------------------------------------------------------------ |
| `switch.<fryer>_cooking`            | Switch         | Start with staged settings (on); end the cook (off).               |
| `number.<fryer>_cooking_temperature`| Number         | 175–400°F native, integer step. Stages or live-updates a cook.     |
| `number.<fryer>_cooking_time`       | Number         | 1–60 min. Stages or live-updates a cook.                           |
| `select.<fryer>_cooking_preset`     | Select         | 11 presets. Picking one stages its default temp/time.              |
| `sensor.<fryer>_cooking_mode`       | Sensor         | Current cooking preset name.                                       |
| `sensor.<fryer>_cook_started`       | Sensor (date)  | Cook start timestamp.                                              |
| `sensor.<fryer>_cooking_time_remaining` | Sensor     | Minutes left in the active cook.                                   |
| `binary_sensor.<fryer>_up_to_temperature` | Binary   | True while cooking and current temp ≥ setpoint − 10°F (deadband).  |
| `sensor.<fryer>_safe_to_handle_at`  | Sensor (date)  | Estimated cooldown ETA via Newton's law from the captured setpoint.|

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

## Installation

### 1. Patch pyvesync (one-time, until upstream merges)

The bundled pyvesync needs WFON-aware control methods. From your
Home Assistant host:

```bash
# adjust SSH command for your setup
cat scripts/patch_pyvesync.py | ssh root@<ha_ip> \
  "docker exec -i homeassistant sh -c 'cat > /tmp/patch.py && python3 /tmp/patch.py'"
```

The script is idempotent — safe to re-run after every HA core update,
which reinstalls pyvesync.

### 2. Install the integration

#### Via HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**
2. URL: `https://github.com/RedsGT/hass-vesync-enhanced` — Type: **Integration**
3. Find "VeSync Enhanced" in the integrations list and install
4. Restart Home Assistant

#### Manual

Copy `custom_components/vesync/` to your config directory at
`/config/custom_components/vesync/` and restart.

Home Assistant loads custom components in preference to built-in ones
with the same domain — your existing VeSync config flow stays exactly
where it is.

## Caveats

- **Remote start works**, contrary to some claims that UL safety regs
  prevent it. Tested on CAF-P583S-KUS firmware v1.0.15.
- **HA restart loses the cooldown ETA tracking** — the in-memory
  cook-end timestamp is reset, and `safe_to_handle_at` will report
  unknown until the next cook ends. Fixable by persisting state, just
  not done yet.
- **Cooldown estimate is a model**, not a measurement — Newton's law
  with `k=0.06/min`, ambient 72°F, safe threshold 110°F. The API
  freezes `currentTemp` after a cook ends, so we can't watch it cool
  in real time.

## Status & roadmap

- ✅ Tested on Cosori CAF-P583S-KUS (Dual Blaze 6.8qt)
- ✅ pyvesync upstream PR open: [webdjoe/pyvesync#517](https://github.com/webdjoe/pyvesync/pull/517)
- 🔜 When the pyvesync `air-fryer-refactor` branch lands and HA core
  picks it up, this custom component will become unnecessary for basic
  support — but the UX entities here will still be a delta worth keeping.

## Acknowledgements

- Protocol reverse-engineered from the working script in
  [webdjoe/pyvesync#477](https://github.com/webdjoe/pyvesync/issues/477)
  by [@mikealanni](https://github.com/mikealanni).
- The HA integration patches and supporting code were authored with
  assistance from Claude (Anthropic).

## License

Apache 2.0 (same as upstream Home Assistant).
