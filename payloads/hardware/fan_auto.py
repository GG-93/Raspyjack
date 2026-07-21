#!/usr/bin/env python3
"""
RaspyJack payload: Fan Auto

Clears any manual override and returns the fan to automatic temperature-based
control (the settings in config/headless.json -> fan_control). Runs instantly
and exits — the background fan service resumes automatic control within ~2s.
"""
import os

OVERRIDE_PATH = "/dev/shm/rj_fan_override"

try:
    os.remove(OVERRIDE_PATH)
except FileNotFoundError:
    pass

print("[Fan] Override cleared — automatic temperature control resumed.")
