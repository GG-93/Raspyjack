"""
Shared whitelist helper for RaspyJack attack payloads.

Reads the raspygotchi whitelist config and provides a simple API
for any payload to check whether a BSSID or SSID should be skipped.

Usage in a payload:
    from payloads._whitelist_helper import load_whitelist, is_whitelisted

    wl_macs, wl_ssids = load_whitelist()

    # In your scan/attack loop:
    if is_whitelisted(bssid=target_bssid, macs=wl_macs, ssids=wl_ssids):
        continue  # skip this target

Config file: /root/Raspyjack/loot/Pwnagotchi/config.json
Format:
    {
        "whitelist_macs": ["AA:BB:CC:DD:EE:FF"],
        "whitelist_ssids": ["MyNetwork"],
        "deauth_enabled": true,
        "webhook_url": ""
    }
"""

import os
import json

WHITELIST_CONFIG = '/root/Raspyjack/loot/Pwnagotchi/config.json'


def load_whitelist(config_path=None):
    """Load whitelist MACs and SSIDs from raspygotchi config.

    Returns:
        (set, set): Uppercase MAC set, SSID string set.
        Both empty if config missing or unreadable.
    """
    path = config_path or WHITELIST_CONFIG
    macs, ssids = set(), set()
    try:
        if os.path.isfile(path):
            with open(path, 'r') as f:
                d = json.load(f)
            macs = set(m.upper() for m in d.get('whitelist_macs', []))
            ssids = set(d.get('whitelist_ssids', []))
    except Exception:
        pass
    return macs, ssids


def is_whitelisted(bssid=None, ssid=None, macs=None, ssids=None):
    """Check if a BSSID or SSID is whitelisted.

    Args:
        bssid: MAC address string (any case)
        ssid: Network name string
        macs: Pre-loaded MAC set from load_whitelist() (optional)
        ssids: Pre-loaded SSID set from load_whitelist() (optional)

    If macs/ssids not provided, loads from config on each call.
    For performance in loops, pre-load once with load_whitelist().
    """
    if macs is None or ssids is None:
        macs, ssids = load_whitelist()
    if bssid and bssid.upper() in macs:
        return True
    if ssid and ssid in ssids:
        return True
    return False
