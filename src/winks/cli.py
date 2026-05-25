from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime, timezone

import click

from winks.listener import ANCSNotFoundError, Listener
from winks.listener import probe as _ble_probe
from winks.platform import (
    CONFIG_PATH,
    Config,
    Tray,
    add_startup_task,
    remove_startup_task,
    show_toast,
    startup_task_exists,
)
from winks.protocol import DataSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """Winks — iPhone notifications on Windows via ANCS."""


@cli.command()
def setup() -> None:
    """First-time setup: probe for device, configure startup."""
    click.echo("Watch your iPhone — a pairing prompt may appear.")
    click.echo("Scanning for your iPhone ...")
    address = asyncio.run(_ble_probe())
    if not address:
        click.echo("No ANCS device found. Make sure your iPhone is paired and nearby.")
        raise SystemExit(1)
    cfg = Config(
        device_address=address,
        probed_at=datetime.now(timezone.utc).isoformat(),
    )
    cfg.save()
    click.echo(f"Device found: {address}")

    if click.confirm("Run winks automatically on login?", default=True):
        add_startup_task()
        click.echo("Startup task created.")

    if click.confirm("Start winks now?", default=True):
        _run(cfg)


@cli.command(name="run")
def run_cmd() -> None:
    """Start the listener and tray icon."""
    cfg = Config.load()
    if not cfg.device_address:
        click.echo("No device configured. Run: winks setup")
        raise SystemExit(1)
    _run(cfg)


@cli.command(name="probe")
def probe_cmd() -> None:
    """Re-probe for iPhone and update saved address."""
    click.echo("Watch your iPhone — a pairing prompt may appear.")
    click.echo("Scanning ...")
    address = asyncio.run(_ble_probe())
    if not address:
        click.echo("No ANCS device found.")
        raise SystemExit(1)
    cfg = Config.load()
    cfg.device_address = address
    cfg.probed_at = datetime.now(timezone.utc).isoformat()
    cfg.save()
    click.echo(f"Updated address: {address}")


@cli.command()
def enable() -> None:
    """Add winks to Windows startup."""
    add_startup_task()
    click.echo("Startup task created.")


@cli.command()
def disable() -> None:
    """Remove winks from Windows startup."""
    remove_startup_task()
    click.echo("Startup task removed.")


@cli.command()
def status() -> None:
    """Show current configuration."""
    cfg = Config.load()
    click.echo(f"Config:   {CONFIG_PATH}")
    click.echo(f"Device:   {cfg.device_address or '(not set)'}")
    click.echo(f"Probed:   {cfg.probed_at or '(never)'}")
    click.echo(f"Startup:  {'yes' if startup_task_exists() else 'no'}")


@cli.command()
def uninstall() -> None:
    """Remove startup task, config, and uninstall winks."""
    click.confirm("This will remove all winks data. Continue?", abort=True)
    remove_startup_task()
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
        click.echo(f"Deleted {CONFIG_PATH}")
    subprocess.run(["uv", "tool", "uninstall", "winks"])


def _make_on_notification(tray: Tray) -> Callable[[DataSource, str], None]:
    def on_notification(ds: DataSource, category: str) -> None:
        show_toast(category, ds.title, ds.subtitle, ds.message)

    return on_notification


def _run(cfg: Config) -> None:
    tray = Tray()
    listener = Listener(
        address=cfg.device_address,  # type: ignore[arg-type]
        on_notification=_make_on_notification(tray),
        on_connect=lambda addr: tray.update_status(True, addr),
        on_disconnect=lambda: tray.update_status(False, None),
    )

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def reprobe() -> None:
        log.info("Watch your iPhone — a pairing prompt may appear.")
        log.info("Probing for device ...")
        address = await _ble_probe()
        if address:
            cfg.device_address = address
            cfg.probed_at = datetime.now(timezone.utc).isoformat()
            cfg.save()
            listener.set_address(address)
            log.info("Updated address: %s", address)
        else:
            log.warning("Probe found no ANCS device.")

    def _quit() -> None:
        asyncio.run_coroutine_threadsafe(listener.pause(), loop).result(timeout=3)
        loop.stop()

    def _sigint(_sig: int, _frame: object) -> None:
        _quit()
        if tray._icon:
            tray._icon.stop()

    signal.signal(signal.SIGINT, _sigint)

    asyncio.run_coroutine_threadsafe(listener.run_forever(), loop)
    tray.run(
        on_probe=lambda: asyncio.run_coroutine_threadsafe(reprobe(), loop),
        on_disconnect=lambda: asyncio.run_coroutine_threadsafe(listener.pause(), loop),
        on_reconnect=lambda: asyncio.run_coroutine_threadsafe(listener.resume(), loop),
        on_quit=_quit,
    )
