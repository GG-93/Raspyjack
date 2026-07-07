#!/usr/bin/env python3
"""
RaspyJack WiFi Dongle Tester
============================
Interactive test suite for WiFi dongles, USB ports, adapters, and antennas.
Tests compatibility, stability, range, power, and interference.
Results are saved to a tabulated report in loot/.

BUTTON LAYOUT (WebUI / HAT):
  UP/DOWN    -- Navigate menu
  CENTER/OK  -- Select / Start test
  KEY1       -- Quick re-test current dongle
  KEY2       -- View saved results
  KEY3       -- Back / Exit

USAGE:
  1. Plug in ONE dongle at a time
  2. Select "New Test" and describe your setup (dongle, port, adapter)
  3. Run tests — results auto-save
  4. Swap dongle/port/adapter and repeat
  5. View "Report" for full comparison table

Designed for Pi 4B headless/AP mode. Excludes AP interfaces automatically.
"""

import os
import sys
import json
import time
import subprocess
import threading
import signal
from datetime import datetime
from pathlib import Path

# ── AP-aware interface helper ────────────────────────────────────────────────
def _is_ap_interface(iface):
    try:
        r = subprocess.run(["iw", "dev", iface, "info"],
                           capture_output=True, text=True, timeout=3)
        return "type AP" in r.stdout
    except Exception:
        return False

def _get_test_interfaces():
    """Return list of non-AP wireless interfaces."""
    ifaces = []
    for name in sorted(os.listdir("/sys/class/net")):
        if os.path.exists(f"/sys/class/net/{name}/wireless"):
            if not _is_ap_interface(name):
                ifaces.append(name)
    return ifaces
# ─────────────────────────────────────────────────────────────────────────────

LOOT_DIR = "/root/Raspyjack/loot/dongle_tests"
REPORT_FILE = os.path.join(LOOT_DIR, "dongle_report.json")
REPORT_HTML = os.path.join(LOOT_DIR, "dongle_report.html")

# ── USB port mapping for Pi 4B ───────────────────────────────────────────────
PI4B_USB_MAP = {
    "1-1.1": "Bottom Black (USB 2.0 - left)",
    "1-1.2": "Top Black (USB 2.0 - left)",
    "1-1.3": "Bottom Black (USB 2.0 - right)",
    "1-1.4": "Top Black (USB 2.0 - right)",
    "2-1":   "Top Blue (USB 3.0)",
    "2-2":   "Bottom Blue (USB 3.0)",
}


def run(cmd, timeout=15):
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)


def get_usb_info(iface):
    """Get USB bus/port info for a wireless interface."""
    info = {
        "usb_path": "unknown",
        "usb_port_name": "unknown",
        "usb_speed": "unknown",
        "usb_vendor": "unknown",
        "usb_product": "unknown",
        "usb_id": "unknown",
        "bus_type": "unknown",
    }
    try:
        # Follow symlink to find USB device
        phy_path = os.path.realpath(f"/sys/class/net/{iface}/device")
        # Walk up to find usb device
        p = phy_path
        for _ in range(10):
            speed_file = os.path.join(p, "speed")
            if os.path.exists(speed_file):
                with open(speed_file) as f:
                    speed = f.read().strip()
                info["usb_speed"] = f"{speed} Mbps"
                if int(speed) >= 5000:
                    info["bus_type"] = "USB 3.0"
                elif int(speed) >= 480:
                    info["bus_type"] = "USB 2.0 (Hi-Speed)"
                elif int(speed) >= 12:
                    info["bus_type"] = "USB 1.1 (Full-Speed)"

                # Get bus path from directory name
                dirname = os.path.basename(p)
                info["usb_path"] = dirname
                info["usb_port_name"] = PI4B_USB_MAP.get(dirname, f"Port {dirname}")

                # Vendor/product
                for fname, key in [("idVendor", "usb_vendor"), ("idProduct", "usb_product")]:
                    vf = os.path.join(p, fname)
                    if os.path.exists(vf):
                        with open(vf) as f:
                            info[key] = f.read().strip()

                if info["usb_vendor"] != "unknown":
                    info["usb_id"] = f"{info['usb_vendor']}:{info['usb_product']}"
                break
            p = os.path.dirname(p)
    except Exception:
        pass
    return info


def get_driver_info(iface):
    """Get driver and firmware info."""
    info = {
        "driver": "unknown",
        "firmware": "unknown",
        "phy": "unknown",
        "chipset": "unknown",
        "mac": "unknown",
    }
    try:
        driver_link = f"/sys/class/net/{iface}/device/driver"
        if os.path.exists(driver_link):
            info["driver"] = os.path.basename(os.path.realpath(driver_link))

        # Get phy name
        rc, out, _ = run(["iw", "dev", iface, "info"])
        if rc == 0:
            for line in out.split("\n"):
                if "wiphy" in line:
                    phy_num = line.strip().split()[-1]
                    info["phy"] = f"phy{phy_num}"

        # Get MAC
        mac_file = f"/sys/class/net/{iface}/address"
        if os.path.exists(mac_file):
            with open(mac_file) as f:
                info["mac"] = f.read().strip()

        # Chipset from lsusb
        usb_info = get_usb_info(iface)
        if usb_info["usb_id"] != "unknown":
            rc, out, _ = run(["lsusb", "-d", usb_info["usb_id"]])
            if rc == 0 and out:
                # Extract product name after ID
                parts = out.split(usb_info["usb_id"])
                if len(parts) > 1:
                    info["chipset"] = parts[1].strip()

        # Firmware from dmesg
        rc, out, _ = run(["dmesg"])
        if rc == 0:
            for line in reversed(out.split("\n")):
                if info["driver"] in line and "irmware" in line.lower():
                    # Extract firmware version
                    if "version" in line.lower():
                        info["firmware"] = line.split(info["driver"])[-1].strip()[:60]
                        break
    except Exception:
        pass
    return info


def get_capabilities(iface):
    """Check interface capabilities: monitor mode, packet injection, bands."""
    caps = {
        "monitor_mode": False,
        "packet_injection": False,
        "bands": [],
        "channels_2g": 0,
        "channels_5g": 0,
        "max_tx_power": "unknown",
        "supported_modes": [],
    }
    try:
        # Get phy info
        rc, out, _ = run(["iw", "dev", iface, "info"])
        phy = None
        if rc == 0:
            for line in out.split("\n"):
                if "wiphy" in line:
                    phy = f"phy{line.strip().split()[-1]}"
                if "txpower" in line:
                    caps["max_tx_power"] = line.strip()

        if phy:
            rc, out, _ = run(["iw", "phy", phy, "info"])
            if rc == 0:
                # Check supported modes
                in_modes = False
                for line in out.split("\n"):
                    if "Supported interface modes:" in line:
                        in_modes = True
                        continue
                    if in_modes:
                        if line.strip().startswith("*"):
                            mode = line.strip().lstrip("* ")
                            caps["supported_modes"].append(mode)
                            if "monitor" in mode.lower():
                                caps["monitor_mode"] = True
                        else:
                            in_modes = False

                    # Count channels
                    if "MHz" in line and "[" in line:
                        freq_str = line.strip().split("MHz")[0].strip().split()[-1]
                        try:
                            freq = int(freq_str)
                            if 2400 <= freq <= 2500:
                                caps["channels_2g"] += 1
                                if "2.4 GHz" not in caps["bands"]:
                                    caps["bands"].append("2.4 GHz")
                            elif 5000 <= freq <= 5900:
                                caps["channels_5g"] += 1
                                if "5 GHz" not in caps["bands"]:
                                    caps["bands"].append("5 GHz")
                            elif 5925 <= freq <= 7125:
                                if "6 GHz" not in caps["bands"]:
                                    caps["bands"].append("6 GHz")
                        except ValueError:
                            pass

        # Test packet injection (quick check with aireplay-ng if available)
        rc, _, _ = run(["which", "aireplay-ng"])
        if rc == 0 and caps["monitor_mode"]:
            # We won't actually test injection here - just note capability
            caps["packet_injection"] = True  # Most monitor-capable cards support it

    except Exception:
        pass
    return caps


def test_stability(iface, duration=30):
    """Test USB stability over time. Check for disconnects/errors."""
    result = {
        "duration_seconds": duration,
        "disconnects": 0,
        "errors": [],
        "stable": True,
        "link_drops": 0,
    }

    # Get current dmesg line count for this driver
    driver_info = get_driver_info(iface)
    driver = driver_info["driver"]

    # Clear and monitor dmesg
    start_time = time.time()
    rc, dmesg_before, _ = run(["dmesg"])
    before_lines = len(dmesg_before.split("\n"))

    # Monitor interface state
    checks = 0
    while time.time() - start_time < duration:
        # Check interface still exists
        if not os.path.exists(f"/sys/class/net/{iface}"):
            result["disconnects"] += 1
            result["stable"] = False
            result["errors"].append(f"Interface disappeared at {time.time() - start_time:.1f}s")
            # Wait for it to come back
            time.sleep(2)
            if not os.path.exists(f"/sys/class/net/{iface}"):
                result["errors"].append("Interface did not recover")
                break
            else:
                result["errors"].append("Interface recovered")

        # Check for link state
        try:
            with open(f"/sys/class/net/{iface}/operstate") as f:
                state = f.read().strip()
        except Exception:
            state = "unknown"

        checks += 1
        time.sleep(1)

    # Check dmesg for errors during test
    rc, dmesg_after, _ = run(["dmesg"])
    after_lines = dmesg_after.split("\n")
    new_lines = after_lines[before_lines:]

    for line in new_lines:
        lower = line.lower()
        if any(w in lower for w in ["error", "disconnect", "failed", "timeout", "reset"]):
            if driver.lower() in lower or iface in lower:
                result["errors"].append(line.strip()[-100:])
                if "disconnect" in lower:
                    result["disconnects"] += 1
                    result["stable"] = False

    result["checks_passed"] = checks
    return result


def test_range(iface):
    """Scan for networks and measure signal strengths."""
    result = {
        "networks_found": 0,
        "strongest_signal": None,
        "weakest_signal": None,
        "avg_signal": None,
        "networks": [],
    }

    rc, out, _ = run(["iw", "dev", iface, "scan"], timeout=30)
    if rc != 0:
        result["error"] = "Scan failed"
        return result

    current_bss = None
    current_signal = None
    current_ssid = None
    signals = []

    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("BSS "):
            # Save previous
            if current_bss and current_signal is not None:
                signals.append(current_signal)
                result["networks"].append({
                    "bssid": current_bss[:17],
                    "ssid": current_ssid or "(hidden)",
                    "signal": current_signal,
                })
            current_bss = line.split("(")[0].replace("BSS ", "").strip()
            current_signal = None
            current_ssid = None
        elif "signal:" in line:
            try:
                current_signal = float(line.split("signal:")[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
        elif line.startswith("SSID:"):
            ssid = line.replace("SSID:", "").strip()
            if ssid:
                current_ssid = ssid

    # Don't forget last one
    if current_bss and current_signal is not None:
        signals.append(current_signal)
        result["networks"].append({
            "bssid": current_bss[:17],
            "ssid": current_ssid or "(hidden)",
            "signal": current_signal,
        })

    if signals:
        result["networks_found"] = len(signals)
        result["strongest_signal"] = max(signals)
        result["weakest_signal"] = min(signals)
        result["avg_signal"] = round(sum(signals) / len(signals), 1)
        # Sort by signal
        result["networks"].sort(key=lambda x: x["signal"], reverse=True)
        # Keep top 20 for report
        result["networks"] = result["networks"][:20]

    return result


def test_power(iface):
    """Check TX power and USB power draw indicators."""
    result = {
        "current_tx_power": "unknown",
        "max_tx_power": "unknown",
        "usb_speed_actual": "unknown",
        "usb_speed_expected": "unknown",
    }

    # Current TX power
    rc, out, _ = run(["iw", "dev", iface, "info"])
    if rc == 0:
        for line in out.split("\n"):
            if "txpower" in line:
                result["current_tx_power"] = line.strip()

    # USB speed (actual vs expected)
    usb_info = get_usb_info(iface)
    result["usb_speed_actual"] = usb_info["usb_speed"]
    result["usb_bus_type"] = usb_info["bus_type"]
    result["usb_port"] = usb_info["usb_port_name"]
    result["usb_path"] = usb_info["usb_path"]

    return result


def test_monitor_mode(iface):
    """Test if monitor mode actually works (not just reported as supported)."""
    result = {
        "supported": False,
        "activated": False,
        "reverted": False,
        "error": None,
    }

    # Check support first
    caps = get_capabilities(iface)
    result["supported"] = caps["monitor_mode"]

    if not result["supported"]:
        result["error"] = "Monitor mode not supported by driver"
        return result

    # Try to activate monitor mode
    original_state = None
    try:
        rc, out, _ = run(["iw", "dev", iface, "info"])
        for line in out.split("\n"):
            if "type" in line and "type" == line.strip().split()[0]:
                original_state = line.strip().split()[-1]

        # Bring down, set monitor, bring up
        run(["ip", "link", "set", iface, "down"])
        rc, _, err = run(["iw", "dev", iface, "set", "monitor", "none"])
        if rc == 0:
            run(["ip", "link", "set", iface, "up"])
            time.sleep(1)

            # Verify
            rc, out, _ = run(["iw", "dev", iface, "info"])
            if "type monitor" in out:
                result["activated"] = True
        else:
            result["error"] = err[:100] if err else "Failed to set monitor mode"

    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        # Always revert
        try:
            run(["ip", "link", "set", iface, "down"])
            run(["iw", "dev", iface, "set", "type", "managed"])
            run(["ip", "link", "set", iface, "up"])
            time.sleep(1)
            rc, out, _ = run(["iw", "dev", iface, "info"])
            if "type managed" in out:
                result["reverted"] = True
        except Exception:
            pass

    return result


def load_report():
    """Load existing test results."""
    if os.path.exists(REPORT_FILE):
        try:
            with open(REPORT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"tests": [], "created": datetime.now().isoformat()}


def save_report(report):
    """Save test results."""
    os.makedirs(LOOT_DIR, exist_ok=True)
    report["last_updated"] = datetime.now().isoformat()
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)
    generate_html_report(report)


def generate_html_report(report):
    """Generate a nice HTML report from test data."""
    tests = report.get("tests", [])
    if not tests:
        return

    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RaspyJack Dongle Test Report</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0a0e17;color:#c9d1d9;padding:16px;max-width:1200px;margin:0 auto}
h1{color:#58a6ff;font-size:1.4em;margin-bottom:4px}
.sub{color:#8b949e;font-size:.85em;margin-bottom:20px;border-bottom:1px solid #21262d;padding-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:.8em;margin:12px 0}
th{background:#161b22;color:#8b949e;font-size:.7em;text-transform:uppercase;letter-spacing:.8px;text-align:left;padding:8px;border-bottom:1px solid #30363d;position:sticky;top:0}
td{padding:7px 8px;border-bottom:1px solid #21262d;color:#b1bac4;vertical-align:top}
tr:hover td{background:#1c2129}
.ok{color:#3fb950}.warn{color:#f0883e}.fail{color:#f85149}.info{color:#58a6ff}
.tag{font-size:.7em;padding:2px 6px;border-radius:8px;font-weight:600;white-space:nowrap}
.tag-pass{background:#0d2818;color:#3fb950}.tag-fail{background:#3d1214;color:#f85149}
.tag-warn{background:#3d2508;color:#f0883e}
.section{color:#f0883e;font-size:.7em;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;margin:20px 0 8px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin:8px 0}
.card h3{color:#e6edf3;font-size:.95em;margin-bottom:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px}
pre{background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:10px;font-size:.78em;overflow-x:auto;color:#c9d1d9;font-family:'SF Mono',monospace}
</style></head><body>
<h1>WiFi Dongle Test Report</h1>
<p class="sub">Generated """ + datetime.now().strftime("%Y-%m-%d %H:%M") + f" &bull; {len(tests)} test(s) recorded</p>\n"

    # Summary comparison table
    html += '<p class="section">Comparison Table</p>\n'
    html += '<div style="overflow-x:auto"><table>\n'
    html += '<tr><th>#</th><th>Label</th><th>Chipset</th><th>Driver</th>'
    html += '<th>USB Port</th><th>Bus</th><th>Adapter</th>'
    html += '<th>Stable</th><th>Networks</th><th>Strongest</th><th>Weakest</th>'
    html += '<th>Monitor</th><th>Bands</th><th>TX Power</th></tr>\n'

    for i, t in enumerate(tests):
        label = t.get("label", f"Test {i+1}")
        chip = t.get("driver_info", {}).get("chipset", "?")[:30]
        driver = t.get("driver_info", {}).get("driver", "?")
        port = t.get("power", {}).get("usb_port", "?")
        bus = t.get("power", {}).get("usb_bus_type", "?")
        adapter = t.get("adapter", "direct")
        stable = t.get("stability", {})
        stable_ok = stable.get("stable", False)
        stable_cls = "ok" if stable_ok else "fail"
        stable_tag = "tag-pass" if stable_ok else "tag-fail"
        stable_txt = "PASS" if stable_ok else f"FAIL ({stable.get('disconnects', '?')} drops)"
        rng = t.get("range", {})
        nets = rng.get("networks_found", "?")
        strongest = rng.get("strongest_signal", "?")
        weakest = rng.get("weakest_signal", "?")
        mon = t.get("monitor_mode", {})
        mon_ok = mon.get("activated", False)
        mon_cls = "ok" if mon_ok else ("warn" if mon.get("supported") else "fail")
        mon_txt = "Yes" if mon_ok else ("Supported" if mon.get("supported") else "No")
        caps = t.get("capabilities", {})
        bands = ", ".join(caps.get("bands", []))
        tx = t.get("power", {}).get("current_tx_power", "?")
        if isinstance(tx, str) and "txpower" in tx:
            tx = tx.replace("txpower", "").strip()

        html += f'<tr><td>{i+1}</td><td><strong>{label}</strong></td><td>{chip}</td><td>{driver}</td>'
        html += f'<td>{port}</td><td>{bus}</td><td>{adapter}</td>'
        html += f'<td><span class="tag {stable_tag}">{stable_txt}</span></td>'
        html += f'<td>{nets}</td><td class="{stable_cls}">{strongest}</td><td>{weakest}</td>'
        html += f'<td class="{mon_cls}">{mon_txt}</td><td>{bands}</td><td>{tx}</td></tr>\n'

    html += '</table></div>\n'

    # Detailed cards
    html += '<p class="section">Detailed Results</p>\n<div class="grid">\n'

    for i, t in enumerate(tests):
        label = t.get("label", f"Test {i+1}")
        html += f'<div class="card"><h3>#{i+1}: {label}</h3>\n'
        html += f'<p style="font-size:.8em;color:#8b949e">{t.get("timestamp", "")}</p>\n'

        # Quick stats
        stable = t.get("stability", {})
        rng = t.get("range", {})
        html += '<pre>'
        html += f'Dongle:    {t.get("dongle_name", "?")}\n'
        html += f'Adapter:   {t.get("adapter", "direct")}\n'
        html += f'Antenna:   {t.get("antenna", "stock")}\n'
        html += f'Port:      {t.get("power", {}).get("usb_port", "?")}\n'
        html += f'Bus:       {t.get("power", {}).get("usb_bus_type", "?")}\n'
        html += f'Driver:    {t.get("driver_info", {}).get("driver", "?")}\n'
        html += f'MAC:       {t.get("driver_info", {}).get("mac", "?")}\n'
        html += f'Stable:    {"YES" if stable.get("stable") else "NO"} ({stable.get("duration_seconds", 0)}s test)\n'
        html += f'Drops:     {stable.get("disconnects", 0)}\n'
        html += f'Networks:  {rng.get("networks_found", 0)}\n'
        html += f'Best sig:  {rng.get("strongest_signal", "?")} dBm\n'
        html += f'Worst sig: {rng.get("weakest_signal", "?")} dBm\n'
        html += f'Avg sig:   {rng.get("avg_signal", "?")} dBm\n'
        html += f'Monitor:   {"YES" if t.get("monitor_mode", {}).get("activated") else "NO"}\n'

        errors = stable.get("errors", [])
        if errors:
            html += f'\nErrors ({len(errors)}):\n'
            for e in errors[:5]:
                html += f'  ! {e[:80]}\n'

        html += '</pre></div>\n'

    html += '</div>\n'

    # Raw JSON link
    html += f'<p style="margin-top:20px;font-size:.75em;color:#484f58">Raw data: {REPORT_FILE}</p>\n'
    html += '</body></html>'

    with open(REPORT_HTML, "w") as f:
        f.write(html)


def print_banner():
    print()
    print("=" * 56)
    print("  RaspyJack WiFi Dongle Tester")
    print("  Tests: compatibility, stability, range, power,")
    print("         monitor mode, USB ports, adapters")
    print("=" * 56)
    print()


def prompt_choice(prompt, options):
    """Simple numbered menu for CLI."""
    print(f"\n  {prompt}")
    for i, opt in enumerate(options):
        print(f"    [{i+1}] {opt}")
    while True:
        try:
            raw = input(f"\n  > ").strip()
            if raw.lower() in ("q", "quit", "exit", "back"):
                return None
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except (ValueError, EOFError, KeyboardInterrupt):
            return None
        print("  Invalid choice. Try again or 'q' to go back.")


def prompt_text(prompt, default=""):
    """Get text input with optional default."""
    try:
        suffix = f" [{default}]" if default else ""
        raw = input(f"  {prompt}{suffix}: ").strip()
        return raw if raw else default
    except (EOFError, KeyboardInterrupt):
        return default


def run_full_test(iface, label, dongle_name, adapter, antenna):
    """Run all tests on an interface and return results dict."""
    result = {
        "label": label,
        "interface": iface,
        "dongle_name": dongle_name,
        "adapter": adapter,
        "antenna": antenna,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    steps = [
        ("USB & Power Info", lambda: {**get_usb_info(iface), **test_power(iface)}),
        ("Driver & Chipset", lambda: get_driver_info(iface)),
        ("Capabilities", lambda: get_capabilities(iface)),
        ("Stability (30s)", lambda: test_stability(iface, duration=30)),
        ("Range Scan", lambda: test_range(iface)),
        ("Monitor Mode", lambda: test_monitor_mode(iface)),
    ]

    for step_name, step_fn in steps:
        print(f"\n  [{step_name}] ", end="", flush=True)
        try:
            data = step_fn()
            key = step_name.split("(")[0].strip().lower().replace(" & ", "_").replace(" ", "_")
            if key == "usb_power_info":
                key = "power"
            elif key == "driver_chipset":
                key = "driver_info"
            elif key == "stability_30s":
                key = "stability"
            elif key == "range_scan":
                key = "range"

            result[key] = data

            # Print quick summary
            if "stable" in data:
                status = "PASS" if data["stable"] else f"FAIL ({data.get('disconnects', 0)} disconnects)"
                print(f"{'OK' if data['stable'] else 'FAIL'} - {status}")
            elif "networks_found" in data:
                print(f"OK - {data['networks_found']} networks, best {data.get('strongest_signal', '?')} dBm")
            elif "activated" in data:
                print(f"{'OK' if data['activated'] else 'NO'} - Monitor mode {'works' if data['activated'] else 'failed'}")
            elif "driver" in data:
                print(f"OK - {data.get('driver', '?')} / {data.get('chipset', '?')[:40]}")
            elif "usb_port_name" in data:
                print(f"OK - {data.get('usb_port_name', '?')} ({data.get('bus_type', '?')})")
            else:
                print("OK")
        except Exception as e:
            print(f"ERROR - {e}")
            result[step_name.lower().replace(" ", "_")] = {"error": str(e)}

    return result


def interactive_menu():
    """Main interactive menu for CLI mode."""
    print_banner()

    report = load_report()

    while True:
        ifaces = _get_test_interfaces()

        print(f"\n  Detected interfaces: {', '.join(ifaces) if ifaces else 'NONE'}")
        print(f"  Saved tests: {len(report.get('tests', []))}")

        choice = prompt_choice("What would you like to do?", [
            "New Test (plug in a dongle first)",
            "View Report",
            "Delete All Results",
            "Export Report",
            "Exit",
        ])

        if choice is None or "Exit" in choice:
            break

        elif "New Test" in choice:
            if not ifaces:
                print("\n  No WiFi dongles detected! Plug one in and try again.")
                continue

            if len(ifaces) == 1:
                iface = ifaces[0]
                print(f"\n  Using interface: {iface}")
            else:
                iface = prompt_choice("Select interface:", ifaces)
                if not iface:
                    continue

            # Get test metadata
            print(f"\n  Describe this test setup:")
            dongle_name = prompt_text("Dongle name/model", "unknown")
            adapter = prompt_text("USB adapter type (direct/right-angle/left-angle/extender/hub)", "direct")
            antenna = prompt_text("Antenna (stock/directional/yagi/panel/none)", "stock")

            # Auto-detect some info for the label
            usb_info = get_usb_info(iface)
            port_short = usb_info["usb_port_name"].split("(")[0].strip()
            label = prompt_text("Test label",
                                f"{dongle_name} / {port_short} / {adapter}")

            print(f"\n  Starting tests for: {label}")
            print("  " + "-" * 50)

            result = run_full_test(iface, label, dongle_name, adapter, antenna)

            # Save
            report["tests"].append(result)
            save_report(report)

            print(f"\n  " + "=" * 50)
            print(f"  Test complete! Results saved.")
            print(f"  HTML report: {REPORT_HTML}")

        elif "View Report" in choice:
            tests = report.get("tests", [])
            if not tests:
                print("\n  No tests recorded yet.")
                continue

            print(f"\n  {'#':<4} {'Label':<35} {'Stable':<8} {'Nets':<6} {'Bus':<12}")
            print("  " + "-" * 70)
            for i, t in enumerate(tests):
                label = t.get("label", "?")[:33]
                stable = "YES" if t.get("stability", {}).get("stable", False) else "NO"
                nets = t.get("range", {}).get("networks_found", "?")
                bus = t.get("power", {}).get("usb_bus_type", "?")
                print(f"  {i+1:<4} {label:<35} {stable:<8} {nets:<6} {bus:<12}")

            print(f"\n  Full report: {REPORT_HTML}")

        elif "Delete" in choice:
            confirm = prompt_text("Type 'yes' to delete all results", "no")
            if confirm.lower() == "yes":
                report = {"tests": [], "created": datetime.now().isoformat()}
                save_report(report)
                print("\n  All results deleted.")

        elif "Export" in choice:
            save_report(report)
            print(f"\n  JSON: {REPORT_FILE}")
            print(f"  HTML: {REPORT_HTML}")


# ── RaspyJack payload entry point ────────────────────────────────────────────
def main():
    """Entry point - works both as RaspyJack payload and standalone CLI."""
    os.makedirs(LOOT_DIR, exist_ok=True)

    # Check if running as RaspyJack payload (has display) or CLI
    try:
        interactive_menu()
    except KeyboardInterrupt:
        print("\n\n  Exiting dongle tester.")
    except Exception as e:
        print(f"\n  Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
