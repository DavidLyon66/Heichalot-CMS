#!/usr/bin/env python3
"""
tailcat.py - small Tailcat transport driver for CharacterIF.

This module deliberately owns Tailcat-specific command lines and process
management.  CharacterIF should deal in peers, messages and API paths rather
than knowing how Tailcat forwards sockets.

Tailcat is optional.  Call available() before enabling online/Tailcat mode.

Public interface:

    available()
    start(port) / start_listener(port)
    stop()
    get_address()
    forward(address, remote_port, ...)
    get_json(address, remote_port, path, ...)
    post_json(address, remote_port, path, payload, ...)
    ping(address, ...)
    run_remote(address, command, ...)
    ssh(address, extra_args=None)

Croc bootstrap is intentionally not implemented here.  Croc is an introduction
mechanism, not the Tailcat transport itself.
"""

from __future__ import annotations

import atexit
import json
import re
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional
from urllib import request


DEFAULT_TIMEOUT = 15

_CHILDREN: list[subprocess.Popen] = []
_LISTENER: Optional[subprocess.Popen] = None
_ADDRESS: Optional[str] = None


def available() -> bool:
    """Return True when the tailcat executable is available."""
    return shutil.which("tailcat") is not None


def _require_tailcat() -> None:
    if not available():
        raise RuntimeError("tailcat is not installed")


def _run(args, *, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
    started = time.time()
    try:
        cp = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "ok": cp.returncode == 0,
            "exit_code": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "elapsed": round(time.time() - started, 3),
            "argv": args,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "elapsed": round(time.time() - started, 3),
            "error": f"timeout after {timeout}s",
            "argv": args,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "elapsed": round(time.time() - started, 3),
            "error": "command not found: tailcat",
            "argv": args,
        }


def ensure_default_key() -> None:
    """Create Tailcat's persistent default server key when needed."""
    _require_tailcat()

    listing = _run(["tailcat", "genkey", "--list"], timeout=5)
    if listing["ok"] and "default" in listing.get("stdout", ""):
        return

    result = _run(["tailcat", "genkey", "--key=default"], timeout=10)
    if not result["ok"]:
        text = (result.get("stderr") or "") + (result.get("stdout") or "")
        if "exist" not in text.lower():
            raise RuntimeError(
                "could not create Tailcat default key: " + text.strip()
            )


def _extract_address(line: str) -> Optional[str]:
    line = line.strip()
    if not line:
        return None

    try:
        obj = json.loads(line)
        for key in ("listenAddr", "listen_addr", "address", "addr"):
            value = obj.get(key)
            if isinstance(value, str) and value:
                return value
    except Exception:
        pass

    match = re.search(r"(tc:[^\s]+)", line)
    if match:
        return match.group(1)

    # Tolerate a future/human output form that is simply an address token.
    if len(line) > 30 and " " not in line and "\t" not in line:
        return line

    return None


def start_listener(port: int, timeout: int = 12) -> str:
    """
    Start a persistent Tailcat server for a local TCP port.

    Tailcat 0.6.x command:
        tailcat --json serve <port>
    """
    global _LISTENER, _ADDRESS

    if _LISTENER is not None and _LISTENER.poll() is None and _ADDRESS:
        return _ADDRESS

    _require_tailcat()
    ensure_default_key()

    proc = subprocess.Popen(
        ["tailcat", "--json", "serve", str(int(port))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    _CHILDREN.append(proc)
    _LISTENER = proc

    deadline = time.time() + timeout
    seen = []

    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(
                "Tailcat listener exited before producing an address.\n"
                + "\n".join(seen)
                + (("\n" + err) if err else "")
            )

        if proc.stdout is None:
            break

        line = proc.stdout.readline()
        if line:
            seen.append(line.rstrip())
            address = _extract_address(line)
            if address:
                _ADDRESS = address
                return address
        else:
            time.sleep(0.05)

    raise RuntimeError(
        "Timed out waiting for Tailcat listener address."
        + (("\nOutput:\n" + "\n".join(seen)) if seen else "")
    )


# Driver-style short name.
start = start_listener


def get_address() -> Optional[str]:
    if _LISTENER is not None and _LISTENER.poll() is not None:
        return None
    return _ADDRESS


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 8) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _terminate(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


@contextmanager
def forward(
    address: str,
    remote_port: int,
    *,
    local_port: Optional[int] = None,
    timeout: int = 10,
) -> Iterator[int]:
    """
    Temporarily forward localhost:<local_port> to a Tailcat peer.

        tailcat forward <address> <local-port>:<remote-port>

    Yields the local port and tears the forward down on exit.
    """
    _require_tailcat()

    if local_port is None:
        local_port = _find_free_local_port()

    proc = subprocess.Popen(
        [
            "tailcat",
            "forward",
            address,
            f"{int(local_port)}:{int(remote_port)}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _CHILDREN.append(proc)

    if not _wait_for_port(local_port, timeout=timeout):
        err = ""
        if proc.poll() is not None and proc.stderr:
            err = proc.stderr.read()
        _terminate(proc)
        raise RuntimeError(
            f"Tailcat forward did not become ready on localhost:{local_port}"
            + (f"\n{err}" if err else "")
        )

    try:
        yield int(local_port)
    finally:
        _terminate(proc)


def get_json(
    address: str,
    remote_port: int,
    path: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """GET JSON from a peer API through a temporary Tailcat forward."""
    if not path.startswith("/"):
        path = "/" + path

    with forward(address, remote_port, timeout=min(timeout, 10)) as local_port:
        req = request.Request(
            f"http://127.0.0.1:{local_port}{path}",
            method="GET",
        )
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def post_json(
    address: str,
    remote_port: int,
    path: str,
    payload: Dict[str, Any],
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """POST JSON to a peer API through a temporary Tailcat forward."""
    if not path.startswith("/"):
        path = "/" + path

    with forward(address, remote_port, timeout=min(timeout, 10)) as local_port:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"http://127.0.0.1:{local_port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def ping(address: str, *, until_direct: bool = False,
         timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    _require_tailcat()
    args = ["tailcat", "ping"]
    if until_direct:
        args.append("--until-direct")
    args.append(address)
    return _run(args, timeout=timeout)


def run_remote(
    address: str,
    command: str,
    *,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Run one shell command through Tailcat SSH."""
    _require_tailcat()
    return _run(
        ["tailcat", "ssh", address, "sh", "-lc", command],
        timeout=timeout,
    )


def ssh(address: str, extra_args=None) -> int:
    """Open an interactive Tailcat SSH session."""
    _require_tailcat()
    args = ["tailcat", "ssh", address]
    if extra_args:
        args.extend(extra_args)
    return subprocess.call(args)


def stop() -> None:
    """Stop the persistent listener and any active forwards."""
    global _LISTENER, _ADDRESS

    for proc in reversed(_CHILDREN):
        _terminate(proc)
    _CHILDREN.clear()

    _LISTENER = None
    _ADDRESS = None


atexit.register(stop)
