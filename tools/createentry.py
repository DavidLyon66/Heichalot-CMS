#!/usr/bin/env python3
from pathlib import Path
import argparse
import sys
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
import shutil

from rich.console import Console
from rich.prompt import Confirm

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None
    
console = Console()

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from config import (
    load_app_config,
    get_entry_prefix,
    get_entry_pad_width,
    get_template_path,
    get_last_id,
    set_last_id,
    resolve_entry_kind,
)


def prompt_if_missing(val: str | None, prompt_text: str) -> str:
    if val is not None and str(val).strip():
        return str(val).strip()
    return input(prompt_text).strip()


def render_story(template_path: Path, context: dict) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except Exception as e:
        raise SystemExit("ERROR: jinja2 not installed. Install with: pip install jinja2") from e

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(enabled_extensions=()),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template(template_path.name)
    return tmpl.render(**context)

def entry_type_defaults(cfg, entry_type: str) -> dict:
    entry_type = str(entry_type).strip().casefold()
    kind = resolve_entry_kind(cfg, entry_type)

    defaults = {
        "kind": kind,
    }

    if entry_type == "rv":
        defaults.update({
            "kind": "remote_viewing",
            "tags": ["remote-viewing"],
            "status": "Draft",
        })

    elif entry_type == "st":
        defaults.update({
            "kind": "historic_site",
            "tags": ["historic-site"],
            "status": "Draft",
        })

    elif entry_type == "v":
        defaults.update({
            "kind": "video",
            "tags": ["video"],
            "status": "Draft",
        })

    return defaults

def build_entry_fields(
    cfg,
    entry_type: str,
    fields: dict | None = None,
) -> dict:
    """
    Build the final template field dictionary for a new CMS entry.

    Entry-type defaults are applied first. Caller-supplied fields override
    those defaults.
    """

    final_fields = entry_type_defaults(
        cfg,
        entry_type,
    )

    if fields:
        final_fields.update(fields)

    if not final_fields.get("title"):
        final_fields["title"] = cfg.get(
            "new_entry",
            "default_title",
            fallback="Title",
        )

    final_fields.setdefault(
        "location_text",
        "",
    )

    if entry_type == 'st':
        final_fields.setdefault(
            "base_map",
            "",
        )

    final_fields.setdefault(
        "tags",
        [],
    )

    final_fields.setdefault(
        "status",
        "Draft",
    )

    return final_fields

def create_entry(
    entry_type: str,
    fields: dict | None = None,
    *,
    title: str | None = None,
    tags: Sequence[str] | str | None = None,
    body: str | None = None,
    conversation: Sequence[Mapping] | None = None,
    image: str | Path | None = None,
    images: Sequence[str | Path] | None = None,
    files: Sequence[str | Path] | None = None,
    yaml_fields: dict | None = None,
    config_path: str | Path | None = None,
    prefix: str | None = None,
    pad_width: int | None = None,
) -> tuple[str, Path, Path]:

    cfg, resolved_config_path, paths = load_app_config(
        config_path
    )

    cms_dir = paths.cms_dir
    cms_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    resolved_prefix = (
        prefix
        or get_entry_prefix(cfg)
    )

    resolved_pad = (
        pad_width
        or get_entry_pad_width(cfg)
    )

    last_id = get_last_id(cfg)
    next_id_num = last_id + 1

    entry_id = (
        f"{resolved_prefix}"
        f"{next_id_num:0{resolved_pad}d}"
    )

    entry_dir = (
        cms_dir / entry_id
    ).resolve()

    if entry_dir.exists():
        raise FileExistsError(
            f"Entry already exists: {entry_dir}"
        )

    #
    # Build template/YAML fields.
    #

    supplied_fields = dict(
        fields or {}
    )

    if yaml_fields:
        supplied_fields.update(
            yaml_fields
        )

    if title is not None:
        supplied_fields["title"] = (
            str(title).strip()
        )

    if tags is not None:

        if isinstance(tags, str):

            supplied_fields["tags"] = [
                item.strip()
                for item in tags.split(",")
                if item.strip()
            ]

        else:

            supplied_fields["tags"] = [
                str(item).strip()
                for item in tags
                if str(item).strip()
            ]

    final_fields = build_entry_fields(
        cfg,
        entry_type,
        supplied_fields,
    )

    now = datetime.now(
        timezone.utc
    )

    final_fields["entry_id"] = entry_id

    final_fields["created_utc"] = (
        now.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )

    final_fields["entry_type"] = (
        entry_type
    )

    if not final_fields.get("year"):
        final_fields["year"] = now.year

    if not final_fields.get("datetime"):
        final_fields["datetime"] = (
            f"{int(final_fields['year']):04d}-01-01"
        )

    template_path = get_template_path(
        cfg
    )

    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}"
        )

    #
    # Create entry directory structure.
    #

    images_dir = (
        entry_dir / "images"
    )

    files_dir = (
        entry_dir / "files"
    )

    images_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    #
    # Render the normal CMS story template.
    #

    story_path = (
        entry_dir / "story.md"
    )

    story_text = render_story(
        template_path,
        final_fields,
    )

    story_text = (
        story_text.rstrip()
        + "\n\n"
        + "Write the story here.\n"
    )

    #
    # Optional caller-supplied body/conversation.
    #

    extra_body = build_story_body(
        body=body,
        conversation=conversation,
    )

    if extra_body:

        story_text = (
            story_text.rstrip()
            + "\n\n"
            + extra_body
            + "\n"
        )

    story_path.write_text(
        story_text,
        encoding="utf-8",
    )

    #
    # Optional Image
    #
    if image:
        copy_primary_image(image, entry_dir, )
    
    #
    # Optional assets.
    #

    copy_entry_files(
        images,
        images_dir,
    )

    if files:
        copy_entry_files(
            files,
            files_dir,
        )

    #
    # Only advance last_id after the entry has
    # successfully been written.
    #

    set_last_id(
        cfg,
        next_id_num,
        resolved_config_path,
    )

    return (
        entry_id,
        entry_dir,
        story_path,
    )
        
def conversation_to_story_text(
    conversation: Sequence[Mapping] | None,
    *,
    include_datetime: bool = True,
) -> str:
    """
    Convert conversation messages into Heichalot story.md transcript blocks.

    Expected input:

        [
            {
                "role": "Narrator",
                "content": "Remote-view this place..."
            },
            {
                "role": "Ai",
                "content": "The strongest impression is..."
            },
        ]

    Empty or malformed messages are ignored.

    Returns plain text only. Nothing is written to disk.
    """

    if not conversation:
        return ""

    blocks: list[str] = []

    for message in conversation:

        if not isinstance(message, Mapping):
            continue

        role = str(
            message.get("role", "")
        ).strip()

        content = str(
            message.get("content", "")
        ).strip()

        if not role or not content:
            continue

        # Normalise common role names into the CMS convention.
        role_key = role.casefold()

        if role_key in {
            "user",
            "human",
            "narrator",
        }:
            role = "Narrator"

        elif role_key in {
            "assistant",
            "ai",
        }:
            role = "Ai"

        timestamp = (
            message.get("datetime")
            or message.get("created_at")
            or ""
        )

        if include_datetime:

            if timestamp:
                heading = (
                    f'"""{role} -- datetime: {timestamp} --'
                )
            else:
                heading = f'"""{role}'

        else:
            heading = f'"""{role}'

        block = (
            f"{heading}\n\n"
            f"{content}\n"
            f'"""'
        )

        blocks.append(block)

    return "\n\n".join(blocks)

def build_story_body(
    body: str | None = None,
    conversation: Sequence[Mapping] | None = None,
) -> str:
    """
    Build additional story.md body content.

    Explicit body text is retained first. Conversation text is appended
    afterwards.

    This function only returns text and performs no filesystem operations.
    """

    parts: list[str] = []

    if body:
        body_text = str(body).strip()

        if body_text:
            parts.append(body_text)

    conversation_text = conversation_to_story_text(
        conversation
    )

    if conversation_text:
        parts.append(conversation_text)

    return "\n\n".join(parts)
    
def copy_entry_files(
    sources: Sequence[str | Path] | None,
    destination: Path,
) -> list[Path]:
    """
    Copy existing files into an entry subdirectory.

    Missing files raise FileNotFoundError rather than being silently ignored.
    """

    copied: list[Path] = []

    if not sources:
        return copied

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    for source in sources:

        source_path = Path(
            source
        ).expanduser().resolve()

        if not source_path.is_file():
            raise FileNotFoundError(
                f"Entry asset not found: {source_path}"
            )

        target = destination / source_path.name

        shutil.copy2(
            source_path,
            target,
        )

        copied.append(target)

    return copied

def copy_primary_image(
    source: str | Path | None,
    entry_dir: Path,
) -> Path | None:
    """
    Copy the primary story image beside story.md.

    This is separate from images/, because renderhtml.py treats an image
    in the entry directory as the story illustration/preview image.
    """

    if not source:
        return None

    source_path = Path(
        source
    ).expanduser().resolve()

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Story image not found: {source_path}"
        )

    target = (
        entry_dir / source_path.name
    )

    shutil.copy2(
        source_path,
        target,
    )

    return target
    
def delete_entry(
    entry_id: str,
    *,
    config_path: str | Path | None = None,
) -> Path:
    """
    Permanently delete one CMS entry directory and everything inside it.
    """

    cfg, _cfg_path, paths = load_app_config(
        config_path
    )

    cms_dir = paths.cms_dir.resolve()

    entry_id = str(entry_id).strip()

    if not entry_id:
        raise ValueError(
            "Entry ID cannot be empty"
        )

    # Prevent callers from supplying paths such as ../../something.
    if Path(entry_id).name != entry_id:
        raise ValueError(
            f"Entry ID must be a directory name: {entry_id!r}"
        )

    entry_dir = (
        cms_dir / entry_id
    ).resolve()

    # Additional containment check.
    if entry_dir.parent != cms_dir:
        raise ValueError(
            f"Entry is outside CMS directory: {entry_dir}"
        )

    if not entry_dir.exists():
        raise FileNotFoundError(
            f"CMS entry does not exist: {entry_dir}"
        )

    if not entry_dir.is_dir():
        raise ValueError(
            f"CMS entry is not a directory: {entry_dir}"
        )

    if send2trash is not None:
        send2trash(str(entry_dir))
    else:
        shutil.rmtree(entry_dir)

    return entry_dir
                
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Create a new CMS entry directory using the Heichalot-CMS config."
    )
    ap.add_argument("entry_type", nargs="?", help="Short entry type code such as n, rv, v, yt, st")
    ap.add_argument("title", nargs="?", help="Entry title")
    ap.add_argument("--location", help="Location text")
    ap.add_argument("--year", type=int, help="Year only, e.g. 1857")
    ap.add_argument("--config", default=None, help="Optional override path to config.ini")
    ap.add_argument("--prefix", default=None, help="Entry prefix override")
    ap.add_argument("--pad", type=int, default=None, help="Numeric padding width override")
    ap.add_argument("--delete-entry", metavar="ENTRY_ID", help="Permanently delete an entire CMS entry directory",)
    ap.add_argument("--body-text", help="Body text to append to the new story.md", )
    ap.add_argument("--image", type=Path, help="Primary story image to copy beside story.md", )    
    
    args = ap.parse_args()

    cfg, cfg_path, paths = load_app_config(args.config)

    cms_dir = paths.cms_dir
    
    if args.delete_entry:

        entry_id = args.delete_entry.strip()

        console.print()
        console.print(
            f"[bold red]WARNING: Permanently delete {entry_id}?[/bold red]"
        )

        console.print(
            "[red]"
            "This will delete all files entirely from the CMS entry directory."
            "[/red]"
        )

        console.print()

        confirmed = Confirm.ask(
            "[bold red]Are you sure?[/bold red]",
            default=False,
        )

        if not confirmed:
            console.print(
                "[yellow]Deletion cancelled.[/yellow]"
            )
            return 0

        try:
            deleted_path = delete_entry(
                entry_id,
                config_path=args.config,
            )

        except (ValueError, FileNotFoundError) as exc:
            console.print(
                f"[bold red]ERROR:[/bold red] {exc}"
            )
            return 1

        console.print()
        console.print(
            f"[bold red]Deleted:[/bold red] {deleted_path}"
        )

        return 0    
    
    cms_dir.mkdir(parents=True, exist_ok=True)

    #
    # Fast entry creation.
    #
    # Supplying --body-text or --image uses the newer create_entry()
    # library interface and avoids the older interactive CLI construction.
    #

    if args.body_text is not None or args.image is not None:

        if not args.entry_type:
            raise SystemExit(
                "ERROR: entry_type is required"
            )

        if not args.title:
            raise SystemExit(
                "ERROR: title is required"
            )

        fields = {}

        if args.location:
            fields["location_text"] = args.location

        if args.year is not None:
            fields["year"] = args.year
            fields["datetime"] = (
                f"{args.year:04d}-01-01"
            )

        try:
            entry_id, entry_dir, story_path = create_entry(
                args.entry_type,
                fields=fields,
                title=args.title,
                body=args.body_text,
                image=args.image,
                config_path=args.config,
                prefix=args.prefix,
                pad_width=args.pad,
            )

        except (
            FileNotFoundError,
            FileExistsError,
            ValueError,
        ) as exc:
            console.print(
                f"[bold red]ERROR:[/bold red] {exc}"
            )
            return 1

        console.print()
        console.print(
            f"[bold green]Created:[/bold green] {entry_id}"
        )
        console.print(
            f"Story:  {story_path}"
        )

        if args.image:
            console.print(
                f"Image:  {entry_dir / args.image.name}"
            )

        return 0
        
    prefix = args.prefix or get_entry_prefix(cfg)
    pad_width = args.pad or get_entry_pad_width(cfg)

    last_id = get_last_id(cfg)
    next_id_num = last_id + 1
    entry_id = f"{prefix}{next_id_num:0{pad_width}d}"
    entry_dir = (cms_dir / entry_id).resolve()

    if entry_dir.exists():
        raise SystemExit(f"ERROR: Entry already exists: {entry_dir}")

    images_dir = entry_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    template_path = get_template_path(cfg)
    if not template_path.exists():
        raise SystemExit(f"ERROR: Template not found: {template_path}")

    entry_kind = resolve_entry_kind(cfg, args.entry_type)

    entry_title = (
        args.title.strip()
        if args.title
        else cfg.get("new_entry", "default_title", fallback="Title")
    )

    location_text = prompt_if_missing(args.location, "Location (e.g. singapore): ")

    year_val = args.year
    if year_val is None:
        year_str = prompt_if_missing(None, "Year (e.g. 1857): ")
        try:
            year_val = int(year_str)
        except ValueError:
            raise SystemExit("ERROR: Year must be an integer like 1857")

    datetime_iso = f"{year_val:04d}-01-01"
    created_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    story_text = render_story(
        template_path,
        {
            "entry_id": entry_id,
            "created_utc": created_utc,
            "location_text": location_text,
            "datetime": datetime_iso,
            "year": year_val,
            "kind": entry_kind,
            "title": entry_title,
            "entry_type": args.entry_type or "",
            "base_map": "",
        },
    )

    (entry_dir / "story.md").write_text(story_text, encoding="utf-8")

    set_last_id(cfg, next_id_num, cfg_path)

    print(entry_id)
    print(f"Created: {entry_dir}")
    print(f"Images:  {images_dir}")
    print(f"Kind:    {entry_kind}")
    print(f"Title:   {entry_title}")
    print(f"Updated {cfg_path}: last_id = {next_id_num}")
    print("\nNext:")
    print(f"cd {entry_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
