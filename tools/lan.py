from __future__ import annotations

import configparser
import socket
import threading
from pathlib import Path

DEFAULT_CONFIG_FILE = Path("config.ini")
DEFAULT_TOPIC = "rvcrypto/graph"
CHARACTERIF_SERVICE_TYPE = "_characterif._tcp.local."

_ZEROCONF = None
_SERVICE_BROWSER = None
_LOCAL_SERVICE_INFO = None
_LOCAL_SERVICE_NAME = None
_DISCOVERED_PEERS = {}
_DISCOVERED_PEERS_LOCK = threading.Lock()


def load_config(config_path=DEFAULT_CONFIG_FILE):
    config = configparser.ConfigParser()
    config.read(Path(config_path))
    return config


def stream_type(config=None, config_path=DEFAULT_CONFIG_FILE):
    if config is None:
        config = load_config(config_path)

    value = config.get(
        "stream",
        "type",
        fallback="console",
    ).strip().lower()

    if value not in {"console", "mqtt"}:
        return "console"

    return value


def publish_mqtt(text, config=None, config_path=DEFAULT_CONFIG_FILE, topic=None):
    if config is None:
        config = load_config(config_path)

    try:
        import paho.mqtt.publish as publish
    except ImportError as exc:
        raise RuntimeError(
            "MQTT stream requested but paho-mqtt is not installed."
        ) from exc

    broker = config.get("lan-transport", "broker", fallback="localhost")
    port = config.getint("lan-transport", "port", fallback=1883)
    mqtt_topic = topic or config.get(
        "lan-transport",
        "topic",
        fallback=DEFAULT_TOPIC,
    )
    qos = config.getint("lan-transport", "qos", fallback=0)
    retain = config.getboolean("lan-transport", "retain", fallback=False)
    client_id = config.get(
        "lan-transport",
        "client_id",
        fallback="rvcrypto-stream",
    )
    username = config.get("lan-transport", "username", fallback="")
    password = config.get("lan-transport", "password", fallback="")

    auth = None
    if username:
        auth = {"username": username, "password": password}

    publish.single(
        topic=mqtt_topic,
        payload=text,
        qos=qos,
        retain=retain,
        hostname=broker,
        port=port,
        client_id=client_id,
        auth=auth,
    )


def stream(text, config=None, config_path=DEFAULT_CONFIG_FILE, topic=None):
    if config is None:
        config = load_config(config_path)

    transport = stream_type(config=config, config_path=config_path)

    if transport == "mqtt":
        publish_mqtt(
            text=text,
            config=config,
            config_path=config_path,
            topic=topic,
        )
    else:
        print(text)

    return transport


def get_local_address():
    """Return a useful IPv4 address for advertising this machine on the LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is sent. connect() only asks the OS which local interface
        # it would use for an ordinary private-network destination.
        sock.connect(("192.0.2.1", 9))
        address = sock.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass

    return "127.0.0.1"


def get_bind_address():
    """Address CharacterIF should bind to when accepting LAN connections."""
    return "0.0.0.0"


def _decode_properties(properties):
    decoded = {}
    for key, value in (properties or {}).items():
        if isinstance(key, bytes):
            key = key.decode("utf-8", errors="replace")
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        decoded[str(key)] = str(value)
    return decoded


def _peer_from_service_info(info):
    if info is None:
        return None

    properties = _decode_properties(info.properties)
    addresses = info.parsed_addresses()
    address = next((item for item in addresses if ":" not in item), None)
    if not address:
        return None

    return {
        "character": properties.get("character", ""),
        "node": properties.get("node", ""),
        "protocol": properties.get("protocol", "characterif/1"),
        "transport": "lan",
        "address": address,
        "port": info.port,
        "service_name": info.name,
    }


class _CharacterIFServiceListener:
    def add_service(self, zeroconf, service_type, name):
        self._remember(zeroconf, service_type, name)

    def update_service(self, zeroconf, service_type, name):
        self._remember(zeroconf, service_type, name)

    def remove_service(self, zeroconf, service_type, name):
        if name == _LOCAL_SERVICE_NAME:
            return
        with _DISCOVERED_PEERS_LOCK:
            peer = _DISCOVERED_PEERS.pop(name, None)
        if peer:
            print(
                "LAN character disappeared: "
                f"{peer.get('character') or peer.get('node') or name}"
            )

    def _remember(self, zeroconf, service_type, name):
        if name == _LOCAL_SERVICE_NAME:
            return

        info = zeroconf.get_service_info(service_type, name, timeout=1500)
        peer = _peer_from_service_info(info)
        if not peer:
            return

        with _DISCOVERED_PEERS_LOCK:
            previous = _DISCOVERED_PEERS.get(name)
            _DISCOVERED_PEERS[name] = peer

        if previous != peer:
            print(
                "LAN character discovered: "
                f"{peer.get('character') or peer.get('node')} "
                f"({peer['address']}:{peer['port']})"
            )


def start(character_name, node_name=None, port=8765):
    """Advertise this CharacterIF service and discover peers on the local LAN."""
    global _ZEROCONF, _SERVICE_BROWSER, _LOCAL_SERVICE_INFO, _LOCAL_SERVICE_NAME

    if _ZEROCONF is not None:
        return {
            "character": character_name,
            "node": node_name or socket.gethostname(),
            "address": get_local_address(),
            "port": int(port),
            "transport": "lan",
        }

    try:
        from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
    except ImportError as exc:
        raise RuntimeError(
            "CharacterIF LAN discovery requires the 'zeroconf' package. "
            "Install it with: pip install zeroconf"
        ) from exc

    node_name = node_name or socket.gethostname()
    address = get_local_address()
    safe_character = str(character_name).replace(".", "-")
    safe_node = str(node_name).replace(".", "-")
    service_name = f"{safe_character}@{safe_node}.{CHARACTERIF_SERVICE_TYPE}"

    _ZEROCONF = Zeroconf()
    _LOCAL_SERVICE_NAME = service_name
    _LOCAL_SERVICE_INFO = ServiceInfo(
        CHARACTERIF_SERVICE_TYPE,
        service_name,
        addresses=[socket.inet_aton(address)],
        port=int(port),
        properties={
            "character": str(character_name),
            "node": str(node_name),
            "protocol": "characterif/1",
        },
        server=f"{safe_node}.local.",
    )

    _ZEROCONF.register_service(_LOCAL_SERVICE_INFO)
    _SERVICE_BROWSER = ServiceBrowser(
        _ZEROCONF,
        CHARACTERIF_SERVICE_TYPE,
        _CharacterIFServiceListener(),
    )

    print(
        f"LAN discovery active: {character_name} "
        f"({address}:{int(port)})"
    )

    return {
        "character": str(character_name),
        "node": str(node_name),
        "address": address,
        "port": int(port),
        "transport": "lan",
    }


def stop():
    """Stop CharacterIF LAN advertisement and discovery."""
    global _ZEROCONF, _SERVICE_BROWSER, _LOCAL_SERVICE_INFO, _LOCAL_SERVICE_NAME

    if _SERVICE_BROWSER is not None:
        try:
            _SERVICE_BROWSER.cancel()
        except Exception:
            pass
        _SERVICE_BROWSER = None

    if _ZEROCONF is not None:
        if _LOCAL_SERVICE_INFO is not None:
            try:
                _ZEROCONF.unregister_service(_LOCAL_SERVICE_INFO)
            except Exception:
                pass
        _ZEROCONF.close()

    _ZEROCONF = None
    _LOCAL_SERVICE_INFO = None
    _LOCAL_SERVICE_NAME = None

    with _DISCOVERED_PEERS_LOCK:
        _DISCOVERED_PEERS.clear()


def get_peers():
    """Return a snapshot of currently discovered CharacterIF LAN peers."""
    with _DISCOVERED_PEERS_LOCK:
        return [dict(peer) for peer in _DISCOVERED_PEERS.values()]
