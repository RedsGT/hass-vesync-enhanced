# -*- coding: utf-8 -*-
"""Apply VeSync Enhanced's pyvesync patches.

Run this INSIDE the Home Assistant container so it edits the bundled
pyvesync (the version pinned by the integration's manifest).

What it does (idempotent — safe to re-run):

  1. Adds `cook_mode` and `cook_start_time` slots + initializers to
     `AirFryer158State` so the integration can hang those sensor values
     on the device state.
  2. Replaces `_get_details_wfon` with a version that uses bypassV2 with
     `getAirfryerStatus` (works without a PID, which the API doesn't
     return for WFON devices), normalises temperatures into Celsius, and
     captures `cook_mode` / `cook_start_time` from the response.
  3. Adds `_wfon_bypass_v2`, `wfon_start_cook`, and `wfon_end_cook`
     methods used by the integration's switch/number/select entities to
     remotely control the fryer.

Usage on Home Assistant Yellow / OS:

    cat scripts/patch_pyvesync.py | ssh root@<your_ha_ip> \
      "docker exec -i homeassistant sh -c \
        'cat > /tmp/patch.py && python3 /tmp/patch.py'"

Or copy the file in any way you like and run it via `python3 patch.py`
inside the homeassistant container.
"""
import re
import sys
from pathlib import Path

# ── Locate pyvesync ──────────────────────────────────────────────────────────
candidates = [
    p for p in Path('/usr/local/lib').glob('python3.*/site-packages/pyvesync')
] + [
    p for p in Path('/usr/lib').glob('python3.*/site-packages/pyvesync')
]
if not candidates:
    sys.exit('ERROR: cannot locate pyvesync — is this the HA container?')
PYVESYNC = candidates[0]
KITCHEN = PYVESYNC / 'devices' / 'vesynckitchen.py'
print(f'Patching {KITCHEN}')

txt = KITCHEN.read_text()

# ── 1. Add cook_mode / cook_start_time slots ─────────────────────────────────
OLD_SLOTS = "        'ready_start',\n    )"
NEW_SLOTS = (
    "        'ready_start',\n"
    "        'cook_mode',\n"
    "        'cook_start_time',\n"
    "    )"
)
if OLD_SLOTS in txt and "'cook_mode'," not in txt:
    txt = txt.replace(OLD_SLOTS, NEW_SLOTS, 1)
    print('  __slots__: added cook_mode / cook_start_time')
else:
    print('  __slots__: already patched or pattern moved')

# ── 2. Init the new slots in __init__ ────────────────────────────────────────
INIT_MARKER = (
    "        self.preheat_last_time: int | None = None\n"
    "        self._temp_unit: str | None = None"
)
INIT_NEW = (
    INIT_MARKER + "\n"
    "        self.cook_mode: str | None = None\n"
    "        self.cook_start_time = None"
)
INIT_DONE = (
    "        self._temp_unit: str | None = None\n"
    "        self.cook_mode: str | None = None"
)
if INIT_DONE in txt:
    print('  __init__: already initialised')
elif INIT_MARKER in txt:
    txt = txt.replace(INIT_MARKER, INIT_NEW, 1)
    print('  __init__: added initialisers')
else:
    print('  __init__: WARNING marker not found')

# ── 3. Replace _get_details_wfon with a clean WFON-aware version ─────────────
CLEAN_GET_DETAILS = """    async def _get_details_wfon(self) -> None:
        \"\"\"Get status for WFON/CAF air fryers via bypassV2 (no PID required).\"\"\"
        from datetime import datetime, timezone
        req = self._build_request()
        req.pop('jsonCmd', None)
        req.pop('pid', None)
        req.pop('uuid', None)
        req['method'] = 'bypassV2'
        req['appVersion'] = 'VeSync 5.7.80 build693'
        req['payload'] = {'data': {}, 'method': 'getAirfryerStatus', 'source': 'APP'}
        r_dict, _ = await self.manager.async_call_api(
            '/cloud/v2/deviceManaged/bypassV2', 'post', json_object=req
        )
        if r_dict is None:
            self.state.device_status = DeviceStatus.OFF
            self.state.connection_status = ConnectionStatus.OFFLINE
            return
        outer = r_dict.get('result') or {}
        inner = (outer.get('result') or {}) if isinstance(outer, dict) else {}
        if not inner:
            return

        # currentTemp arrives in Celsius regardless of tempUnit; preserve it.
        if 'currentTemp' in inner:
            inner['curentTemp'] = inner['currentTemp']

        # Normalise per-step fields so status_response can consume them.
        # cookTemp arrives in the user's chosen unit (tempUnit). Convert to
        # Celsius so both temperatures share a native unit.
        step = (inner['stepArray'][0]) if inner.get('stepArray') else {}
        raw_unit = (inner.get('tempUnit') or 'f').lower()
        if step:
            if 'cookTemp' in step:
                cook_temp = step['cookTemp']
                if raw_unit in ('f', 'fahrenheit', 'fahrenheight'):
                    cook_temp = round((cook_temp - 32) * 5 / 9, 1)
                inner['cookSetTemp'] = cook_temp
            # API gives times in seconds; HA duration sensor expects minutes
            if 'cookSetTime' in step:
                inner['cookSetTime'] = round(step['cookSetTime'] / 60)
            if 'cookLastTime' in step:
                inner['cookLastTime'] = round(step['cookLastTime'] / 60)

        inner['tempUnit'] = 'c'
        self.state.cook_mode = step.get('recipeName') or step.get('mode') if step else None
        start_ts = inner.get('startTime')
        self.state.cook_start_time = (
            datetime.fromtimestamp(start_ts, tz=timezone.utc) if start_ts else None
        )

        self.state.status_response(inner)

"""
m = re.search(
    r"    async def _get_details_wfon\(self\) -> None:.*?(?=\n    (?:async )?def )",
    txt, re.DOTALL,
)
if m:
    txt = txt[:m.start()] + CLEAN_GET_DETAILS + txt[m.end():]
    print('  _get_details_wfon: rewritten')
else:
    print('  _get_details_wfon: WARNING not found')

# ── 4. Add WFON control methods (idempotent) ─────────────────────────────────
WFON_METHODS = '''
    # ── WFON remote control (CAF-P583S etc.) ─────────────────────────────────
    # See https://github.com/webdjoe/pyvesync/issues/477
    WFON_RECIPES = {
        "Air Fry":      {"id": 14, "type": 3, "mode": "AirFry"},
        "Broil":        {"id": 17, "type": 3, "mode": "Broil"},
        "Roast":        {"id": 13, "type": 3, "mode": "Roast"},
        "Bake":         {"id": 9,  "type": 3, "mode": "Bake"},
        "Reheat":       {"id": 16, "type": 3, "mode": "Reheat"},
        "Steak":        {"id": 1,  "type": 3, "mode": "Steak"},
        "Seafood":      {"id": 3,  "type": 3, "mode": "Seafood"},
        "Veggies":      {"id": 15, "type": 3, "mode": "Veggies"},
        "French Fries": {"id": 6,  "type": 3, "mode": "FrenchFries"},
        "Frozen":       {"id": 5,  "type": 3, "mode": "Frozen"},
        "Chicken":      {"id": 2,  "type": 3, "mode": "Chicken"},
    }

    async def _wfon_bypass_v2(self, method: str, data: dict) -> bool:
        """Send a bypassV2 command. Returns True on outer code 0."""
        req = self._build_request()
        req.pop('jsonCmd', None)
        req.pop('pid', None)
        req.pop('uuid', None)
        req['method'] = 'bypassV2'
        req['appVersion'] = 'VeSync 5.6.60'
        req['payload'] = {'method': method, 'source': 'APP', 'data': data}
        r_dict, _ = await self.manager.async_call_api(
            '/cloud/v2/deviceManaged/bypassV2', 'post', json_object=req
        )
        return r_dict is not None and r_dict.get('code', -1) == 0

    async def wfon_start_cook(self, set_temp_c: float, set_time_min: int,
                              preset: str = 'Air Fry') -> bool:
        """Start a cook. Temperature in Celsius, time in minutes."""
        import asyncio as _a
        recipe = self.WFON_RECIPES.get(preset, self.WFON_RECIPES['Air Fry'])
        config = {
            "accountId": self.manager.account_id,
            "hasLinkage": False, "hasPreheat": 0, "hasWarm": False,
            "mode": recipe["mode"], "readyStart": False,
            "recipeId": recipe["id"], "recipeName": preset,
            "recipeType": recipe["type"],
            "startAct": {
                "cookSetTime": int(set_time_min * 60),
                "cookTemp": round(set_temp_c * 9 / 5 + 32),
                "preheatTemp": 0, "shakeTime": 0,
            },
            "tempUnit": "f",
        }
        ok = await self._wfon_bypass_v2("startCook", config)
        if not ok:
            return False
        await _a.sleep(1)
        await self._wfon_bypass_v2("setSwitch", {"startStop": "start"})
        await self._wfon_bypass_v2("updateDeviceStatus", {"readyStart": True})
        # Refresh local state so HA reads cookStatus=cooking immediately
        await _a.sleep(1.5)
        try:
            await self._get_details_wfon()
        except Exception:
            pass
        return True

    async def wfon_end_cook(self) -> bool:
        """End the current cook."""
        ok = await self._wfon_bypass_v2("endCook", {})
        if ok:
            import asyncio as _a
            await _a.sleep(1.5)
            try:
                await self._get_details_wfon()
            except Exception:
                pass
        return ok

'''

if 'wfon_start_cook' in txt:
    print('  control methods: already present')
else:
    m2 = re.search(
        r"    async def _get_details_wfon\(self\) -> None:.*?(?=\n    (?:async )?def )",
        txt, re.DOTALL,
    )
    if m2:
        txt = txt[:m2.end()] + WFON_METHODS + txt[m2.end():]
        print('  control methods: added')
    else:
        print('  control methods: WARNING anchor not found')

KITCHEN.write_text(txt)

# ── Clear pyc cache so next import re-compiles ───────────────────────────────
import glob, os
for f in glob.glob(str(PYVESYNC / '**' / '*.pyc'), recursive=True):
    os.remove(f)
print('Done — restart Home Assistant to load the patched pyvesync')
