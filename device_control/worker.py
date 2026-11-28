"""Background worker: turns the deck heaters off when a guest's auto-off is due.

The deadlines live in the app's state (:mod:`device_control.appliances`), so
one that passed while the app was down is acted on shortly after it starts.
"""
import logging
import os
import sys
import threading

from . import appliances

log = logging.getLogger(__name__)

TICK = 30
#: Let the server finish starting before the first Home Assistant call.
FIRST_DELAY = 20

_wake = threading.Event()
_started = False
_start_lock = threading.Lock()


def _is_runtime(path):
    """``python -m bdh_sdk.runtime`` (the app's container) runs ``bdh_sdk/runtime/__main__.py``."""
    parts = path.replace("\\", "/").split("/")
    return parts[-3:] == ["bdh_sdk", "runtime", "__main__.py"]


def should_start(argv=None):
    """Start only in the server process (the app's container, Daphne, or runserver's reloaded child)."""
    if os.environ.get("BDH_DEVICE_CONTROL_WORKER", "").lower() in ("0", "false", "off", "no"):
        return False
    argv = sys.argv if argv is None else argv
    if argv and _is_runtime(argv[0]):
        return True
    prog = os.path.basename(argv[0]) if argv else ""
    if "daphne" in prog:
        return True
    if len(argv) > 1 and prog in ("manage.py", "django-admin", "__main__.py") and argv[1] == "runserver":
        return os.environ.get("RUN_MAIN") == "true" or "--noreload" in argv
    return False


def tick(now=None):
    try:
        return appliances.enforce_auto_off(now)
    except Exception:
        log.exception("auto-off check failed")
        return []


def _loop():
    _wake.wait(FIRST_DELAY)
    while True:
        _wake.clear()
        tick()
        _wake.wait(TICK)


def start():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="device-control-worker", daemon=True).start()
