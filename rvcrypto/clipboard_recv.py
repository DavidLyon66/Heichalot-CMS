#!/usr/bin/env python3
"""
clipboard_recv.py

Receive text from MQTT (sent by clipboard_send.py) and store it
locally — write to clipboard, file, or stdout.

Examples:

    # Listen once, write to clipboard, then exit
    python3 clipboard_recv.py --once

    # Listen once, write to file
    python3 clipboard_recv.py --once --output received.txt

    # Listen once, print to stdout
    python3 clipboard_recv.py --once --stdout

    # Keep listening, write every message to file
    python3 clipboard_recv.py --output received.txt

    # Keep listening, print to stdout
    python3 clipboard_recv.py --stdout

    # Custom topic
    python3 clipboard_recv.py --topic rvcrypto/clipboard

    # Write each message to a new timestamped file
    python3 clipboard_recv.py --archive
"""

import argparse
import configparser
import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE.parent / "config.ini"

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_TOPIC = "rvcrypto/clipboard"
DEFAULT_QOS = 0


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def write_clipboard(text):
    for cmd in (["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"]):
        try:
            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            continue

    return False


def write_file(path, text, append=False):
    mode = "a" if append else "w"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(mode, encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")

    return True


def archive_message(text, archive_dir):
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = Path(archive_dir) / f"msg_{now}.txt"
    return write_file(path, text, append=False)


class ClipboardReceiver:
    def __init__(
        self,
        broker,
        port,
        topic,
        qos,
        client_id,
        output_path=None,
        stdout=False,
        to_clipboard=True,
        once=False,
        archive=False,
        archive_dir=None,
        verbose=False,
    ):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.qos = qos
        self.client_id = client_id
        self.output_path = output_path
        self.stdout = stdout
        self.to_clipboard = to_clipboard
        self.once = once
        self.archive = archive
        self.archive_dir = archive_dir or str(BASE / "data" / "clipboard_archive")
        self.verbose = verbose
        self.running = True
        self.received = False

        self.client = None

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            if self.verbose:
                print(
                    f"Connected to {self.broker}:{self.port}, "
                    f"subscribing to {self.topic}"
                )
            client.subscribe(self.topic, qos=self.qos)
        else:
            print(
                f"Connection failed with code {rc}",
                file=sys.stderr,
            )

    def on_message(self, client, userdata, msg):
        try:
            text = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            text = msg.payload.decode("latin-1")

        if self.verbose:
            print(f"Received {len(text)} bytes on {msg.topic}")

        self.process(text)
        self.received = True

        if self.once:
            self.running = False
            client.disconnect()

    def process(self, text):
        saved_to = []

        if self.output_path:
            write_file(self.output_path, text, append=False)
            saved_to.append(f"file: {self.output_path}")

        if self.archive:
            archive_message(text, self.archive_dir)
            saved_to.append(f"archive: {self.archive_dir}")

        if self.to_clipboard:
            if write_clipboard(text):
                saved_to.append("clipboard")
            else:
                if self.verbose:
                    print(
                        "xclip/xsel not available, "
                        "skipping clipboard write",
                        file=sys.stderr,
                    )

        if self.stdout or not saved_to:
            print(text)
            saved_to.append("stdout")

        if self.verbose and saved_to:
            print(f"Saved to: {', '.join(saved_to)}")

    def run(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print(
                "Error: paho-mqtt not installed. "
                "Run: pip install paho-mqtt",
                file=sys.stderr,
            )
            sys.exit(1)

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        def handle_signal(sig, frame):
            self.running = False
            if self.client:
                self.client.disconnect()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            self.client.connect(self.broker, self.port, keepalive=60)
        except Exception as exc:
            print(
                f"Error connecting to {self.broker}:{self.port}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

        if self.verbose:
            print(f"Listening on {self.broker}:{self.port}/{self.topic}...")

        self.client.loop_start()

        while self.running:
            time.sleep(0.1)

        self.client.loop_stop()

        if self.once and not self.received:
            if self.verbose:
                print("No message received before disconnect.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Receive text from MQTT (sent by clipboard_send.py)"
    )

    parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help=f"MQTT broker hostname (default: {DEFAULT_BROKER})",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"MQTT broker port (default: {DEFAULT_PORT})",
    )

    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help=f"MQTT topic (default: {DEFAULT_TOPIC})",
    )

    parser.add_argument(
        "--qos",
        type=int,
        default=None,
        choices=[0, 1, 2],
        help=f"MQTT QoS level (default: {DEFAULT_QOS})",
    )

    parser.add_argument(
        "--client-id",
        type=str,
        default="rvcrypto-clipboard-recv",
        help="MQTT client ID",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Write received text to this file",
    )

    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print received text to stdout",
    )

    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Do not write to clipboard",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Receive one message and exit",
    )

    parser.add_argument(
        "--archive",
        action="store_true",
        help="Save each message to a timestamped file",
    )

    parser.add_argument(
        "--archive-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Directory for archived messages",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print connection and message details",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    config = load_config()

    broker = args.broker or config.get(
        "lan-transport", "broker", fallback=DEFAULT_BROKER
    )
    port = args.port or config.getint(
        "lan-transport", "port", fallback=DEFAULT_PORT
    )
    topic = args.topic or config.get(
        "lan-transport", "topic", fallback=DEFAULT_TOPIC
    )
    qos = args.qos if args.qos is not None else config.getint(
        "lan-transport", "qos", fallback=DEFAULT_QOS
    )

    receiver = ClipboardReceiver(
        broker=broker,
        port=port,
        topic=topic,
        qos=qos,
        client_id=args.client_id,
        output_path=args.output,
        stdout=args.stdout,
        to_clipboard=not args.no_clipboard,
        once=args.once,
        archive=args.archive,
        archive_dir=args.archive_dir,
        verbose=args.verbose,
    )

    receiver.run()


if __name__ == "__main__":
    main()
