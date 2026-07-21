# Fork Differences — Headless Portable Edition

This fork ([GG-93/Raspyjack](https://github.com/GG-93/Raspyjack)) adds a **headless portable operation layer** on top of the upstream project ([7h30th3r0n3/Raspyjack](https://github.com/7h30th3r0n3/Raspyjack)).

All upstream functionality is preserved and unchanged. Nothing has been removed or modified from the original codebase.

---

## What This Fork Adds

### 1. Config-Driven Setup (`config/headless.json`)

A single JSON config file holds all personal details (WiFi credentials, hostname, Tailscale key, fan settings). The file is gitignored — no personal data is ever committed.

`config/headless.json.example` ships as a template with placeholder values.

### 2. Headless Setup Script (`payloads/utilities/raspyjack_headless_setup.sh`)

Reads `headless.json` and configures the Pi for headless operation:
- Connects to any WiFi network (phone hotspot, travel router, microcontroller AP, etc.)
- Sets hostname
- Optionally brings up Tailscale for remote access
- Can install itself as a systemd service for automatic boot configuration

### 3. First-Time Setup Helper (`scripts/configure_headless.sh`)

Interactive script that walks a new user through creating their `headless.json`. Prompts for WiFi SSID/password, hostname, optional Tailscale key, and optional fan control settings.

### 4. Dynamic Fan Control (`payloads/hardware/dynamic_fan_control.py` + systemd service)

PWM fan speed controller driven by CPU temperature. Reads settings from `headless.json` (`fan_control` section). Uses GPIO 18 by default — no conflict with HAT button pins (5, 6, 13, 16, 19, 20, 21, 26). Runs as a **background systemd service** (`config/systemd/raspyjack-fan.service`), auto-installed by the headless setup when fan control is enabled, so it never blocks the WebUI. A foreground-launch guard makes the payload hand off to the service instead of freezing the UI. Manual override payloads — `fan_on.py`, `fan_off.py`, `fan_auto.py` — force 100%, force off, or restore automatic control via a tmpfs override file.

### 5. Clean-Shutdown Button (`scripts/shutdown_button.py` + systemd service)

Momentary button on GPIO 17 (pin 11) to GND (pin 9); hold ~2s for a clean shutdown. Polls the pin rather than using `GPIO.wait_for_edge()` (which is broken on current Raspberry Pi OS / Bookworm). Installed via `config/systemd/raspyjack-shutdown.service`.

### 6. Portable Headless Documentation (`docs/PORTABLE_HEADLESS_SETUP.md`)

Explains the two connection methods (WiFi client with static IP + mDNS, optional Tailscale), the handoff process for giving clones to others, and how to strip personal data before sharing.

---

## Design Principles

- **Pi is a WiFi client only** — it connects to an existing hotspot. It never creates its own access point. Upstream already disables `hostapd` by default; this fork keeps that decision.
- **No internet required for operation** — the WebUI and all payloads work on a local network with no internet access. Tailscale is strictly optional.
- **Nothing personal in the repo** — `headless.json` is gitignored. The example file ships with placeholder values.
- **Minimal upstream footprint** — most changes are new files (headless layer, fan/button services, docs). A few upstream files are lightly modified (e.g. `README.md`, `.gitignore`, and `wardriving.py` to protect the WebUI management interface), which keeps merges with upstream small.

---

## Compatibility

Tested on Raspberry Pi (aarch64, Debian 13 Trixie). The headless layer is shell + Python with no new dependencies beyond what the original installer already provides (`nmcli`, `python3`, optionally `jq`).

---

## Potential Upstream Contribution

The following pieces may be useful to the upstream project:

| Component | Notes |
|---|---|
| `config/headless.json` system | Enables SD card handoff without re-imaging |
| `scripts/configure_headless.sh` | First-time setup UX for new users |
| `payloads/hardware/dynamic_fan_control.py` | Useful for any headless/fanless Pi build |
| `.gitignore` additions | Prevents accidental credential commits |
