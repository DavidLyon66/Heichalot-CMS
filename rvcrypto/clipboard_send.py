#!/usr/bin/env python3
"""
clipboard_send.py

Send clipboard content (or provided text) to MQTT on the LAN.

The receiver (clipboard_recv.py) picks it up on the other end.

Examples:

    # Send whatever is currently in the clipboard
    python3 clipboard_send.py

    # Send specific text
    python3 clipboard_send.py --text "BTC 78500.00"

    # Send contents of a file
    python3 clipboard_send.py --file screenshot.txt

    # Send with a custom topic
    python3 clipboard_send.py --topic rvcrypto/clipboard

    # Read from stdin
    echo "hello" | python3 clipboard_send.py --stdin
"""

import argparse
import configparser
import subprocess
import sys
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


def read_clipboard():
    for cmd in (["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"]):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            continue

    return None


def publish_mqtt(text, broker, port, topic, qos, retain, client_id):
    try:
        import paho.mqtt.publish as publish
    except ImportError:
        print(
            "Error: paho-mqtt not installed. "
            "Run: pip install paho-mqtt",
            file=sys.stderr,
        )
        sys.exit(1)

    auth = None

    publish.single(
        topic=topic,
        payload=text,
        qos=qos,
        retain=retain,
        hostname=broker,
        port=port,
        client_id=client_id,
        auth=auth,
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Send text to MQTT for receipt by clipboard_recv.py"
    )

    source = parser.add_mutually_exclusive_group()

    source.add_argument(
        "--text",
        type=str,
        help="Text to send",
    )

    source.add_argument(
        "--file",
        type=str,
        metavar="PATH",
        help="Send contents of a file",
    )

    source.add_argument(
        "--stdin",
        action="store_true",
        help="Read text from stdin",
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
        "--retain",
        action="store_true",
        default=False,
        help="Retain the message on the broker",
    )

    parser.add_argument(
        "--client-id",
        type=str,
        default="rvcrypto-clipboard-send",
        help="MQTT client ID",
    )

    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the text being sent",
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
    retain = args.retain or config.getboolean(
        "lan-transport", "retain", fallback=False
    )

    text = None

    if args.text:
        text = args.text
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        text = path.read_text(encoding="utf-8")
    elif args.stdin:
        text = sys.stdin.read()
    else:
        text = read_clipboard()
        if text is None:
            print(
                "Error: clipboard is empty or xclip/xsel not installed.\n"
                "Install xclip: sudo apt install xclip\n"
                "Or use --text, --file, or --stdin.",
                file=sys.stderr,
            )
            sys.exit(1)

    if not text or not text.strip():
        print("Error: no text to send.", file=sys.stderr)
        sys.exit(1)

    if args.show:
        print(f"Sending {len(text)} bytes to {broker}:{port}/{topic}")
        print("---")
        print(text)
        print("---")

    try:
        publish_mqtt(text, broker, port, topic, qos, retain, args.client_id)
        print(f"Sent {len(text)} bytes to {topic}")
    except Exception as exc:
        print(f"Error publishing to MQTT: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
