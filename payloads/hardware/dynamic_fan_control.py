#!/usr/bin/env python3
"""
RaspyJack Dynamic Fan Control Payload
Dynamically adjusts fan speed based on CPU temperature.

Safe GPIO pins (do not use HAT button pins 5,6,13,16,19,20,21,26):
- 17, 18 (hardware PWM), 27, 22, 23, 24

Settings are read from /root/Raspyjack/config/headless.json (fan_control section).
Hardcoded defaults are used if the config file is missing or fan_control is absent.
"""

import json
import os
import shutil
import time
import subprocess
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

CONFIG_PATH = "/root/Raspyjack/config/headless.json"

DEFAULTS = {
    "pin": 18,
    "min_temp_c": 45,
    "max_temp_c": 70,
    "min_duty": 20,
    "max_duty": 100,
}
UPDATE_INTERVAL = 8  # seconds


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        fc = data.get("fan_control", {})
        if not data.get("fan_control", {}).get("enabled", False):
            print("[FanControl] fan_control.enabled is false in config. Exiting.")
            sys.exit(0)
        return {
            "pin":        int(fc.get("pin",         DEFAULTS["pin"])),
            "min_temp":   float(fc.get("min_temp_c", DEFAULTS["min_temp_c"])),
            "max_temp":   float(fc.get("max_temp_c", DEFAULTS["max_temp_c"])),
            "min_duty":   int(fc.get("min_duty",     DEFAULTS["min_duty"])),
            "max_duty":   int(fc.get("max_duty",     DEFAULTS["max_duty"])),
        }
    except FileNotFoundError:
        print(f"[FanControl] Config not found at {CONFIG_PATH}, using defaults.")
        return dict(DEFAULTS, min_temp=DEFAULTS["min_temp_c"], max_temp=DEFAULTS["max_temp_c"])
    except Exception as e:
        print(f"[FanControl] Config error: {e}, using defaults.")
        return dict(DEFAULTS, min_temp=DEFAULTS["min_temp_c"], max_temp=DEFAULTS["max_temp_c"])


def get_cpu_temp():
    try:
        output = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        return float(output.split("=")[1].split("'")[0])
    except Exception:
        return 50.0


def calculate_duty(temp, cfg):
    if temp < cfg["min_temp"]:
        return 0  # fully off when cool
    if temp >= cfg["max_temp"]:
        return cfg["max_duty"]
    ratio = (temp - cfg["min_temp"]) / (cfg["max_temp"] - cfg["min_temp"])
    return int(cfg["min_duty"] + (cfg["max_duty"] - cfg["min_duty"]) * ratio)


def main():
    cfg = load_config()
    pin = cfg["pin"]

    # Foreground-launch guard.
    # systemd sets INVOCATION_ID for services; if it's absent we were started in
    # the foreground — almost always the WebUI payload runner, which blocks until
    # the payload exits. Our control loop never exits, so running it here would
    # freeze the WebUI/LCD. Instead, hand off to the background service and return
    # immediately. Set RJ_FAN_FOREGROUND=1 to force the blocking loop (manual debug).
    if os.environ.get("INVOCATION_ID") is None and os.environ.get("RJ_FAN_FOREGROUND") != "1":
        started = (
            shutil.which("systemctl") is not None
            and subprocess.call(
                ["systemctl", "start", "raspyjack-fan.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ) == 0
        )
        if started:
            print("[FanControl] Started background service 'raspyjack-fan.service'. "
                  "Fan control is now running in the background — control returned to the UI.")
        else:
            print("[FanControl] Foreground launch detected, but the background service is not available.")
            print("[FanControl] Install it with: sudo bash payloads/utilities/raspyjack_headless_setup.sh")
            print("[FanControl] Not running the blocking loop here (it would freeze the WebUI).")
        return

    print(f"[FanControl] GPIO {pin} | {cfg['min_temp']}°C–{cfg['max_temp']}°C | duty {cfg['min_duty']}–{cfg['max_duty']}%")

    if GPIO is None:
        print("[FanControl] RPi.GPIO not available — simulation mode.")
        while True:
            temp = get_cpu_temp()
            duty = calculate_duty(temp, cfg)
            print(f"[SIM] {temp:.1f}°C → {duty}%")
            time.sleep(UPDATE_INTERVAL)
        return

    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    except Exception as e:
        print(f"[FanControl] WARNING: Failed to set up GPIO {pin}: {e}")
        print("[FanControl] Running in no-hardware mode (no fan connected or permission issue).")
        while True:
            temp = get_cpu_temp()
            duty = calculate_duty(temp, cfg)
            print(f"[NO-HW] {temp:.1f}°C → would set {duty}%")
            time.sleep(UPDATE_INTERVAL)
        return

    pwm = GPIO.PWM(pin, 25000)
    pwm_running = False

    try:
        while True:
            temp = get_cpu_temp()
            duty = calculate_duty(temp, cfg)

            if duty == 0:
                if pwm_running:
                    pwm.stop()
                    pwm_running = False
                GPIO.output(pin, GPIO.LOW)
            else:
                if not pwm_running:
                    pwm.start(duty)
                    pwm_running = True
                else:
                    pwm.ChangeDutyCycle(duty)

            print(f"[Fan] {temp:.1f}°C → {'OFF' if duty == 0 else str(duty)+'%'}")
            time.sleep(UPDATE_INTERVAL)
    except KeyboardInterrupt:
        print("\n[FanControl] Stopped.")
    finally:
        try:
            if pwm_running:
                pwm.stop()
            GPIO.output(pin, GPIO.LOW)
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
