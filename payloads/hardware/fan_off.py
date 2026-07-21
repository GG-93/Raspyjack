#!/usr/bin/env python3
"""
RaspyJack payload: Fan OFF

Forces the fan fully off, overriding temperature control. Runs instantly
and exits — the background fan service picks up the override within ~2
seconds. Pick "Fan Auto" to return to automatic temperature-based control.

Note: this keeps the fan off even if the CPU heats up, so use it briefly.
"""
OVERRIDE_PATH = "/dev/shm/rj_fan_override"

with open(OVERRIDE_PATH, "w") as f:
    f.write("off")

print("[Fan] Override set to OFF.")
print("[Fan] Fan stays off regardless of temperature. Run 'Fan Auto' to restore automatic control.")
