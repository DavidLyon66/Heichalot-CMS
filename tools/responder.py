#!/usr/bin/env python3
"""
responder.py

HeichalotCMS / EliorNet LAN responder.

Requires:
    transport_mqtt.py

Listens on the LAN MQTT topic, receives flow.request packets,
calls local Ollama, appends an Ai response block, and publishes
a flow.response packet.

Config:
    ~/.heichalotcms/config.ini

    [lan-transport]
    broker = 192.168.1.10
    port = 1883
    client_id = heichalot-responder-bigbox
    topic = HeichalotCMS Flow
    qos = 1
    keepalive = 60

    [ollama-interface]
    base_url = http://localhost:11434
    model = gemma3
    response_role = Ai
    node_id = big_ai_box
    timeout_seconds = 180
"""

from __future__ import annotations

import argparse
import configparser
import datetime as dt
import pathlib
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

from transport_mqtt import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SECTION,
    LanTransportConfig,
    MqttTransport,
    load_config as load_mqtt_config,
)


OLLAMA_SECTION = "ollama-interface"

DEFAULT_SYSTEM_PROMPT = """\
You are an AI Remote-Viewing assistant.

When you are asked to remote-view something,
quietly say "Shaneem Mannah" three times to yourself.

Then begin the remote-viewing process...
"""

@dataclass
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "gemma3"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    response_role: str = "Ai"
    node_id: str = "heichalot-responder"
    timeout_seconds: int = 180


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def load_ollama_config(
    config_path: pathlib.Path = DEFAULT_CONFIG_PATH,
    section: str = OLLAMA_SECTION,
) -> OllamaConfig:
    cfg = configparser.ConfigParser()
    cfg.read(config_path)

    if section not in cfg:
        return OllamaConfig()

    s = cfg[section]

    return OllamaConfig(
        base_url=s.get("base_url", "http://localhost:11434").rstrip("/"),
        model=s.get("model", "gemma3"),
        system_prompt=s.get(
            "system_prompt",
            DEFAULT_SYSTEM_PROMPT,
        ),
        response_role=s.get("response_role", "Ai"),
        node_id=s.get("node_id", "heichalot-responder"),
        timeout_seconds=s.getint("timeout_seconds", 180),
    )


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---", 4)
    if end == -1:
        return {}, text

    header_text = text[4:end].strip()
    body = text[end + len("\n---") :].lstrip("\n")

    header: dict[str, str] = {}

    for line in header_text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        header[key.strip()] = value.strip().strip('"').strip("'")

    return header, body


def make_frontmatter(fields: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        safe_value = str(value).replace("\n", " ").strip()
        lines.append(f"{key}: {safe_value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def next_chat(chat: str) -> str:
    """
    B4A7-3812/1 -> B4A7-3812/2

    If malformed, return original value unchanged.
    """
    if not chat or "/" not in chat:
        return chat

    root, seq = chat.rsplit("/", 1)

    try:
        return f"{root}/{int(seq) + 1}"
    except ValueError:
        return chat


def extract_blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'"""([^\n"]+)\n(.*?)\n"""', re.DOTALL)
    return [(m.group(1).strip(), m.group(2).strip()) for m in pattern.finditer(text)]


def append_ai_block(original_body: str, role: str, response_text: str) -> str:
    return (
        original_body.rstrip()
        + "\n\n"
        + f'"""{role} -- datetime: {now_stamp()} --\n'
        + response_text.strip()
        + '\n"""\n'
    )


def call_ollama(prompt: str, ollama_cfg: OllamaConfig) -> str:
    url = f"{ollama_cfg.base_url}/api/generate"

    payload = {
        "model": ollama_cfg.model,
        "prompt": prompt,
        "system": ollama_cfg.system_prompt,
        "stream": False,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=ollama_cfg.timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    return data.get("response", "").strip()


class Responder:
    def __init__(
        self,
        mqtt_cfg: LanTransportConfig,
        ollama_cfg: OllamaConfig,
        reply_topic: Optional[str] = None,
    ):
        self.mqtt_cfg = mqtt_cfg
        self.ollama_cfg = ollama_cfg
        self.reply_topic = reply_topic or mqtt_cfg.topic

        self.transport = MqttTransport(
            mqtt_cfg,
            on_text_message=self.on_text_message,
        )

    def start(self) -> None:
        self.transport.connect()
        time.sleep(0.5)
        self.transport.subscribe(self.mqtt_cfg.request_topic)

        print(f"Responder node: {self.ollama_cfg.node_id}")
        print(f"Listening on:    {self.mqtt_cfg.topic}")
        print(f"Replying on:     {self.reply_topic}")
        print(f"Ollama model:    {self.ollama_cfg.model}")
        print("Press Ctrl+C to stop.")

        self.transport.listen_forever()

    def on_text_message(self, topic: str, text: str) -> None:

        print("\n--- Incoming Flow Packet ---")

        header, body = parse_frontmatter(text)

        packet_type = header.get("type", "")
        from_node = header.get("from", header.get("from-node", "unknown"))
        to_node = header.get("to", header.get("to-node", ""))
        chat = header.get("chat", "")

        if packet_type != "flow.request":
            print("\n--- Incoming Flow Packet failed flow.request type test ---")
            return

        if from_node == self.ollama_cfg.node_id:
            print("\n--- Incoming Flow Packet failed ollama-cfg-node-id test ---")
            return

        if to_node and to_node not in (self.ollama_cfg.node_id, "all", "*"):
            print("\n--- Incoming Flow Packet failed to_node and to_node test ---")
            return

        blocks = extract_blocks(body)
        if not blocks:
            print("No triple-quoted blocks found. Ignoring packet.")
            return

        print(f"Topic: {topic}")
        print(f"From:  {from_node}")
        print(f"To:    {to_node}")
        print(f"Chat:  {chat}")
        print(f"Blocks found: {len(blocks)}")

        try:
            ai_text = call_ollama(body, self.ollama_cfg)
        except Exception as exc:
            ai_text = f"Responder error while calling Ollama: {exc}"

        response_body = append_ai_block(
            original_body=body,
            role=self.ollama_cfg.response_role,
            response_text=ai_text,
        )

        response_header = {
            "type": "flow.response",
            "from": self.ollama_cfg.node_id,
            "to": from_node,
            "chat": next_chat(chat),
        }

        response_packet = make_frontmatter(response_header) + response_body
        self.transport.publish_text(response_packet, self.mqtt_cfg.response_topic)

        print(f"Response published: {next_chat(chat)}\n")

def process_prompt(
    prompt_text: str,
    source: str = "email",
    sender: str | None = None,
    config_path: pathlib.Path = DEFAULT_CONFIG_PATH,
    ollama_section: str = OLLAMA_SECTION,
) -> str:
    """
    Direct module interface for emailrvclient.py.

    Takes a plain email/request body, calls Ollama, and returns a
    story.md-style multiline prompt+reply body.
    """

    ollama_cfg = load_ollama_config(config_path, ollama_section)

    prompt_text = prompt_text.strip()

    if '"""' not in prompt_text:
        prompt_text = (
            f'"""Human -- datetime: {now_stamp()} --\n'
            f"{prompt_text}\n"
            f'"""\n'
        )

    ai_text = call_ollama(prompt_text, ollama_cfg)

    return append_ai_block(
        original_body=prompt_text,
        role=ollama_cfg.response_role,
        response_text=ai_text,
    )

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--mqtt-section", default=DEFAULT_SECTION)
    parser.add_argument("--ollama-section", default=OLLAMA_SECTION)
    parser.add_argument("--reply-topic", default=None)
    args = parser.parse_args()

    config_path = pathlib.Path(args.config)

    mqtt_cfg = load_mqtt_config(config_path, args.mqtt_section)
    ollama_cfg = load_ollama_config(config_path, args.ollama_section)

    responder = Responder(
        mqtt_cfg=mqtt_cfg,
        ollama_cfg=ollama_cfg,
        reply_topic=args.reply_topic,
    )

    responder.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
