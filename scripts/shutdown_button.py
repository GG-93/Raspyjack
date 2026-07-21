#!/usr/bin/env python3
"""
RaspyJack Shutdown Button
Watches GPIO 17 for a button press and issues a clean shutdown.

Wiring:
  Button leg 1 → Pin 11 (GPIO 17, BCM)
  Button leg 2 → Pin 9  (GND)

Uses internal pull-up — no resistor needed.
Press and hold for 2 seconds to trigger shutdown (prevents accidental presses).
"""

import time
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="[ShutdownBtn] %(message)s")

SHUTDOWN_PIN = 17
HOLD_SECONDS = 2  # hold button this long to trigger shutdown

try:
    import RPi.GPIO as GPIO
except ImportError:
    logging.error("RPi.GPIO not available. Is this running on a Pi?")
    sys.exit(1)

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(SHUTDOWN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

logging.info(f"Watching GPIO {SHUTDOWN_PIN}. Hold {HOLD_SECONDS}s to shut down.")

try:
    # Poll the pin instead of GPIO.wait_for_edge(): on current Raspberry Pi OS
    # (Bookworm) RPi.GPIO edge detection raises "RuntimeError: Error waiting for
    # edge", so we sample the input every 50 ms — negligible CPU, and it works
    # reliably across kernels.
    while True:
        if GPIO.input(SHUTDOWN_PIN) == GPIO.LOW:      # button pressed
            press_time = time.monotonic()

            # Wait for release or the hold threshold
            while GPIO.input(SHUTDOWN_PIN) == GPIO.LOW:
                if time.monotonic() - press_time >= HOLD_SECONDS:
                    logging.info("Shutdown button held — shutting down now.")
                    os.system("shutdown now")
                    sys.exit(0)
                time.sleep(0.05)

            # Short press — ignore
            logging.info("Short press detected (ignored). Hold 2s to shut down.")

        time.sleep(0.05)

except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
