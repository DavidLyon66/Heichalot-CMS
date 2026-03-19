# addaistorytext.py

Lightweight utility for importing terminal-based AI conversations into the Heichalot CMS `story.md` format.

---

## Overview

`addaistorytext.py` is a small command-line tool that converts AI terminal transcripts (e.g. Gemma / Ollama sessions) into structured story blocks:

* `"""Narrator` → user prompt
* `"""Ai` → model response

The tool is designed to be:

* **fast** (clipboard-friendly)
* **minimal** (no heavy parsing logic)
* **safe** (preserves content, avoids rewriting files)
* **testable** (fully covered by pytest)

---

## Input Format

The tool expects transcripts using the familiar prompt style:

```
>>> What do you see?

I see a quiet concourse.

>>> Go back 500 years

The structure appears older.
```

### Multiline prompts

Wrapped prompts using continuation markers are supported:

```
>>> let's remote-view the conference where they decided which books w
... ould be included and which books not.
... let's examine the setting.
```

These are reconstructed into a single logical prompt:

```
let's remote-view the conference where they decided which books would be included and which books not. let's examine the setting.
```

---

## Output Format

The transcript is converted into CMS story blocks:

```
"""Narrator
What do you see?
"""

"""Ai
I see a quiet concourse.
"""
```

Each prompt/response pair becomes one block.

---

## Usage

### File input

```
python tools/addaistorytext.py transcript.txt
```

Appends parsed content to:

```
./story.md
```

---

### Clipboard mode

If no file is provided:

```
python tools/addaistorytext.py
```

You will be prompted:

```
Paste transcript (Ctrl-D to finish):
```

Paste content and press `Ctrl-D`.

---

### Story path override

```
python tools/addaistorytext.py transcript.txt --story /tmp/story.md
```

Useful for:

* testing
* alternate output locations
* batch processing

---

### Debate mode

```
python tools/addaistorytext.py --debate transcript.txt
```

Creates a new file:

```
./debate/YYYY-MM-DD_HH-MM-SS.md
```

With header:

```
---
origin: addaistorytext
timestamp: 2026-03-19T15:22:10
---
```

---

## Configuration

The tool reads from:

```
./heichalotcms/config.ini
```

Fallback:

```
./config.ini
```

### Example

```ini
[cms]
story_filename = story.md

[tags]
default_story_tags = remote-viewing
```

---

## Tags

If `default_story_tags` are defined, they are inserted into the story file once:

```
"""Tags
remote-viewing
```

Tags are only added if not already present.

---

## Parsing Rules

The parser follows simple rules:

| Pattern     | Meaning                  |
| ----------- | ------------------------ |
| `>>>`       | start Narrator block     |
| `...`       | continuation of Narrator |
| other lines | Ai response              |

### Continuation handling

The parser reconstructs wrapped prompts:

* `w` + `ould` → `would`
* `of` + `the setting` → `of the setting`

This is achieved using a lightweight heuristic based on trailing tokens.

---

## File Behaviour

### Story mode

* always **appends**
* never overwrites
* creates file if missing
* ensures parent directories exist

### Debate mode

* always creates a **new file**
* does not modify `story.md`

---

## Design Philosophy

This tool is intentionally minimal.

It does:

* convert transcripts → story blocks
* handle multiline prompts
* append safely

It does **not**:

* validate CMS structure
* rewrite files
* manage metadata beyond tags
* enforce formatting rules

---

## Testing

Fully covered by pytest:

```
pytest tests/test_addaistorytext.py
```

Test coverage includes:

* parsing (single/multiple turns)
* multiline continuation handling
* rendering output
* config loading
* tag insertion
* file writing
* CLI behavior

---

## Example Workflow

```
ollama run gemma
```

Copy terminal output, then:

```
python tools/addaistorytext.py
```

Paste → `Ctrl-D`

Result:

```
story.md updated instantly
```

---

## Notes

* Designed for real-world terminal output, not idealized text
* Handles common wrapping issues automatically
* Keeps logic small and maintainable

---

## Future Enhancements (Optional)

* strip spinner characters (`⠋ ⠙ ⠹`)
* remove ANSI color codes
* optional timestamp capture
* batch import support

---

## Summary

`addaistorytext.py` provides a fast, reliable bridge between:

```
AI terminal sessions → structured CMS stories
```

It is intentionally simple, robust, and optimized for daily use.
