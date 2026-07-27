#!/usr/bin/env python3
"""
Core remote-viewing responder.

This first version provides a stable interface for the Flask server,
command-line use, and future local-model responders.

For now, mock mode returns one random response from a small built-in
paragraph list. The real local Gemma/Ollama responder will replace the
non-mock branch later without changing callers.
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from config import default_config_path, load_app_config
from responder import process_prompt

def _config_api(cfg: Any) -> str:
    api = cfg.get(
        "remoteviewing",
        "api",
        fallback="ollama",
    ).strip().lower()

    supported = {
        "ollama",
        "http",
    }

    if api not in supported:
        raise ValueError(
            f"Unsupported [remoteviewing] api value: {api!r}. "
            f"Expected one of: {', '.join(sorted(supported))}"
        )

    return api
   
   
def _config_http_url(cfg: Any) -> str | None:
    url = cfg.get(
        "remoteviewing",
        "http_url",
        fallback="",
    ).strip()

    return url or None
    
    
MOCK_REMOTE_VIEW_ANSWERS: tuple[str, ...] = (
    (
        "The first impression is of a broad open area with a strong sense of "
        "distance. There appears to be a hard surface in the foreground and "
        "a softer, less defined region beyond it. The atmosphere feels quiet, "
        "with no immediate sense of urgency."
    ),
    (
        "I am getting an impression of vertical structures grouped closely "
        "together. Some parts feel metallic or reflective, while others seem "
        "older and more weathered. There may be movement nearby, but it is "
        "intermittent rather than continuous."
    ),
    (
        "The scene feels enclosed at first, although there may be an opening "
        "towards one side. The dominant colours seem muted, with darker tones "
        "around the edges and a lighter area near the centre. There is a sense "
        "of waiting or observation."
    ),
    (
        "My attention is drawn to something circular or curved. It may be part "
        "of a larger structure rather than a separate object. The surrounding "
        "space feels cool and slightly damp, with irregular textures and a "
        "faint impression of flowing water."
    ),
    (
        "The strongest signal is a contrast between a dense foreground and a "
        "more open background. There could be several people present, although "
        "they are not the main focus. The location feels active but organised."
    ),
    (
        "There is an impression of height and layered space. The lower area "
        "feels solid and structured, while the upper region is lighter and "
        "more exposed. A narrow route or passage seems to connect the two."
    ),
    (
        "The target suggests repeated shapes arranged in a loose pattern. "
        "There is a mixture of natural and constructed texture, with one area "
        "standing out because it is smoother, brighter, or more reflective "
        "than everything around it."
    ),
    (
        "The initial signal is quiet but persistent: a confined place, a "
        "central object, and activity occurring just outside the main focus. "
        "The scene seems functional rather than decorative, and the strongest "
        "impression is of something being examined or prepared."
    ),
)


def _normalise_conversation(
    conversation: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return a plain, serialisable copy of supplied conversation messages."""

    if conversation is None:
        return []

    normalised: list[dict[str, Any]] = []

    for item in conversation:
        if not isinstance(item, Mapping):
            continue

        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()

        if not role or not content:
            continue

        normalised.append(
            {
                "role": role,
                "content": content,
            }
        )

    return normalised

def generate_remote_view(
    prompt: str,
    conversation: Sequence[Mapping[str, Any]] | None = None,
    *,
    api: str | None = None,
) -> dict[str, Any]:
    """
    Generate the next remote-viewing response.

    Parameters
    ----------
    prompt:
        The user's latest remote-viewing request.

    conversation:
        Existing conversation messages. The first version records the
        conversation length but does not use its contents to choose a mock
        response.

    mock:
        True forces a mock response. False requests the future live responder.
        None uses the [remote_viewing] mock setting from config.ini, defaulting
        to true while the real responder is not yet connected.

    Returns
    -------
    dict
        A stable response object. Callers should display ``result["text"]``.
    """

    prompt_text = str(prompt).strip()

    if not prompt_text:
        raise ValueError("prompt cannot be empty")

    conversation_items = _normalise_conversation(conversation)

    config_path = default_config_path()
    cfg, resolved_config_path, paths = load_app_config(config_path)

    use_mock = _config_mock_enabled(cfg) if mock is None else bool(mock)

    if api == "mock":
		#
		# Mock responder delay.
		# Simulates a local LLM thinking so the UI can be developed.
		#
        time.sleep(random.uniform(3.0, 10.0))
        answer_text = random.choice(MOCK_REMOTE_VIEW_ANSWERS)
    
        return {
            "text": answer_text,
            "role": "assistant",
            "mode": "mock",
            "model": "mock-paragraph-list",
            "prompt": prompt_text,
            "conversation_length": len(conversation_items),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config_path": str(resolved_config_path),
            "project_root": str(paths.project_root),
        }

    if api == "ollama":
		
        return process_prompt(
            prompt_text=prompt_text,
            source="remoteviewing",
            config_path=Path(settings["config_path"]),
            ollama_section=settings.get("ollama_section", "ollama-interface"),
        )

    if api == "remote":
        raise RuntimeError(
            "No live remote-viewing responder is not connected yet. "
        )

    raise RuntimeError(
        "No live remote-viewing responder is not connected yet. "
    )


def parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one remote-viewing response."
    )

    parser.add_argument(
        "prompt",
        help='Remote-viewing request, for example: "Let\'s remote-view the old house"',
    )

    mode_group = parser.add_mutually_exclusive_group()

    mode_group.add_argument(
        "--mock",
        action="store_true",
        help="Return a temporary random mock response.",
    )

    mode_group.add_argument(
        "--ollama",
        action="store_true",
        help="Use the local Ollama responder.",
    )

    mode_group.add_argument(
        "--http",
        metavar="URL",
        help=(
            "Use the hosted HTTP responder and override "
            "[remoteviewing] api from config.ini."
        ),
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete result object as JSON.",
    )

    return parser.parse_args(argv)

def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = parse_args(argv)

    try:
        config_path = default_config_path()
        cfg, resolved_config_path, _paths = load_app_config(config_path)
    
        api = _config_api(cfg)
        api_url = _config_http_url(cfg)

        # Deliberate command-line overrides.
        if args.mock:
            api = "mock"
        elif args.ollama:
            api = "ollama"
        elif args.http:
            api = "http"
            api_url = args.http
    
        result = generate_remote_view(
            prompt=args.prompt,
            conversation=[],
            api=api,
            api_url=args.http,
        )

    except (ValueError, RuntimeError) as exc:
        print(f"remoteviewing: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["text"])

    return 0
    
if __name__ == "__main__":
    raise SystemExit(main())
