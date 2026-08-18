from __future__ import annotations

import configparser
from pathlib import Path

DEFAULT_CONFIG_FILE = Path("config.ini")
DEFAULT_TOPIC = "rvcrypto/graph"


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
