# winks

iPhone notifications on Windows, forwarded via Bluetooth LE ANCS.

Please note: I built this with AI simply as a proof of concept. It works, but it's not the most polished. You might want to look into Microsoft Phone Link as an alternative. For Linux, I came across [ancs4linux](https://github.com/pzmarzly/ancs4linux), which might be worth checking out.
<!-- DO NOT REMOVE THE ABOVE LINE -->

## Requirements

- Windows 10/11
- iPhone paired via **Windows Settings › Bluetooth** (classic BT — do this first)
- [uv](https://docs.astral.sh/uv/)

## Install

```
uv tool install git+https://github.com/slashtechno/winks
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
| `winks enable` | Add to Windows startup (registry) |
| `winks disable` | Remove from Windows startup |
| `winks menu-add` | Add to Start Menu (runs without a console) |
| `winks menu-remove` | Remove from Start Menu |
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
