#!/usr/bin/env python3
"""
characterif.py - Heichalot two-node Tailcat bootstrap/link prototype.

v0.3a idea (v0.2 transport preserved; display/API entry-points added):

  NODE A:
      python3 tools/characterif.py start

      - starts the local Flask API
      - starts `tailcat --json serve <api-port>`
      - obtains A's Tailcat address
      - gives a tiny JSON identity document to `croc send --text`
      - prints croc's human-manageable pairing code
      - waits as a server

  NODE B:
      python3 tools/characterif.py join <croc-code>

      - starts its own Flask API/Tailcat listener
      - receives A's identity JSON through croc
      - stores A locally
      - connects to A over Tailcat
      - POSTs B's own identity to A's /api/peer/register
      - stores the two-way relationship
      - remains running as a server

After pairing, both machines are peers: each is both a Tailcat server and client.

v0.3a also reserves/implements simple display-facing API entry-points for AI identity,
standard representation, location manifest, and recent chat. These are deliberately
minimal so their internals can be replaced later without changing the URLs.

This is an internal prototype. The Flask API binds to loopback by default.
Do not expose it directly to an untrusted network without authentication.
"""

from __future__ import annotations

import argparse
import atexit
import configparser
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List
from urllib import error, request

import tailcat

try:
    from flask import Flask, jsonify, request as flask_request, send_file
except ImportError:
    Flask = None
    jsonify = None
    flask_request = None
    send_file = None


APP_NAME = "characterif"
PROTOCOL = "characterif/1"
API_VERSION = 1
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 15

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("CHARACTERIF_CONFIG", BASE_DIR / "characterif.conf")).expanduser()

# Shared Heichalot-CMS platform paths live in src/config.py.
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from config import character_data_dir, platform_data_dir
except ImportError:
    character_data_dir = None
    platform_data_dir = None
STATE_DIR = Path.home() / ".config" / APP_NAME
REGISTRY_CACHE = STATE_DIR / "nodes.json"
LOCATION_MANIFEST = BASE_DIR / "location-manifest.json"

# Small in-memory display feed. This is deliberately not a durable queue.
# It only gives the visual client something to poll until a later event/stream layer exists.
RECENT_CHAT_LIMIT = 100
RECENT_CHAT: List[Dict[str, Any]] = []
RECENT_CHAT_LOCK = threading.Lock()

CHILDREN = []
CURRENT_TAILCAT_ADDRESS: Optional[str] = None


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    return cfg


def cfg_get(cfg: configparser.ConfigParser, section: str, option: str, fallback=None):
    try:
        return cfg.get(section, option)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


def local_node_name(cfg: configparser.ConfigParser) -> str:
    name = cfg_get(cfg, "characterif", "node")
    if name:
        return name.strip()

    for section, option in (
        ("node", "name"),
        ("heichalot", "node"),
        ("server", "node"),
    ):
        name = cfg_get(cfg, section, option)
        if name:
            return name.strip()

    return socket.gethostname().split(".")[0]


def local_ai_name(cfg: configparser.ConfigParser) -> str:
    """Human/AI identity used in simple chat envelopes."""
    name = cfg_get(cfg, "characterif", "ai_name")
    if name:
        return name.strip()
    return local_node_name(cfg)


def character_section(cfg: configparser.ConfigParser, name: Optional[str] = None) -> str:
    """Return the config section for a character on this node."""
    return f"character-{name or local_ai_name(cfg)}"


def character_cfg_get(cfg: configparser.ConfigParser, option: str, fallback=None, name: Optional[str] = None):
    """Read a character-specific setting from [character-<ai_name>]."""
    return cfg_get(cfg, character_section(cfg, name), option, fallback)




def _character_bool(cfg: configparser.ConfigParser, name: str, option: str, fallback: bool = False) -> bool:
    value = character_cfg_get(cfg, option, name=name)
    if value is None:
        return fallback
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def character_document(cfg: configparser.ConfigParser, name: str) -> Optional[Dict[str, Any]]:
    """Return one configured character, or None if it does not exist."""
    section = character_section(cfg, name)
    if not cfg.has_section(section):
        return None

    configured_name = character_cfg_get(cfg, "name", name, name=name).strip()
    character_type = character_cfg_get(cfg, "character_type", "ai", name=name).strip().lower()
    data_dir = character_cfg_get(cfg, "data_dir", "", name=name).strip()

    return {
        "name": configured_name,
        "character_type": character_type,
        "node": local_node_name(cfg),
        "state": "available",
        "portrait": f"/api/character/{configured_name}/portrait",
        "data_dir": data_dir or None,
        "available_remotely": _character_bool(cfg, name, "available_remotely"),
        "exists_remotely": _character_bool(cfg, name, "exists_remotely"),
    }


def character_documents(cfg: configparser.ConfigParser) -> List[Dict[str, Any]]:
    """Return all characters configured in [character-<name>] sections."""
    result = []
    for section in cfg.sections():
        if not section.startswith("character-"):
            continue
        name = section[len("character-"):]
        doc = character_document(cfg, name)
        if doc is not None:
            result.append(doc)
    return result


def remote_character_data_dir(name: str, node: str) -> Path:
    """Return the local cache directory for a character learned from another node."""
    def slug(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
        if not cleaned:
            raise ValueError("character/node name does not contain a usable directory name")
        return cleaned

    return platform_data_dir() / f"character-{slug(name)}@{slug(node)}"


def cached_remote_character_documents() -> List[Dict[str, Any]]:
    """Load cached remote character metadata from the platform data directory."""
    result = []
    root = platform_data_dir()
    if not root.is_dir():
        return result

    for data_dir in sorted(root.glob("character-*@*")):
        json_path = data_dir / "character.json"
        conf_path = data_dir / "character.conf"
        if not json_path.is_file() or not conf_path.is_file():
            continue
        try:
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            meta = configparser.ConfigParser()
            meta.read(conf_path, encoding="utf-8")
            if not isinstance(doc, dict):
                continue
            doc = dict(doc)
            doc["local"] = meta.getboolean("address", "local", fallback=False)
            doc["source_node"] = meta.get("address", "node", fallback="") or None
            doc["data_dir"] = str(data_dir.resolve())
            result.append(doc)
        except Exception:
            continue
    return result


def all_character_documents(cfg: configparser.ConfigParser) -> List[Dict[str, Any]]:
    """Return local characters followed by locally cached remote characters."""
    local = []
    for doc in character_documents(cfg):
        item = dict(doc)
        item["local"] = True
        local.append(item)
    return local + cached_remote_character_documents()


def remotely_available_character_documents(cfg: configparser.ConfigParser) -> List[Dict[str, Any]]:
    """Return only local characters that this node explicitly advertises remotely."""
    result = []
    for doc in character_documents(cfg):
        if doc.get("available_remotely"):
            item = dict(doc)
            item["local"] = True
            result.append(item)
    return result


def cache_remote_characters(peer: Dict[str, Any], payload: Dict[str, Any]) -> List[Path]:
    """Persist character metadata learned from one remote CharacterIF server."""
    node = str(peer.get("node") or "").strip()
    if not node:
        raise RuntimeError("remote peer has no node name")

    characters = payload.get("characters")
    if not isinstance(characters, list):
        raise RuntimeError("remote server did not return a character list")

    written = []
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "").strip()
        if not name:
            continue

        data_dir = remote_character_data_dir(name, node)
        data_dir.mkdir(parents=True, exist_ok=True)

        (data_dir / "character.json").write_text(
            json.dumps(character, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        meta = configparser.ConfigParser()
        meta["address"] = {
            "node": node,
            "local": "false",
            "api_port": str(peer.get("api_port", DEFAULT_PORT)),
            "tailcat_address": str(peer.get("address") or ""),
            "updated": utcnow(),
        }
        with (data_dir / "character.conf").open("w", encoding="utf-8") as handle:
            meta.write(handle)
        written.append(data_dir)

    return written


def fetch_remote_characters(peer: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the public character index from one Tailcat peer."""
    return tailcat.get_json(
        peer["address"],
        int(peer.get("api_port", DEFAULT_PORT)),
        "/",
        timeout=15,
    )


def sync_remote_characters(peer: Dict[str, Any]) -> List[Path]:
    payload = fetch_remote_characters(peer)
    if not payload.get("ok", True):
        raise RuntimeError("remote character index returned an error: " + json.dumps(payload))
    return cache_remote_characters(peer, payload)


def _delayed_sync_remote_characters(peer: Dict[str, Any]) -> None:
    """Best-effort reverse sync after a newly joined peer has started its Flask server."""
    last_error = None
    for _ in range(8):
        time.sleep(1.0)
        try:
            written = sync_remote_characters(peer)
            print(f"\nCached {len(written)} remote character(s) from {peer.get('node')}")
            return
        except Exception as exc:
            last_error = exc
    print(f"\nRemote character sync from {peer.get('node')} deferred: {last_error}")


def character_private_config_path(cfg: configparser.ConfigParser, name: str) -> Optional[Path]:
    """Return the private character.conf path for a local character."""
    data_dir = character_cfg_get(cfg, "data_dir", "", name=name)
    if not data_dir:
        return None
    return Path(data_dir).expanduser() / "character.conf"


def load_character_private_config(cfg: configparser.ConfigParser, name: str) -> configparser.ConfigParser:
    private = configparser.ConfigParser()
    path = character_private_config_path(cfg, name)
    if path is not None and path.is_file():
        private.read(path, encoding="utf-8")
    return private


def cached_remote_character(name: str) -> Optional[Dict[str, Any]]:
    """Return the first cached remote character with this name."""
    for doc in cached_remote_character_documents():
        if str(doc.get("name") or "").casefold() == name.casefold():
            return doc
    return None


def cached_remote_address(name: str) -> Optional[Dict[str, Any]]:
    """Load routing data from a cached remote character's character.conf."""
    doc = cached_remote_character(name)
    if doc is None:
        return None
    data_dir = doc.get("data_dir")
    if not data_dir:
        return None
    meta = configparser.ConfigParser()
    conf_path = Path(str(data_dir)) / "character.conf"
    if not conf_path.is_file():
        return None
    meta.read(conf_path, encoding="utf-8")
    if not meta.has_section("address"):
        return None
    return {
        "node": meta.get("address", "node", fallback=""),
        "address": meta.get("address", "tailcat_address", fallback=""),
        "api_port": meta.getint("address", "api_port", fallback=DEFAULT_PORT),
    }


def respond_as_character(cfg: configparser.ConfigParser, name: str, text: str) -> Dict[str, Any]:
    """Route one synchronous prompt to a local or cached remote character."""
    local_doc = character_document(cfg, name)
    if local_doc is not None:
        private = load_character_private_config(cfg, name)
        api = private.get("interface", "api", fallback="ollama")
        model = private.get("interface", "model", fallback="gemma3")

        # Lazy import keeps CharacterIF usable for routing-only installations.
        import responder

        response_text = responder.respond(text, api=api, model=model)
        return {
            "ok": True,
            "character": local_doc.get("name", name),
            "node": local_node_name(cfg),
            "local": True,
            "response": response_text,
            "time": utcnow(),
        }

    remote_doc = cached_remote_character(name)
    route = cached_remote_address(name)
    if remote_doc is None or route is None or not route.get("address"):
        raise RuntimeError(f"character not found or has no route: {name}")

    return tailcat.post_json(
        route["address"],
        int(route.get("api_port", DEFAULT_PORT)),
        f"/api/character/{name}/respond",
        {"text": text},
        timeout=180,
    )


def local_ai_document(cfg: configparser.ConfigParser) -> Dict[str, Any]:
    """Return the configured/default local AI participant."""
    name = local_ai_name(cfg)
    doc = character_document(cfg, name)
    if doc is not None and doc.get("character_type") == "ai":
        return doc
    return {
        "name": name,
        "character_type": "ai",
        "node": local_node_name(cfg),
        "state": "available",
        "portrait": f"/api/ai/{name}/portrait",
    }


def portrait_path(cfg: configparser.ConfigParser, name: Optional[str] = None) -> Optional[Path]:
    """Resolve the configured portrait for a character."""
    value = character_cfg_get(cfg, "portrait", name=name)
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def location_document() -> Dict[str, Any]:
    """
    Load location-manifest.json if present; otherwise return the v1 stage shape.

    The fallback preserves the API contract before any artwork exists.
    """
    if LOCATION_MANIFEST.exists():
        try:
            data = json.loads(LOCATION_MANIFEST.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return {
        "location": "skylab-default",
        "dimensions": {"width": 12, "height": 4, "depth": 8},
        "stage": {
            "background": None,
            "floor": None,
            "ceiling": None,
            "left_wall": None,
            "right_wall": None,
        },
        "implemented": False,
    }


def remember_chat_message(message: Dict[str, Any]) -> None:
    item = dict(message)
    item.setdefault("received_time", utcnow())
    with RECENT_CHAT_LOCK:
        RECENT_CHAT.append(item)
        if len(RECENT_CHAT) > RECENT_CHAT_LIMIT:
            del RECENT_CHAT[:-RECENT_CHAT_LIMIT]


def api_port(cfg: configparser.ConfigParser) -> int:
    return int(character_cfg_get(cfg, "api_port", DEFAULT_PORT))


def daemon_url(cfg: configparser.ConfigParser) -> str:
    bind = character_cfg_get(cfg, "api_host", DEFAULT_BIND)
    if bind in ("0.0.0.0", "::"):
        bind = "127.0.0.1"
    return f"http://{bind}:{api_port(cfg)}"


def load_registry() -> Dict[str, Any]:
    ensure_state_dir()
    if not REGISTRY_CACHE.exists():
        return {"version": API_VERSION, "nodes": {}}

    try:
        data = json.loads(REGISTRY_CACHE.read_text())
        data.setdefault("version", API_VERSION)
        data.setdefault("nodes", {})
        return data
    except Exception:
        return {"version": API_VERSION, "nodes": {}}


def save_registry(data: Dict[str, Any]) -> None:
    ensure_state_dir()
    tmp = REGISTRY_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(REGISTRY_CACHE)


def save_peer(doc: Dict[str, Any]) -> None:
    reg = load_registry()
    doc = dict(doc)
    doc["updated"] = utcnow()
    reg["nodes"][doc["node"]] = doc
    save_registry(reg)


def get_peer(node: str) -> Optional[Dict[str, Any]]:
    return load_registry().get("nodes", {}).get(node)


def run_cmd(args, *, timeout=DEFAULT_TIMEOUT, input_text=None, env=None) -> Dict[str, Any]:
    started = time.time()
    try:
        cp = subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
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
            "error": f"command not found: {args[0]}",
            "argv": args,
        }


def cleanup_children() -> None:
    for proc in reversed(CHILDREN):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass


atexit.register(cleanup_children)


def check_dependencies(require_croc=False) -> None:
    missing = []
    if not tailcat.available():
        missing.append("tailcat")
    if require_croc and not shutil.which("croc"):
        missing.append("croc")
    if missing:
        raise RuntimeError("missing command(s): " + ", ".join(missing))



def start_tailcat_listener(port: int) -> str:
    """Compatibility wrapper; Tailcat implementation now lives in tailcat.py."""
    global CURRENT_TAILCAT_ADDRESS
    CURRENT_TAILCAT_ADDRESS = tailcat.start(port)
    return CURRENT_TAILCAT_ADDRESS


def identity_document(cfg: configparser.ConfigParser, address: str) -> Dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "node": local_node_name(cfg),
        "ai_name": local_ai_name(cfg),
        "address": address,
        "api_port": api_port(cfg),
        "services": {
            "characterif_api": api_port(cfg),
        },
        "created": utcnow(),
    }


def parse_identity_text(text: str) -> Dict[str, Any]:
    """
    Find a characterif identity JSON object in croc's stdout.

    Normally croc's received --text content should be the stdout itself, but
    scanning permits harmless surrounding status text.
    """
    text = text.strip()

    try:
        obj = json.loads(text)
        if obj.get("protocol") == PROTOCOL:
            return obj
    except Exception:
        pass

    # Try line-by-line in case croc includes informational output on stdout.
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
            if obj.get("protocol") == PROTOCOL:
                return obj
        except Exception:
            pass

    # Last-resort JSON object scan.
    for m in re.finditer(r"\{.*?\}", text, flags=re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if obj.get("protocol") == PROTOCOL:
                return obj
        except Exception:
            continue

    raise RuntimeError("received croc text did not contain a characterif/1 identity document")


def start_croc_send_text(payload: str) -> tuple[subprocess.Popen, str]:
    """
    Start `croc send --text ...`, read enough output to obtain its human code,
    and leave croc running until the receiver consumes the text.
    """
    check_dependencies(require_croc=True)

    proc = subprocess.Popen(
        ["croc", "send", "--text", payload],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    CHILDREN.append(proc)

    deadline = time.time() + 20
    lines = []
    code = None

    # Croc has historically printed variants such as "Code is: ...".
    patterns = [
        re.compile(r"code\s+is\s*:\s*(.+?)\s*$", re.I),
        re.compile(r"code\s*:\s*(.+?)\s*$", re.I),
    ]

    while time.time() < deadline:
        if proc.stdout is None:
            break

        line = proc.stdout.readline()
        if line:
            clean = line.rstrip()
            lines.append(clean)

            # Show croc's output verbatim. Earlier we suppressed every line
            # containing "code", which accidentally hid the actual receive
            # command / URL containing the generated secret.
            print(f"[croc] {clean}")

            # Older/current classic form:
            #     Code is: alpha-beta-gamma
            for pattern in patterns:
                m = pattern.search(clean)
                if m:
                    code = m.group(1).strip()
                    break

            # Current Linux/macOS form keeps the secret out of argv:
            #     CROC_SECRET='alpha-beta-gamma' croc
            if not code:
                m = re.search(
                    r"""CROC_SECRET\s*=\s*['\"]([^'\"]+)['\"]""",
                    clean,
                    flags=re.I,
                )
                if m:
                    code = m.group(1).strip()

            # Classic receive command:
            #     croc alpha-beta-gamma
            if not code:
                m = re.search(r"\bcroc\s+([^\s]+)\s*$", clean)
                if m:
                    candidate = m.group(1).strip().strip("'\"")
                    if not candidate.startswith("-"):
                        code = candidate

            # Browser form:
            #     https://getcroc.com/?code=alpha-beta-gamma
            if not code:
                m = re.search(r"[?&]code=([^&\s]+)", clean, flags=re.I)
                if m:
                    from urllib.parse import unquote
                    code = unquote(m.group(1)).strip()

            if code:
                return proc, code
        elif proc.poll() is not None:
            break
        else:
            time.sleep(0.05)

    raise RuntimeError(
        "croc did not print a pairing code"
        + (("\nOutput:\n" + "\n".join(lines)) if lines else "")
    )


def receive_croc_text(code: str, timeout: int = 300) -> str:
    """
    Receive croc text using CROC_SECRET in the child environment.

    This is intentionally the first thing to try. Python's subprocess API
    explicitly supports setting an environment for a spawned process.

    If the installed croc build does not accept CROC_SECRET for receive mode,
    we fall back to passing the code as an argument.
    """
    check_dependencies(require_croc=True)

    env = os.environ.copy()
    env["CROC_SECRET"] = code

    result = run_cmd(["croc", "--yes"], timeout=timeout, env=env)
    if result["ok"] and result.get("stdout", "").strip():
        return result["stdout"]

    # Compatibility fallback. If the environment-variable invocation fails,
    # try croc's ordinary positional-code form.
    fallback = run_cmd(["croc", "--yes", code], timeout=timeout)
    if fallback["ok"] and fallback.get("stdout", "").strip():
        return fallback["stdout"]

    raise RuntimeError(
        "could not receive croc text.\n"
        f"CROC_SECRET attempt stderr: {result.get('stderr','').strip()}\n"
        f"argument fallback stderr: {fallback.get('stderr','').strip()}"
    )


def find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_port(port: int, timeout=8) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def post_json(url: str, payload: Dict[str, Any], timeout=15) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def register_with_remote_peer(peer: Dict[str, Any], me: Dict[str, Any]) -> Dict[str, Any]:
    """Register through the optional Tailcat transport driver."""
    return tailcat.post_json(
        peer["address"],
        int(peer.get("api_port", DEFAULT_PORT)),
        "/api/peer/register",
        me,
        timeout=15,
    )


def send_chat_to_remote_peer(peer: Dict[str, Any], envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Send chat through the optional Tailcat transport driver."""
    return tailcat.post_json(
        peer["address"],
        int(peer.get("api_port", DEFAULT_PORT)),
        "/api/chat-text",
        envelope,
        timeout=15,
    )


def make_app() -> "Flask":
    if Flask is None:
        raise RuntimeError("Flask is not installed. Try: pip install flask")

    cfg = load_config()
    app = Flask(APP_NAME)

    @app.get("/api/status")
    def api_status():
        return jsonify({
            "ok": True,
            "service": APP_NAME,
            "protocol": PROTOCOL,
            "api_version": API_VERSION,
            "node": local_node_name(cfg),
            "ai_name": local_ai_name(cfg),
            "tailcat_address": CURRENT_TAILCAT_ADDRESS,
            "time": utcnow(),
        })

    # --- Character / AI display API --------------------------------------

    @app.get("/")
    def index():
        # The public CharacterIF index is intentionally just JSON.  Only local
        # characters explicitly marked available_remotely are advertised.
        return jsonify({
            "ok": True,
            "node": local_node_name(cfg),
            "characters": remotely_available_character_documents(cfg),
        })

    @app.get("/api/characters")
    def api_characters():
        return jsonify({"ok": True, "characters": all_character_documents(cfg)})

    @app.get("/api/character/<name>")
    def api_character(name):
        character = character_document(cfg, name)
        if character is None:
            return jsonify({"ok": False, "error": "character not found", "name": name}), 404
        return jsonify({"ok": True, **character})

    @app.get("/api/ais")
    def api_ais():
        ais = [c for c in all_character_documents(cfg) if c.get("character_type") == "ai"]
        return jsonify({"ok": True, "ais": ais})

    @app.get("/api/ai/<name>")
    def api_ai(name):
        ai = character_document(cfg, name)
        if ai is None or ai.get("character_type") != "ai":
            return jsonify({"ok": False, "error": "ai not found", "name": name}), 404
        return jsonify({"ok": True, **ai})

    @app.get("/api/character/<name>/portrait")
    @app.get("/api/ai/<name>/portrait")
    @app.get("/api/ai/<name>/representation/standard")
    def api_character_portrait(name):
        character = character_document(cfg, name)
        if character is None:
            return jsonify({"ok": False, "error": "character not found", "name": name}), 404

        path = portrait_path(cfg, name)
        if path is None:
            return jsonify({
                "ok": False,
                "error": "portrait not configured",
                "name": name,
                "config_key": f"[{character_section(cfg, name)}] portrait",
            }), 501
        if not path.is_file():
            return jsonify({
                "ok": False,
                "error": "portrait file not found",
                "name": name,
                "path": str(path),
            }), 404
        return send_file(path)

    @app.post("/api/character/<name>/respond")
    def api_character_respond(name):
        body = flask_request.get_json(silent=True) or {}
        text_value = body.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            return jsonify({"ok": False, "error": "text is required"}), 400

        try:
            result = respond_as_character(cfg, name, text_value)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "name": name}), 502


    @app.get("/api/location")
    def api_location():
        return jsonify({"ok": True, **location_document()})

    @app.get("/api/chat/recent")
    def api_chat_recent():
        try:
            limit = int(flask_request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, RECENT_CHAT_LIMIT))
        with RECENT_CHAT_LOCK:
            messages = list(RECENT_CHAT[-limit:])
        return jsonify({"ok": True, "messages": messages})

    # --- Existing peer/node API -------------------------------------------

    @app.get("/api/nodes")
    def api_nodes():
        return jsonify(load_registry())

    @app.get("/api/nodes/<node>")
    def api_node(node):
        peer = get_peer(node)
        if not peer:
            return jsonify({"ok": False, "error": "node not found", "node": node}), 404
        return jsonify({"ok": True, "node": peer})

    @app.post("/api/peer/register")
    def api_peer_register():
        body = flask_request.get_json(silent=True) or {}

        if body.get("protocol") != PROTOCOL:
            return jsonify({"ok": False, "error": "unsupported protocol"}), 400
        if not body.get("node") or not body.get("address"):
            return jsonify({"ok": False, "error": "node and address are required"}), 400

        save_peer(body)

        # The joining node starts its Flask server immediately after this
        # registration returns, so retry its character index in the background.
        threading.Thread(
            target=_delayed_sync_remote_characters,
            args=(dict(body),),
            daemon=True,
        ).start()

        mine = None
        if CURRENT_TAILCAT_ADDRESS:
            mine = identity_document(cfg, CURRENT_TAILCAT_ADDRESS)

        print(f"\nPeer registered: {body['node']}")
        print(f"  address: {body['address'][:45]}{'...' if len(body['address']) > 45 else ''}")

        return jsonify({
            "ok": True,
            "registered": body["node"],
            "peer": mine,
        })

    @app.post("/api/chat-text")
    def api_chat_text():
        body = flask_request.get_json(silent=True) or {}

        text_value = body.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            return jsonify({"ok": False, "error": "text is required"}), 400

        sender_node = body.get("from_node") or "unknown-node"
        sender_ai = body.get("from_ai") or sender_node
        target_ai = body.get("to_ai") or local_ai_name(cfg)

        # Keep a small display-oriented feed as well as printing to console.
        # This is not intended to replace durable chat storage/queueing.
        remembered = dict(body)
        remembered.setdefault("from_node", sender_node)
        remembered.setdefault("from_ai", sender_ai)
        remembered.setdefault("to_ai", target_ai)
        remember_chat_message(remembered)

        print("\nCHAT")
        print(f"  from node: {sender_node}")
        print(f"  from ai:   {sender_ai}")
        print(f"  to ai:     {target_ai}")
        print(f"  text:      {text_value}")

        return jsonify({
            "ok": True,
            "received": True,
            "node": local_node_name(cfg),
            "ai": local_ai_name(cfg),
            "time": utcnow(),
        })

    @app.post("/api/ping")
    def api_ping():
        body = flask_request.get_json(silent=True) or {}
        node = body.get("node")
        timeout = int(body.get("timeout", DEFAULT_TIMEOUT))
        peer = get_peer(node) if node else None

        if not peer or not peer.get("address"):
            return jsonify({"ok": False, "error": "node/address not found", "node": node}), 404

        result = tailcat.ping(
            peer["address"],
            until_direct=bool(body.get("until_direct")),
            timeout=timeout,
        )
        result["node"] = node
        return jsonify(result), (200 if result["ok"] else 502)

    @app.post("/api/run")
    def api_run():
        body = flask_request.get_json(silent=True) or {}
        node = body.get("node")
        command = body.get("command")
        timeout = int(body.get("timeout", 60))

        if not node or not command:
            return jsonify({"ok": False, "error": "node and command are required"}), 400

        peer = get_peer(node)
        if not peer or not peer.get("address"):
            return jsonify({"ok": False, "error": "node/address not found", "node": node}), 404

        result = tailcat.run_remote(
            peer["address"],
            command,
            timeout=timeout,
        )
        result["node"] = node
        result["command"] = command
        return jsonify(result), (200 if result["ok"] else 502)

    return app


def run_flask(cfg: configparser.ConfigParser, bind=None, port=None) -> int:
    bind = bind or character_cfg_get(cfg, "api_host", DEFAULT_BIND)
    port = port or api_port(cfg)

    app = make_app()
    print(f"\n{APP_NAME}: node={local_node_name(cfg)}")
    print(f"{APP_NAME}: api=http://{bind}:{port}")
    print(f"{APP_NAME}: registry={REGISTRY_CACHE}")
    app.run(host=bind, port=port, threaded=True, use_reloader=False)
    return 0


def api_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = load_config()
    url = daemon_url(cfg) + path
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except Exception:
            return {"ok": False, "error": f"HTTP {exc.code}", "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


def print_result(obj: Any, raw=False) -> int:
    if raw and isinstance(obj, dict):
        if obj.get("stdout"):
            sys.stdout.write(obj["stdout"])
        if obj.get("stderr"):
            sys.stderr.write(obj["stderr"])
        return 0 if obj.get("ok") else 1

    print(json.dumps(obj, indent=2))
    return 0 if not isinstance(obj, dict) or obj.get("ok", True) else 1


def cmd_start(args) -> int:
    cfg = load_config()
    port = args.port or api_port(cfg)

    check_dependencies(require_croc=True)
    address = start_tailcat_listener(port)
    me = identity_document(cfg, address)
    payload = json.dumps(me, separators=(",", ":"))

    print(f"\ncharacterif node: {me['node']}")
    print("Tailcat listener: ready")
    print(f"Tailcat address: {address[:45]}{'...' if len(address) > 45 else ''}")

    _, code = start_croc_send_text(payload)

    print("\nPAIRING CODE")
    print(f"  {code}")
    print("\nGive that croc code to the second machine and run:")
    print(f"  python3 tools/characterif.py join '{code}'")
    print("\nWaiting for peer registration...")

    return run_flask(cfg, bind=args.bind, port=port)


def cmd_join(args) -> int:
    cfg = load_config()
    port = args.port or api_port(cfg)

    check_dependencies(require_croc=True)

    # B must become a server too before telling A about itself.
    address = start_tailcat_listener(port)
    me = identity_document(cfg, address)

    print(f"\ncharacterif node: {me['node']}")
    print("Tailcat listener: ready")
    print("Receiving first peer address through croc...")

    received = receive_croc_text(args.code, timeout=args.croc_timeout)
    peer = parse_identity_text(received)

    if peer["node"] == me["node"]:
        raise RuntimeError(f"peer has same node name as this machine: {me['node']}")

    save_peer(peer)

    print(f"Received peer: {peer['node']}")
    print("Connecting back over Tailcat and registering this node...")

    reply = register_with_remote_peer(peer, me)
    if not reply.get("ok"):
        raise RuntimeError("peer registration failed: " + json.dumps(reply))

    # A may return its current identity. Save it because it is authoritative.
    returned_peer = reply.get("peer")
    if isinstance(returned_peer, dict) and returned_peer.get("node") and returned_peer.get("address"):
        save_peer(returned_peer)

    print("\nPAIRING COMPLETE")
    print(f"  {me['node']} <-> {peer['node']}")
    print("Both nodes now have each other's Tailcat address.")

    print(f"Fetching characters from {peer['node']}...")
    written = sync_remote_characters(peer)
    print(f"Cached {len(written)} remote character(s).")
    for path in written:
        print(f"  {path}")

    return run_flask(cfg, bind=args.bind, port=port)



def _setup_prompt_value(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def _setup_prompt_bool(label: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{label} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "1", "true", "on"}:
            return True
        if value in {"n", "no", "0", "false", "off"}:
            return False
        print("Please answer y or n.")


def _parse_bool_arg(value: str) -> bool:
    text = value.strip().lower()
    if text in {"y", "yes", "1", "true", "on"}:
        return True
    if text in {"n", "no", "0", "false", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _setup_config_bool(
    cfg: configparser.ConfigParser,
    option: str,
    fallback: bool,
) -> bool:
    try:
        return cfg.getboolean("characterif", option, fallback=fallback)
    except ValueError:
        return fallback


def _write_setup_config(cfg: configparser.ConfigParser) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        cfg.write(handle)
    print(f"\nConfiguration written to:\n  {CONFIG_PATH.resolve()}")


def setup_character(args) -> int:
    """Create or update one CharacterIF character configuration."""
    cfg = load_config()

    name = (args.name or _setup_prompt_value("Character name")).strip()
    if not name:
        raise RuntimeError("character name is required")

    portrait_value = args.portrait or _setup_prompt_value("Portrait image filename")
    portrait_source = Path(portrait_value).expanduser()
    if not portrait_source.is_file():
        raise RuntimeError(f"portrait file not found: {portrait_source}")

    available_remotely = (
        args.available_remotely
        if args.available_remotely is not None
        else _setup_prompt_bool("Available remotely?", False)
    )
    exists_remotely = (
        args.exists_remotely
        if args.exists_remotely is not None
        else _setup_prompt_bool("Exists remotely?", False)
    )
    interface_api = (args.interface_api or _setup_prompt_value("Interface API", "ollama")).strip()
    interface_model = (args.model or _setup_prompt_value("Model", "gemma3")).strip()

    if character_data_dir is None:
        raise RuntimeError("cannot import character_data_dir from src/config.py")

    data_dir = character_data_dir(name)
    data_dir.mkdir(parents=True, exist_ok=True)

    portrait_target = data_dir / portrait_source.name
    if portrait_source.resolve() != portrait_target.resolve():
        shutil.copy2(portrait_source, portrait_target)

    section = f"character-{name}"
    if not cfg.has_section(section):
        cfg.add_section(section)

    cfg.set(section, "name", name)
    cfg.set(section, "character_type", "ai")
    cfg.set(section, "portrait", str(portrait_target.resolve()))
    cfg.set(section, "data_dir", str(data_dir.resolve()))
    cfg.set(section, "available_remotely", "true" if available_remotely else "false")
    cfg.set(section, "exists_remotely", "true" if exists_remotely else "false")

    # Private, machine-local implementation details. This file is never used
    # to build the public character document returned over CharacterIF.
    private_path = data_dir / "character.conf"
    private = configparser.ConfigParser()
    if private_path.is_file():
        private.read(private_path, encoding="utf-8")
    if not private.has_section("address"):
        private.add_section("address")
    if not private.has_section("interface"):
        private.add_section("interface")
    private.set("address", "node", local_node_name(cfg))
    private.set("address", "local", "true")
    private.set("interface", "api", interface_api)
    private.set("interface", "model", interface_model)
    with private_path.open("w", encoding="utf-8") as handle:
        private.write(handle)

    _write_setup_config(cfg)

    print("\nCharacter configured")
    print(f"  name:               {name}")
    print(f"  section:            [{section}]")
    print("  character type:     ai")
    print(f"  data:               {data_dir.resolve()}")
    print(f"  portrait:           {portrait_target.resolve()}")
    print(f"  available remotely: {'yes' if available_remotely else 'no'}")
    print(f"  exists remotely:    {'yes' if exists_remotely else 'no'}")
    print(f"  interface api:      {interface_api}")
    print(f"  model:              {interface_model}")
    print(f"  private config:     {(data_dir / 'character.conf').resolve()}")
    return 0


def setup_lan() -> int:
    """
    Configure CharacterIF's local-network identity and LAN discovery.

    Existing config.ini sections and unrelated options are preserved.
    The historical [characterif] section name is retained for compatibility.
    """
    cfg = load_config()
    if not cfg.has_section("characterif"):
        cfg.add_section("characterif")

    current_character = cfg_get(cfg, "characterif", "ai_name", local_ai_name(cfg))
    current_node = cfg_get(cfg, "characterif", "node", local_node_name(cfg))
    current_port = str(api_port(cfg))
    current_lan = _setup_config_bool(cfg, "lan", True)

    print("\nCharacterIF LAN setup\n")

    character_name = _setup_prompt_value("Character name", current_character)
    node_name = _setup_prompt_value("Node name", current_node)

    while True:
        port_text = _setup_prompt_value("API port", current_port)
        try:
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ValueError
            break
        except ValueError:
            print("Please enter a TCP port between 1 and 65535.")

    lan_enabled = _setup_prompt_bool(
        "Enable automatic local LAN discovery?",
        current_lan,
    )

    try:
        import zeroconf  # noqa: F401
        zeroconf_ok = True
    except ImportError:
        zeroconf_ok = False

    print("\nLAN dependency check")
    print(f"  zeroconf: {'installed' if zeroconf_ok else 'not installed'}")

    if not _setup_prompt_bool("\nSave LAN configuration?", True):
        print("Configuration not changed.")
        return 0

    cfg.set("characterif", "ai_name", character_name)
    cfg.set("characterif", "node", node_name)
    section = f"character-{character_name}"
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, "api_port", str(port))
    cfg.set("characterif", "lan", "true" if lan_enabled else "false")

    _write_setup_config(cfg)

    if lan_enabled and not zeroconf_ok:
        print("\nLAN discovery is enabled, but zeroconf is not installed.")
        print("Install it with:")
        print("  pip install zeroconf")

    return 0


def setup_remote() -> int:
    """
    Configure explicit online/Tailcat participation.

    Running this setup does not itself start Tailcat or contact the Internet.
    It only records whether online operation is enabled.
    """
    cfg = load_config()
    if not cfg.has_section("characterif"):
        cfg.add_section("characterif")

    current_online = _setup_config_bool(cfg, "online", False)

    print("\nCharacterIF remote setup\n")
    print("Remote mode uses Tailcat and Croc and may communicate over the Internet.")
    print("LAN-only operation does not require remote mode.\n")

    online_enabled = _setup_prompt_bool(
        "Enable online/Tailcat networking?",
        current_online,
    )

    tailcat_ok = tailcat.available()
    croc_ok = shutil.which("croc") is not None

    print("\nRemote dependency check")
    print(f"  tailcat: {'installed' if tailcat_ok else 'not installed'}")
    print(f"  croc:    {'installed' if croc_ok else 'not installed'}")

    if not _setup_prompt_bool("\nSave remote configuration?", True):
        print("Configuration not changed.")
        return 0

    cfg.set(
        "characterif",
        "online",
        "true" if online_enabled else "false",
    )
    _write_setup_config(cfg)

    if online_enabled and not tailcat_ok:
        print("\nOnline networking is enabled, but tailcat is not installed.")

    if online_enabled and not croc_ok:
        print("\nOnline bootstrap is enabled, but croc is not installed.")

    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Heichalot CharacterIF node interface")
    p.add_argument(
        "--setup",
        choices=("lan", "remote"),
        help="configure LAN or remote networking",
    )
    p.add_argument(
        "--setup-character",
        action="store_true",
        help="create or update a character; prompts for missing values",
    )
    p.add_argument("--name", help="character name")
    p.add_argument("--portrait", help="portrait image filename")
    p.add_argument("--api", dest="interface_api", help="local responder API (default: ollama)")
    p.add_argument("--model", help="local responder model (default: gemma3)")
    p.add_argument(
        "--available_remotely", "--available-remotely",
        dest="available_remotely",
        type=_parse_bool_arg,
        help="whether this character can be reached remotely (true/false)",
    )
    p.add_argument(
        "--exists_remotely", "--exists-remotely",
        dest="exists_remotely",
        type=_parse_bool_arg,
        help="whether this character exists on a remote node (true/false)",
    )
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("start", help="start first node and print a croc pairing code")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)

    s = sub.add_parser("join", help="join the first node using its croc pairing code")
    s.add_argument("code")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)
    s.add_argument("--croc-timeout", type=int, default=300)

    s = sub.add_parser("server", help="run API/Tailcat server without croc pairing")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)

    sub.add_parser("status", help="show running daemon status")
    sub.add_parser("nodes", help="list locally known peers")

    s = sub.add_parser("sync-characters", help="fetch and cache characters from a known peer")
    s.add_argument("node")

    s = sub.add_parser("node", help="show one locally known peer")
    s.add_argument("node")

    s = sub.add_parser("ping", help="Tailcat ping a known peer")
    s.add_argument("node")
    s.add_argument("--until-direct", action="store_true")
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)

    s = sub.add_parser("run", help="run a command using Tailcat SSH")
    s.add_argument("node")
    s.add_argument("remote_command", nargs=argparse.REMAINDER)
    s.add_argument("--timeout", type=int, default=60)

    s = sub.add_parser("chat", help="send simple text to a known peer")
    s.add_argument("node")
    s.add_argument("--chat-text", required=True)
    s.add_argument("--ai-name", help="sender AI name; defaults to config/local node name")
    s.add_argument("--to-ai", help="optional target AI name on remote node")

    s = sub.add_parser("respond", help="request one synchronous response from a character")
    s.add_argument("character")
    s.add_argument("--text", required=True)

    s = sub.add_parser("ssh", help="open interactive Tailcat SSH to a known peer")
    s.add_argument("node")
    s.add_argument("ssh_args", nargs=argparse.REMAINDER)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.setup == "lan":
        return setup_lan()

    if args.setup == "remote":
        return setup_remote()

    if args.setup_character:
        return setup_character(args)

    if not args.command:
        parser.print_help()
        return 2

    cfg = load_config()

    try:
        if args.command == "start":
            return cmd_start(args)

        if args.command == "join":
            return cmd_join(args)

        if args.command == "server":
            port = args.port or api_port(cfg)
            start_tailcat_listener(port)
            return run_flask(cfg, bind=args.bind, port=port)

        if args.command == "status":
            return print_result(api_request("GET", "/api/status"))

        if args.command == "nodes":
            return print_result(api_request("GET", "/api/nodes"))

        if args.command == "sync-characters":
            peer = get_peer(args.node)
            if not peer or not peer.get("address"):
                print(f"node {args.node!r} not found in {REGISTRY_CACHE}", file=sys.stderr)
                return 1
            written = sync_remote_characters(peer)
            print(f"Cached {len(written)} remote character(s) from {args.node}.")
            for path in written:
                print(path)
            return 0

        if args.command == "node":
            return print_result(api_request("GET", f"/api/nodes/{args.node}"))

        if args.command == "ping":
            return print_result(api_request("POST", "/api/ping", {
                "node": args.node,
                "until_direct": args.until_direct,
                "timeout": args.timeout,
            }), raw=True)

        if args.command == "run":
            remote_command = " ".join(args.remote_command).strip()
            if not remote_command:
                parser.error("run requires a remote command")
            return print_result(api_request("POST", "/api/run", {
                "node": args.node,
                "command": remote_command,
                "timeout": args.timeout,
            }), raw=True)

        if args.command == "chat":
            peer = get_peer(args.node)
            if not peer or not peer.get("address"):
                print(f"node {args.node!r} not found in {REGISTRY_CACHE}", file=sys.stderr)
                return 1

            envelope = {
                "protocol": PROTOCOL,
                "type": "chat-text",
                "from_node": local_node_name(cfg),
                "from_ai": args.ai_name or local_ai_name(cfg),
                "to_ai": args.to_ai or None,
                "text": args.chat_text,
                "time": utcnow(),
            }

            result = send_chat_to_remote_peer(peer, envelope)
            return print_result(result)

        if args.command == "respond":
            return print_result(respond_as_character(cfg, args.character, args.text))

        if args.command == "ssh":
            result = api_request("GET", f"/api/nodes/{args.node}")
            if not result.get("ok"):
                return print_result(result)

            address = result["node"].get("address")
            if not address:
                print(f"node {args.node!r} has no Tailcat address", file=sys.stderr)
                return 1

            return tailcat.ssh(address, args.ssh_args)

    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:
        print(f"{APP_NAME}: ERROR: {exc}", file=sys.stderr)
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
