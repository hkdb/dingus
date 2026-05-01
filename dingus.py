#!/usr/bin/env python3
"""
dingus: a small DBus listener that plays custom sounds when
notifications fire, matched by the originating application name.

Run directly: python3 dingus.py
Config:       ~/.config/dingus/config.toml (auto-created on first run)
Test:         notify-send -a "Slack" "hello"

Requires: Python 3.11+, python-dbus, PyGObject, AyatanaAppIndicator3, PipeWire (pw-play)
On Debian/Ubuntu:  sudo apt install python3-dbus python3-gi gir1.2-ayatanaappindicator3-0.1 pipewire
On Fedora:         sudo dnf install python3-dbus python3-gobject libayatana-appindicator-gtk3 pipewire
On Arch:           sudo pacman -S python-dbus python-gobject libayatana-appindicator pipewire
"""
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import GLib, Gio, Gtk, GdkPixbuf, AyatanaAppIndicator3 as AppIndicator


__version__ = "0.1.0"
GITHUB_URL = "https://github.com/hkdb/dingus"
LICENSE_TYPE = Gtk.License.MIT_X11


CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    / "dingus"
    / "config.toml"
)

LOG_PATH = (
    Path(os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache"))
    / "dingus"
    / "dingus.log"
)

AUTOSTART_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    / "autostart"
    / "dingus.desktop"
)

AUTOSTART_DESKTOP = """\
[Desktop Entry]
Type=Application
Name=dingus
Comment=Per-app notification sounds
Exec={exec_path}
Icon=dingus
Categories=Utility;AudioVideo;
Terminal=false
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""

SAMPLE_CONFIG = """\
# dingus config

# Fallback sound for apps not listed below. Set to "" to only play
# sounds for explicitly mapped apps.
default_sound = "/usr/share/sounds/freedesktop/stereo/message.oga"

# Minimum milliseconds between sounds. Stops spammy apps from machine-gunning audio.
rate_limit_ms = 1000

# Suppress all sounds when GNOME's Do Not Disturb is on.
respect_dnd = true

# Map notification app_name -> sound file.
# The key must match the 'app_name' arg from org.freedesktop.Notifications.Notify
# OR the 'application_id' arg from org.gtk.Notifications.AddNotification, exactly.
# Tip: run with the script in a terminal and trigger a notification to see the name.
#
# Use `mute = true` to silence an app even if a default_sound is set.
#
# Optionally, map per-category sounds within an app. The category comes from
# the notification's `category` hint (freedesktop spec). Common values:
#   im.received, email.arrived, transfer.complete, network.connected, presence.online
# Resolution order: app+category -> app sound -> default_sound.
[apps]
# "Slack"        = { sound = "~/sounds/slack.oga", categories = { "im.received" = "~/sounds/ding.oga" } }
# "Firefox"      = { sound = "~/sounds/firefox.oga" }
# "notify-send"  = { sound = "/usr/share/sounds/freedesktop/stereo/message.oga" }
# "Thunderbird"  = { mute = true }

# Equivalent expanded form for many categories:
# [apps."Evolution"]
# sound = "~/sounds/evolution.oga"
#
# [apps."Evolution".categories]
# "email.arrived" = "~/sounds/email.oga"
# "im.received"   = "~/sounds/ding.oga"
"""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_file_handler = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=2)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(_file_handler)
log = logging.getLogger("dingus")


def ensure_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(SAMPLE_CONFIG)
        log.info("Created sample config at %s — edit it to add mappings.", CONFIG_PATH)
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def is_dnd_active() -> bool:
    """True if GNOME's Do Not Disturb is on (notification banners suppressed)."""
    try:
        settings = Gio.Settings.new("org.gnome.desktop.notifications")
        return not settings.get_boolean("show-banners")
    except Exception as exc:
        log.debug("Could not read DND state: %s", exc)
        return False


class SoundPlayer:
    def __init__(self):
        self.cmd = shutil.which("pw-play")
        if not self.cmd:
            log.warning("pw-play not found; sound playback will not work")

    def play(self, path: str) -> None:
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            log.warning("Sound file not found: %s", path)
            return
        if not self.cmd:
            return
        try:
            subprocess.Popen(
                [self.cmd, path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            log.warning("Failed to play %s: %s", path, exc)


class NotificationRouter:
    def __init__(self, config: dict):
        self.apps: dict = config.get("apps", {}) or {}
        self.default_sound: str = config.get("default_sound", "") or ""
        try:
            self.rate_limit_ms: int = max(0, int(config.get("rate_limit_ms", 1000)))
        except (ValueError, TypeError):
            self.rate_limit_ms = 1000
            log.warning("Invalid rate_limit_ms in config; defaulting to 1000")
        self.respect_dnd: bool = bool(config.get("respect_dnd", True))
        self.player = SoundPlayer()
        self._last_played_ms: float = 0.0
        self.runtime_muted: bool = False

    def reload(self, config: dict) -> None:
        self.apps = config.get("apps", {}) or {}
        self.default_sound = config.get("default_sound", "") or ""
        self.respect_dnd = bool(config.get("respect_dnd", True))
        try:
            self.rate_limit_ms = max(0, int(config.get("rate_limit_ms", 1000)))
        except (ValueError, TypeError):
            self.rate_limit_ms = 1000
            log.warning("Invalid rate_limit_ms in config; defaulting to 1000")
        log.info("Config reloaded. Mapped apps: %s", list(self.apps.keys()) or "(none)")

    def handle(self, app_name: str, summary: str = "", category: str = "") -> None:
        if not app_name:
            return

        if self.runtime_muted:
            return

        if self.respect_dnd and is_dnd_active():
            log.debug("DND active — suppressing %s", app_name)
            return

        now_ms = time.monotonic() * 1000
        if now_ms - self._last_played_ms < self.rate_limit_ms:
            log.debug("Rate-limited; ignoring %s", app_name)
            return

        entry = self.apps.get(app_name)
        if entry is not None and entry.get("mute"):
            log.debug("App %r is muted; skipping", app_name)
            return

        sound_path = ""
        if entry is not None:
            if category:
                cats = entry.get("categories") or {}
                sound_path = cats.get(category, "")
            if not sound_path:
                sound_path = entry.get("sound", "")
        if not sound_path:
            sound_path = self.default_sound
        if not sound_path:
            log.debug("No sound resolved for %r (category=%r); skipping", app_name, category)
            return

        log.info("Playing %s for %r [%s] (%s)", sound_path, app_name, category or "-", summary[:60])
        self.player.play(sound_path)
        self._last_played_ms = now_ms


class TrayIcon:
    def __init__(self, router: NotificationRouter, log_path: Path, on_quit):
        self.router = router
        self.log_path = log_path
        self.on_quit = on_quit

        self.indicator = AppIndicator.Indicator.new(
            "dingus",
            "dingus",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("dingus")

        self.menu = Gtk.Menu()

        self.mute_item = Gtk.MenuItem(label="Unmute" if router.runtime_muted else "Mute")
        self.mute_item.connect("activate", self._on_mute_toggled)
        self.menu.append(self.mute_item)

        self.autostart_item = Gtk.CheckMenuItem(label="Auto-start")
        self.autostart_item.set_active(AUTOSTART_PATH.exists())
        self.autostart_item.connect("toggled", self._on_autostart_toggled)
        self.menu.append(self.autostart_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", self._open_settings)
        self.menu.append(settings_item)

        logs_item = Gtk.MenuItem(label="Open Logs")
        logs_item.connect("activate", self._open_logs)
        self.menu.append(logs_item)

        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self._show_about)
        self.menu.append(about_item)

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self.on_quit())
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def _on_mute_toggled(self, _item):
        muted = not self.router.runtime_muted
        self.router.runtime_muted = muted
        self.mute_item.set_label("Unmute" if muted else "Mute")
        icon = "dingus-muted" if muted else "dingus"
        self.indicator.set_icon_full(icon, "muted" if muted else "active")
        log.info("Muted" if muted else "Unmuted")

    def _on_autostart_toggled(self, item):
        if item.get_active():
            try:
                AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
                exec_path = shutil.which("dingus") or os.path.realpath(sys.argv[0])
                AUTOSTART_PATH.write_text(AUTOSTART_DESKTOP.format(exec_path=exec_path))
                log.info("Autostart enabled at %s", AUTOSTART_PATH)
            except OSError as exc:
                log.warning("Failed to enable autostart: %s", exc)
            return
        try:
            AUTOSTART_PATH.unlink(missing_ok=True)
            log.info("Autostart disabled")
        except OSError as exc:
            log.warning("Failed to disable autostart: %s", exc)

    def _open_logs(self, *_):
        try:
            subprocess.Popen(["xdg-open", str(self.log_path)])
        except OSError as exc:
            log.warning("Failed to open log file: %s", exc)

    def _open_settings(self, *_):
        try:
            subprocess.Popen(["xdg-open", str(CONFIG_PATH)])
        except OSError as exc:
            log.warning("Failed to open config file: %s", exc)

    def _show_about(self, *_):
        dialog = Gtk.AboutDialog()
        dialog.set_program_name("dingus")
        dialog.set_version(__version__)
        dialog.set_comments("Per-app notification sounds for Linux")
        dialog.set_website(GITHUB_URL)
        dialog.set_website_label(GITHUB_URL)
        dialog.set_copyright(" \n ")
        dialog.set_license_type(LICENSE_TYPE)
        try:
            theme = Gtk.IconTheme.get_default()
            pixbuf = theme.load_icon("dingus", 128, 0)
            dialog.set_logo(pixbuf)
        except GLib.Error:
            pass
        dialog.get_content_area().set_margin_bottom(50)
        dialog.run()
        dialog.destroy()


def make_message_handler(router: NotificationRouter):
    def on_message(_bus, message):
        try:
            iface = message.get_interface()
            member = message.get_member()

            if iface == "org.freedesktop.Notifications" and member == "Notify":
                args = message.get_args_list(byte_arrays=True)
                # Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, timeout)
                app_name = str(args[0]) if len(args) > 0 else ""
                summary = str(args[3]) if len(args) > 3 else ""
                category = ""
                if len(args) > 6 and hasattr(args[6], "get"):
                    cat = args[6].get("category")
                    if cat is not None:
                        category = str(cat)
                router.handle(app_name, summary, category)

            elif iface == "org.gtk.Notifications" and member == "AddNotification":
                args = message.get_args_list(byte_arrays=True)
                # AddNotification(application_id, notification_id, notification_dict)
                app_name = str(args[0]) if len(args) > 0 else ""
                summary = ""
                category = ""
                if len(args) > 2 and hasattr(args[2], "get"):
                    title = args[2].get("title")
                    if title is not None:
                        summary = str(title)
                    cat = args[2].get("category")
                    if cat is not None:
                        category = str(cat)
                router.handle(app_name, summary, category)
        except Exception as exc:
            log.exception("Error handling message: %s", exc)

    return on_message


def main() -> int:
    config = ensure_config()
    router = NotificationRouter(config)

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()

    # Become a DBus monitor — required to receive copies of method calls
    # (regular match rules only deliver signals). After this call, the
    # connection is receive-only; no method calls allowed on it.
    bus_obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
    monitoring = dbus.Interface(bus_obj, "org.freedesktop.DBus.Monitoring")

    rules = [
        "interface='org.freedesktop.Notifications',member='Notify'",
        "interface='org.gtk.Notifications',member='AddNotification'",
    ]
    try:
        monitoring.BecomeMonitor(rules, dbus.UInt32(0))
    except dbus.DBusException as exc:
        log.error("Could not become DBus monitor: %s", exc)
        return 1

    bus.add_message_filter(make_message_handler(router))

    def on_sighup(signum, frame):
        try:
            new_config = ensure_config()
            router.reload(new_config)
        except Exception as exc:
            log.error("Failed to reload config: %s", exc)

    signal.signal(signal.SIGHUP, on_sighup)

    mapped = list(router.apps.keys())
    log.info("Listening. Mapped apps: %s", mapped if mapped else "(none — edit config)")
    log.info("Test with:  notify-send -a \"AppName\" \"hello\"")

    def quit_app():
        log.info("Quitting via tray.")
        Gtk.main_quit()

    TrayIcon(router, LOG_PATH, quit_app)

    try:
        Gtk.main()
    except KeyboardInterrupt:
        log.info("Exiting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
