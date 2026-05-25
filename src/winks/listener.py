from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from winks.protocol import (
    ANCS_SERVICE_UUID,
    APPLE_MFR_ID,
    CONTROL_POINT_UUID,
    DATA_SOURCE_UUID,
    NOTIF_SOURCE_UUID,
    DataSource,
    build_attr_request,
    parse_data_source,
    parse_notification_source,
)

log = logging.getLogger(__name__)

_EVENT_ADDED = 0
_EVENT_REMOVED = 2
_RECONNECT_DELAY = 10.0


class ANCSNotFoundError(Exception):
    """Connected successfully but ANCS service not visible.
    Means no BLE bond exists — user needs to re-pair."""


class Listener:
    def __init__(
        self,
        address: str,
        on_notification: Callable[[DataSource, str], None],
        on_connect: Callable[[str], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        self._address = address
        self._on_notification = on_notification
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._pending: dict[int, str] = {}  # uid -> category
        self._client: BleakClient | None = None
        self._running = asyncio.Event()
        self._running.set()  # start unpaused

    def set_address(self, address: str) -> None:
        self._address = address

    async def pause(self) -> None:
        """Disconnect and halt the reconnect loop until resume() is called."""
        self._running.clear()
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    async def resume(self) -> None:
        """Resume the reconnect loop after pause()."""
        self._running.set()

    async def run_forever(self) -> None:
        while True:
            await self._running.wait()
            try:
                await self._connect_and_listen()
            except ANCSNotFoundError:
                raise
            except Exception as e:
                log.error("Connection error: %s", e)
                if not self._running.is_set():
                    continue
                log.info("Reconnecting in %.0fs ...", _RECONNECT_DELAY)
                await asyncio.sleep(_RECONNECT_DELAY)
            else:
                # Clean return: ServicesChanged disconnect or normal drop.
                # Retry quickly — no point waiting 10s.
                if self._running.is_set():
                    await asyncio.sleep(1.0)

    async def _connect_and_listen(self) -> None:
        log.info("Connecting to %s ...", self._address)
        _reached_ready = False
        try:
            async with BleakClient(self._address, pair=True) as client:
                self._client = client
                # iOS fires ServicesChanged after upgrading to an encrypted ANCS
                # session. The WinRT GattSession closes while it's handled, which
                # cancels any in-flight GATT operations. Wait for it to settle
                # before touching GATT.
                await asyncio.sleep(3.0)
                if not client.is_connected:
                    return
                if not client.services.get_service(ANCS_SERVICE_UUID):
                    raise ANCSNotFoundError(
                        f"ANCS not found on {self._address}. Re-pair your iPhone."
                    )
                await client.start_notify(DATA_SOURCE_UUID, self._on_data)
                await client.start_notify(NOTIF_SOURCE_UUID, self._on_notif_source)
                log.info("Ready — listening for notifications.")
                _reached_ready = True
                if self._on_connect:
                    self._on_connect(self._address)
                while client.is_connected:
                    await asyncio.sleep(1)
        finally:
            self._client = None
            if _reached_ready and self._on_disconnect:
                self._on_disconnect()

    def _on_notif_source(self, _sender: object, data: bytearray) -> None:
        notif = parse_notification_source(data)
        if notif is None:
            return
        if notif.event_id == _EVENT_REMOVED:
            self._pending.pop(notif.uid, None)
            return
        if notif.event_id != _EVENT_ADDED:
            return
        self._pending[notif.uid] = notif.category
        asyncio.ensure_future(self._fetch_attrs(notif.uid))

    async def _fetch_attrs(self, uid: int) -> None:
        if not self._client or not self._client.is_connected:
            return
        try:
            await self._client.write_gatt_char(
                CONTROL_POINT_UUID, build_attr_request(uid), response=True
            )
        except Exception as e:
            log.debug("Attr fetch failed uid=%d: %s", uid, e)
            self._pending.pop(uid, None)

    def _on_data(self, _sender: object, data: bytearray) -> None:
        ds = parse_data_source(data)
        if ds is None:
            return
        category = self._pending.pop(ds.uid, "Notification")
        self._on_notification(ds, category)


async def scan_all(
    timeout: float = 12.0,
) -> dict[str, tuple[BLEDevice, AdvertisementData]]:
    return await BleakScanner.discover(timeout=timeout, return_adv=True)


async def probe() -> str | None:
    log.info("Scanning for Apple BLE devices ...")
    found = await scan_all()
    apple = [
        (device, adv)
        for _, (device, adv) in found.items()
        if APPLE_MFR_ID in (adv.manufacturer_data or {})
    ]
    if not apple:
        log.error("No Apple BLE devices found. Keep iPhone nearby with Bluetooth on.")
        return None
    log.info("Found %d Apple device(s). Probing for ANCS ...", len(apple))
    for device, _ in apple:
        log.info("Probing %s (%s) ...", device.address, device.name or "no name")
        try:
            async with BleakClient(device.address, pair=True, timeout=10.0) as client:
                if client.services.get_service(ANCS_SERVICE_UUID):
                    log.info("ANCS found at %s", device.address)
                    return device.address
        except Exception as e:
            log.debug("Could not connect to %s: %s", device.address, e)
    return None
