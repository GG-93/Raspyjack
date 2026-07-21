#!/usr/bin/env python3
"""
RaspyJack payload: Fan ON

Forces the fan to 100% immediately, overriding temperature control.
Runs instantly and exits — the background fan service picks up the
override within ~2 seconds. Pick "Fan Auto" to return to automatic
temperature-based control.
"""
OVERRIDE_PATH = "/dev/shm/rj_fan_override"

with open(OVERRIDE_PATH, "w") as f:
    f.write("on")

print("[Fan] Override set to ON (100%).")
print("[Fan] The fan spins up within ~2s. Run 'Fan Auto' to hand control back to temperature.")
