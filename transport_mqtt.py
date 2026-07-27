#!/usr/bin/env python3
"""
transport_mqtt.py

Small MQTT transport layer for HeichalotCMS / EliorNet LAN flow.

Responsibilities:
    - Read ~/.heichalotcms/config.ini [lan-transport]
    - Connect to MQTT broker using Paho MQTT v2 callback API
    - Publish UTF-8 text packets
    - Subscribe and dispatch UTF-8 text packets to a callback

It does NOT understand:
    - YAML
    - chat ids
    - Ollama
    - flow.request / flow.response

Config example:

    [lan-transport]
    broker = 192.168.1.10
    port = 1883
    client_id = heichalot-controller
    username =
    password =
    topic = HeichalotCMS Flow
    qos = 1
    keepalive = 60
    debug = yes
    mqtt_version = 5

Basic test:

    # terminal 1
    python3 transport_mqtt.py --listen

    # terminal 2
    python3 transport_mqtt.py --text 'hello from mqtt'
"""

from __future__ import annotations

import argparse
import configparser
import pathlib
import sys
import time
import socket
import ipaddress
from typing import Callable, Optional, Dict, Any

import psutil
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.table import Table

from dataclasses import dataclass
from typing import Callable, Optional

import paho.mqtt.client as mqtt

DEFAULT_CONFIG_PATH = pathlib.Path.home() / ".heichalotcms" / "config.ini"
DEFAULT_SECTION = "lan-transport"
DEFAULT_TOPIC = "HeichalotCMS Flow"
request_topic: str = DEFAULT_TOPIC + "/requests"
response_topic: str = DEFAULT_TOPIC + "/responses"

console = Console()

@dataclass
class LanTransportConfig:
    broker: str = "localhost"
    port: int = 1883
    client_id: str = "heichalot-mqtt-client"
    username: str = ""
    password: str = ""
    topic: str = DEFAULT_TOPIC
    request_topic: str = DEFAULT_TOPIC + "/requests"
    response_topic: str = DEFAULT_TOPIC + "/responses"
    qos: int = 1
    keepalive: int = 60
    debug: bool = False
    mqtt_version: int = 5

def load_config(
    config_path: pathlib.Path = DEFAULT_CONFIG_PATH,
    section: str = DEFAULT_SECTION,
) -> LanTransportConfig:
    cfg = configparser.ConfigParser()
    cfg.read(config_path)

    if section not in cfg:
        return LanTransportConfig()

    s = cfg[section]

    return LanTransportConfig(
        broker=s.get("broker", "localhost"),
        port=s.getint("port", 1883),
        client_id=s.get("client_id", "heichalot-mqtt-client"),
        username=s.get("username", ""),
        password=s.get("password", ""),
        topic=s.get("topic", DEFAULT_TOPIC),
        request_topic=s.get("request_topic", s.get("topic", DEFAULT_TOPIC) + "/requests"),
        response_topic=s.get("response_topic", s.get("topic", DEFAULT_TOPIC) + "/responses"),
        qos=s.getint("qos", 1),
        keepalive=s.getint("keepalive", 60),
        debug=s.getboolean("debug", False),
        mqtt_version=s.getint("mqtt_version", 5),
    )

def save_config_broker(
    broker: str,
    config_path: pathlib.Path = DEFAULT_CONFIG_PATH,
    section: str = DEFAULT_SECTION,
) -> None:
    cfg = configparser.ConfigParser()
    cfg.read(config_path)

    if section not in cfg:
        cfg[section] = {}

    cfg[section]["broker"] = broker

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with config_path.open("w", encoding="utf-8") as f:
        cfg.write(f)

class MqttTransport:
    def __init__(
        self,
        config: LanTransportConfig,
        on_text_message: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config
        self.on_text_message = on_text_message
        self.connected = False

        protocol = mqtt.MQTTv5 if config.mqtt_version == 5 else mqtt.MQTTv311

        self.tx_count = 0
        self.rx_count = 0
        self.connect_count = 0
        self.last_topic = "-"

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=config.client_id,
            protocol=protocol,
        )

        if config.username:
            self.client.username_pw_set(
                config.username,
                config.password or None,
            )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_publish = self._on_publish
        self.client.on_subscribe = self._on_subscribe

    def connect(self, wait: bool = True, timeout: float = 5.0) -> None:
        if self.config.debug:
            print(
                f"MQTT connecting async: "
                f"{self.config.broker}:{self.config.port}"
            )

        self.client.connect_async(
            self.config.broker,
            self.config.port,
            self.config.keepalive,
        )
        self.client.loop_start()

        if wait:
            self.wait_connected(timeout=timeout)

    def wait_connected(self, timeout: float = 5.0) -> bool:
        start = time.time()

        while not self.connected:
            if time.time() - start >= timeout:
                raise TimeoutError(
                    f"MQTT connection timeout: "
                    f"{self.config.broker}:{self.config.port}"
                )
            time.sleep(0.05)

        return True

    def is_connected(self) -> bool:
        return self.connected

    def disconnect(self) -> None:
        if self.config.debug:
            print("MQTT disconnecting")

        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()

    def publish_text(
        self,
        text: str,
        topic: Optional[str] = None,
        retain: bool = False,
        wait: bool = True,
    ) -> None:
        publish_topic = topic or self.config.topic

        if self.config.debug:
            print(f"MQTT TX: {publish_topic} ({len(text.encode('utf-8'))} bytes)")

        info = self.client.publish(
            publish_topic,
            payload=text.encode("utf-8"),
            qos=self.config.qos,
            retain=retain,
        )

        if wait:
            info.wait_for_publish(timeout=5.0)

            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                self.tx_count += 1
                self.last_topic = publish_topic
            else:
                raise RuntimeError(f"MQTT publish failed with rc={info.rc}")

    def subscribe(self, topic: Optional[str] = None) -> None:
        subscribe_topic = topic or self.config.topic

        if self.config.debug:
            print(f"MQTT subscribe: {subscribe_topic}")

        self.client.subscribe(
            subscribe_topic,
            qos=self.config.qos,
        )

    def listen_forever(self) -> None:
        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            console.print(
                "[yellow]Stopping MQTT listener.[/yellow]"
            )
        finally:
            self.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = True

        self.connect_count += 1

        console.print(self.status_panel())

        if self.connect_count > 5:
            console.print(
                "[yellow]Warning:[/yellow] MQTT reconnected. "
                "Check for duplicate client_id or broker/network resets."
            )

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ):
        self.connected = False

        console.print(f"[red]MQTT disconnected[/red] reason={reason_code}")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if self.config.debug:
            print(f"MQTT subscribed: mid={mid}, reason_codes={reason_codes}")

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        if self.config.debug:
            print(f"MQTT published: mid={mid}, reason={reason_code}")

    def _on_message(self, client, userdata, message):
        try:
            text = message.payload.decode("utf-8")

            self.rx_count += 1
            self.last_topic = message.topic

        except UnicodeDecodeError:
            print(f"MQTT RX non-UTF8 payload on {message.topic}", file=sys.stderr)
            return

        if self.config.debug:
            print(f"MQTT RX: {message.topic} ({len(message.payload)} bytes)")

        if self.on_text_message:
            self.on_text_message(message.topic, text)
        else:
            print("\n--- MQTT MESSAGE RECEIVED ---")
            print(f"Topic: {message.topic}")
            print(text)
            print("--- END MESSAGE ---\n")

    @staticmethod
    def mqtt_port_open(host: str, port: int = 1883, timeout: float = 0.2) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    @classmethod
    def autodetect_brokers(
        cls,
        port: int = 1883,
        timeout: float = 0.2,
        scan_lan: bool = True,
        max_hosts_per_network: int = 254,
    ) -> Dict[str, Dict[str, Any]]:
        found: Dict[str, Dict[str, Any]] = {}

        console.print("[cyan]Checking localhost for MQTT broker...[/cyan]")

        if cls.mqtt_port_open("127.0.0.1", port, timeout):
            found["127.0.0.1"] = {
                "host": "127.0.0.1",
                "port": port,
                "source": "localhost",
                "interface": "lo",
            }

        if not scan_lan:
            return found

        with console.status(
            "[cyan]Scanning local network for MQTT brokers...[/cyan]"
        ):

#       console.print("[cyan]Scanning local interfaces for MQTT brokers...[/cyan]")

            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family != socket.AF_INET:
                        continue

                    local_ip = addr.address
                    netmask = addr.netmask

                    if not local_ip or not netmask or local_ip.startswith("127."):
                        continue

                    try:
                        network = ipaddress.ip_network(
                            f"{local_ip}/{netmask}",
                            strict=False,
                        )
                    except ValueError:
                        continue

                    if network.num_addresses > max_hosts_per_network + 2:
                        console.print(
                            f"[yellow]Skipping large network {network} on {iface}[/yellow]"
                        )
                        continue

                    console.print(
                        f"[blue]Scanning {network} on {iface} from {local_ip}...[/blue]"
                    )

                    for candidate in network.hosts():
                        candidate_ip = str(candidate)

                        if cls.mqtt_port_open(candidate_ip, port, timeout):
                            found[candidate_ip] = {
                                "host": candidate_ip,
                                "port": port,
                                "source": "lan",
                                "interface": iface,
                                "network": str(network),
                                "local_ip": local_ip,
                            }
                            console.print(
                                f"[green]Found MQTT broker:[/green] {candidate_ip}:{port}"
                            )

        return found

    @staticmethod
    def choose_broker(found: Dict[str, Dict[str, Any]]) -> Optional[str]:
        if not found:
            console.print("[red]No MQTT brokers found.[/red]")
            return None

        keys = list(found.keys())

        for i, host in enumerate(keys, start=1):
            info = found[host]
            console.print(
                f"[{i}] [green]{host}:{info['port']}[/green] "
                f"({info['source']}, {info.get('interface', '-')})"
            )

        choice = Prompt.ask(
            "Select MQTT broker",
            choices=[str(i) for i in range(1, len(keys) + 1)],
            default="1",
        )

        return keys[int(choice) - 1]

    def status_panel(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="cyan")
        table.add_column(style="green")

        table.add_row("MQTT Broker", f"{self.config.broker}:{self.config.port}")
        table.add_row("Connected", "YES" if self.connected else "NO")
        table.add_row("Client ID", self.config.client_id)
        table.add_row("Topic", self.config.topic)
        table.add_row("Messages TX", str(self.tx_count))
        table.add_row("Messages RX", str(self.rx_count))
        table.add_row("Connects", str(self.connect_count))
        table.add_row("Last Topic", self.last_topic)

        return Panel(
            table,
            title="Heichalot LAN Flow Daemon",
            border_style="green" if self.connected else "yellow",
        )

def print_message(topic: str, text: str) -> None:
    console.rule("[bold blue]HeichalotCMS MQTT Packet[/bold blue]")
    console.print(f"Topic: {topic}")
    console.print(text)
    console.print("--- End Packet ---\n")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--section", default=DEFAULT_SECTION)

    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--listen", action="store_true")
    mode.add_argument("--send", help="Send a text/markdown packet file")
    mode.add_argument("--text", help="Send inline text packet")
    mode.add_argument("--autodetect", action="store_true")

    parser.add_argument("--topic", help="Override MQTT topic")
    parser.add_argument("--retain", action="store_true")

    args = parser.parse_args()

    config = load_config(
        pathlib.Path(args.config),
        args.section,
    )

    if not (args.listen or args.send or args.text or args.autodetect):
        args.listen = True

    if args.autodetect:
        found = MqttTransport.autodetect_brokers(port=config.port)
        broker = MqttTransport.choose_broker(found)

        if broker:
            console.print(f"Selected broker: [bold green]{broker}[/bold green]")
            save_config_broker(
                broker,
                pathlib.Path(args.config),
                args.section,
            )
            console.print(
                f"Updated config: [cyan]{args.config}[/cyan] "
                f"[{args.section}] broker = {broker}"
            )

        return 0

    transport = MqttTransport(
        config,
        on_text_message=print_message,
    )

    try:
        transport.connect(wait=True)

        if args.listen:
            transport.subscribe(args.topic or config.topic)
            console.print(
                f"[green]Listening[/green] on topic: "
                f"[cyan]{args.topic or config.topic}[/cyan]"
            )
            transport.listen_forever()
            return 0

        if args.send:
            path = pathlib.Path(args.send)
            if not path.exists():
                print(f"File not found: {path}", file=sys.stderr)
                return 1

            text = path.read_text(encoding="utf-8")
            transport.publish_text(
                text,
                topic=args.topic or config.topic,
                retain=args.retain,
            )

            # Give the background network loop a moment to send.
            time.sleep(0.2)
            return 0

        if args.text:
            transport.publish_text(
                args.text,
                topic=args.topic or config.topic,
                retain=args.retain,
            )

            # Give the background network loop a moment to send.
            time.sleep(0.2)
            return 0

        return 0

    finally:
        transport.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())