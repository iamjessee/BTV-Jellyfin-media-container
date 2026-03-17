#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


FORWARDED_PORT_FILE = os.getenv("GLUETUN_FORWARDED_PORT_FILE", "/tmp/gluetun/forwarded_port")
QBT_URL = os.getenv("QBT_URL", "http://gluetun:8080").rstrip("/")
QBT_USERNAME = os.getenv("QBT_USERNAME", "admin")
QBT_PASSWORD = os.getenv("QBT_PASSWORD", "")
SYNC_INTERVAL = int(os.getenv("QBT_PORT_SYNC_INTERVAL", "30"))
LOGIN_PATH = "/api/v2/auth/login"
PREFERENCES_PATH = "/api/v2/app/setPreferences"


def log(message: str) -> None:
    print(f"[qbt-port-sync] {message}", flush=True)


def build_opener() -> urllib.request.OpenerDirector:
    cookie_jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def wait_for_port_file() -> int:
    while True:
        try:
            with open(FORWARDED_PORT_FILE, "r", encoding="ascii") as port_file:
                content = port_file.read().strip()
            if content.isdigit():
                return int(content)
            log(f"ignoring invalid forwarded port value: {content!r}")
        except FileNotFoundError:
            log(f"waiting for Gluetun forwarded port file at {FORWARDED_PORT_FILE}")
        except OSError as exc:
            log(f"could not read forwarded port file: {exc}")
        time.sleep(SYNC_INTERVAL)


def qb_login(opener: urllib.request.OpenerDirector) -> bool:
    payload = urllib.parse.urlencode(
        {"username": QBT_USERNAME, "password": QBT_PASSWORD}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{QBT_URL}{LOGIN_PATH}",
        data=payload,
        method="POST",
    )
    try:
        with opener.open(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
        if body == "Ok.":
            return True
        log(f"unexpected qBittorrent login response: {body!r}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        log(f"qBittorrent login failed with HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        log(f"could not reach qBittorrent login endpoint: {exc}")
    return False


def set_qb_port(opener: urllib.request.OpenerDirector, port: int) -> bool:
    preferences = json.dumps({"listen_port": port, "upnp": False}, separators=(",", ":"))
    payload = urllib.parse.urlencode({"json": preferences}).encode("utf-8")
    request = urllib.request.Request(
        f"{QBT_URL}{PREFERENCES_PATH}",
        data=payload,
        method="POST",
    )
    try:
        with opener.open(request, timeout=15):
            pass
        return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        log(f"failed to update qBittorrent port with HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        log(f"could not reach qBittorrent preferences endpoint: {exc}")
    return False


def main() -> int:
    if not QBT_PASSWORD:
        log("QBT_PASSWORD is not set. Add it to your .env before starting this service.")
        return 1

    last_applied_port = None
    while True:
        forwarded_port = wait_for_port_file()
        if forwarded_port == last_applied_port:
            time.sleep(SYNC_INTERVAL)
            continue

        opener = build_opener()
        if not qb_login(opener):
            time.sleep(SYNC_INTERVAL)
            continue

        if set_qb_port(opener, forwarded_port):
            last_applied_port = forwarded_port
            log(f"updated qBittorrent listen port to {forwarded_port}")

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
