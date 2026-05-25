"""Single-file prototype — reference only. Use src/winks/ for the real package."""
import argparse, asyncio, json, logging, re, struct, subprocess, sys
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from winotify import Notification, audio

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

APPLE_MFR_ID       = 0x004C
ANCS_SERVICE_UUID  = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIF_SOURCE_UUID  = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
CONTROL_POINT_UUID = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DATA_SOURCE_UUID   = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"

ATTR_TITLE, ATTR_SUBTITLE, ATTR_MESSAGE = 1, 2, 3
EVENT_ADDED, EVENT_REMOVED = 0, 2
CATEGORIES = {
    0: "Other", 1: "Incoming Call", 2: "Missed Call", 3: "Voicemail",
    4: "Social", 5: "Schedule", 6: "Email", 7: "News",
    8: "Health & Fitness", 9: "Business", 10: "Location", 11: "Entertainment",
}

def parse_notification_source(data: bytearray) -> dict:
    if len(data) < 8:
        raise ValueError(f"Too short ({len(data)} bytes)")
    event_id, flags, cat_id, _ = struct.unpack_from("<BBBB", data, 0)
    uid = struct.unpack_from("<I", data, 4)[0]
    return {"uid": uid, "event_id": event_id, "flags": flags,
            "category": CATEGORIES.get(cat_id, f"Cat({cat_id})")}

def build_get_attributes_cmd(uid: int) -> bytes:
    return struct.pack("<BIBHBHBH",
        0x00, uid, ATTR_TITLE, 128, ATTR_SUBTITLE, 64, ATTR_MESSAGE, 256)

def parse_data_source(data: bytearray) -> dict | None:
    if len(data) < 5 or data[0] != 0x00:
        return None
    uid = struct.unpack_from("<I", data, 1)[0]
    attrs, offset = {}, 5
    while offset + 3 <= len(data):
        attr_id  = data[offset]
        attr_len = struct.unpack_from("<H", data, offset + 1)[0]
        offset  += 3
        if offset + attr_len > len(data):
            break
        attrs[attr_id] = data[offset:offset+attr_len].decode("utf-8", errors="replace").strip("\x00")
        offset += attr_len
    return {"uid": uid, "attrs": attrs}

def show_toast(category: str, title: str, subtitle: str, message: str) -> None:
    heading   = title or subtitle or "(no title)"
    body_bits = [p for p in ([subtitle] if title and subtitle else []) + [message] if p]
    body      = " — ".join(body_bits) or "(no content)"
    toast = Notification(app_id="iPhone Notifications",
                         title=f"[{category}] {heading}",
                         msg=body, duration="short")
    toast.set_audio(audio.Default, loop=False)
    toast.show()

def _powershell(cmd: str, timeout: int = 15) -> str | None:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception as e:
        log.debug(f"PowerShell: {e}")
        return None

def _extract_address(instance_id: str) -> str | None:
    m = re.search(r'_([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})$', instance_id)
    if m:
        return m.group(1).upper()
    m = re.search(r'(?:_|DEV_)([0-9a-fA-F]{12})(?:\\|$)', instance_id, re.IGNORECASE)
    if m:
        h = m.group(1)
        return ":".join(h[i:i+2] for i in range(0, 12, 2)).upper()
    return None

def get_all_bt_devices() -> list[dict]:
    out = _powershell(
        "Get-PnpDevice | "
        "Where-Object { $_.InstanceId -like 'BTHLEDevice*' -or $_.InstanceId -like 'BTHENUM*' } | "
        "Select-Object FriendlyName, InstanceId, Status | ConvertTo-Json -Compress")
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    results, seen = [], set()
    for dev in data:
        name = (dev.get("FriendlyName") or "").strip()
        iid  = (dev.get("InstanceId")   or "").strip()
        stat = (dev.get("Status")        or "").strip()
        addr = _extract_address(iid)
        kind = "BLE" if iid.startswith("BTHLEDevice") else "Classic BT"
        if addr and addr not in seen:
            seen.add(addr)
            results.append({"name": name, "address": addr, "status": stat, "kind": kind})
    return results

async def scan_all(timeout: float = 10.0) -> dict:
    return await BleakScanner.discover(timeout=timeout, return_adv=True)

async def probe_for_ancs(candidates: list) -> str | None:
    for device, _ in candidates:
        log.info(f"Probing {device.address} ({device.name or 'no name'}) ...")
        try:
            async with BleakClient(device.address, pair=True, timeout=10.0) as client:
                if client.services.get_service(ANCS_SERVICE_UUID):
                    log.info(f"✓ ANCS found at {device.address}")
                    return device.address
        except Exception as e:
            log.debug(f"Could not connect to {device.address}: {e}")
    return None

async def do_probe() -> str | None:
    found = await scan_all(timeout=12.0)
    apple = [(d, adv) for _, (d, adv) in found.items()
             if APPLE_MFR_ID in (adv.manufacturer_data or {})]
    if not apple:
        log.error("No Apple BLE devices found. Keep iPhone nearby with Bluetooth on.")
        return None
    log.info(f"Found {len(apple)} Apple device(s). Probing for ANCS ...")
    return await probe_for_ancs(apple)

async def auto_find_address() -> str | None:
    found = await scan_all(timeout=12.0)
    for _, (device, adv) in found.items():
        if ANCS_SERVICE_UUID in [u.lower() for u in (adv.service_uuids or [])]:
            return device.address
    ble_paired = [d for d in get_all_bt_devices() if d["kind"] == "BLE"]
    return ble_paired[0]["address"] if len(ble_paired) == 1 else None

class ANCSListener:
    def __init__(self) -> None:
        self._pending: dict[int, dict] = {}
        self._client: BleakClient | None = None

    async def run(self, address: str) -> None:
        log.info(f"Connecting to {address} ...")
        async with BleakClient(address, pair=True) as client:
            self._client = client
            if not client.services.get_service(ANCS_SERVICE_UUID):
                log.error("ANCS not found. Run --probe, or re-pair your iPhone.")
                return
            await client.start_notify(DATA_SOURCE_UUID,  self._on_data)
            await client.start_notify(NOTIF_SOURCE_UUID, self._on_notif)
            log.info("Ready.")
            while client.is_connected:
                await asyncio.sleep(1)

    def _on_notif(self, _s, data: bytearray) -> None:
        try:
            n = parse_notification_source(data)
        except ValueError:
            return
        if n["event_id"] == EVENT_REMOVED:
            self._pending.pop(n["uid"], None)
            return
        if n["event_id"] != EVENT_ADDED:
            return
        self._pending[n["uid"]] = n
        asyncio.ensure_future(self._fetch(n["uid"]))

    async def _fetch(self, uid: int) -> None:
        if not self._client or not self._client.is_connected:
            return
        try:
            await self._client.write_gatt_char(
                CONTROL_POINT_UUID, build_get_attributes_cmd(uid), response=True)
        except Exception as e:
            log.debug(f"Attr fetch failed uid={uid}: {e}")
            self._pending.pop(uid, None)

    def _on_data(self, _s, data: bytearray) -> None:
        parsed = parse_data_source(data)
        if not parsed:
            return
        n = self._pending.pop(parsed["uid"], {})
        a = parsed["attrs"]
        show_toast(n.get("category", "Notification"),
                   a.get(ATTR_TITLE, ""), a.get(ATTR_SUBTITLE, ""), a.get(ATTR_MESSAGE, ""))

async def async_main(args: argparse.Namespace) -> None:
    if args.list:
        found = await scan_all(timeout=10.0)
        print("\n── BLE scan ──────────────────────────────────────────")
        for _, (d, adv) in sorted(found.items(), key=lambda x: x[1][0].name or "~"):
            apple = " [Apple]" if APPLE_MFR_ID in (adv.manufacturer_data or {}) else ""
            ancs  = " ← ANCS"  if ANCS_SERVICE_UUID in [u.lower() for u in (adv.service_uuids or [])] else ""
            print(f"  {d.address}  {d.name or '(no name)'}{apple}{ancs}")
        print("\n── Windows paired Bluetooth ──────────────────────────")
        for dev in get_all_bt_devices():
            print(f"  {dev['address']}  {dev['name'] or '(no name)'}  [{dev['kind']}]")
        return

    if args.probe:
        address = await do_probe()
        if not address:
            sys.exit(1)
    elif args.address:
        address = args.address
    else:
        address = await auto_find_address()
        if not address:
            log.error("Could not find iPhone. Run --list then --probe.")
            sys.exit(1)

    listener = ANCSListener()
    while True:
        try:
            await listener.run(address)
        except Exception as e:
            log.error(f"Connection error: {e}")
        log.info("Reconnecting in 5s ...")
        await asyncio.sleep(5)

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--address", "-a")
    p.add_argument("--list",  action="store_true")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        log.info("Stopped.")

if __name__ == "__main__":
    main()
