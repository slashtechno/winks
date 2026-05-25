# winks

iPhone notifications on Windows, forwarded via Bluetooth LE ANCS.

## Requirements

- Windows 10/11
- iPhone paired via **Windows Settings › Bluetooth** (classic BT — do this first)
- Python 3.11+ / [uv](https://docs.astral.sh/uv/)

## Install

```
uv tool install winks
```

## Setup

```
winks setup
```

This scans for your iPhone, saves its BLE address, and optionally adds a startup task so winks launches on login.

## Commands

| Command | Description |
|---|---|
| `winks setup` | First-time setup |
| `winks run` | Start listener + tray icon |
| `winks probe` | Re-scan for iPhone, update saved address |
| `winks enable` | Add to Windows startup |
| `winks disable` | Remove from Windows startup |
| `winks status` | Show config path, device, startup state |
| `winks uninstall` | Remove all data and uninstall |

## How it works

iOS exposes the **Apple Notification Center Service (ANCS)** over BLE to bonded accessories.
Windows creates a BLE bond as a side effect of classic BT pairing (CTKD).
winks scans for Apple BLE devices, connects to the one with ANCS, and forwards notifications as Windows toasts.

The iPhone's BLE address rotates every ~15 minutes. Run `winks probe` if the connection stops working.

## Troubleshooting

**No device found** — Make sure your iPhone is paired via Windows Settings first. Keep it nearby with Bluetooth on.

**ANCS not found after connecting** — No BLE bond exists. Forget the device in Windows Settings, re-pair, then run `winks probe`.

## License

MIT
