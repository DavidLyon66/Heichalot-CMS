# renderpdf.py

`renderpdf.py` renders a `story.md` entry into a readable PDF using ReportLab.

It is designed for fast production use in Heichalot-CMS and supports both dialogue-style
stories and plain prose stories.

## Features

- Uses the current directory as the default input when no path is given
- Writes output beside the entry, not into an `output/` subdirectory
- Uses the story title as the default PDF filename
- Supports both:
  - dialogue stories with triple-quoted speaker blocks
  - prose stories with normal paragraphs after the title
- Automatically inserts an illustration image under the title
- Supports optional heading color palettes
- Supports optional image alignment and height
- Displays front-matter fields under the title

## Supported story formats

### Dialogue-style

```md
---
entry_id: entry-0000013
location_text: Romania/Romanian Pyramids
datetime: 2026-01-01
status: Draft
---

# Remote-Viewing the Romanian Pyramids

"""Narrator
Excellent. Let's change topics.
"""

"""Ai
**Findings:**

* Origin: Constructed
* Creators: Extraterrestrial (ET)
"""
```

### Prose-style

```md
---
entry_id: entry-0000022
location_text: Philippines
datetime: 1870-01-01
source: History and Description of Our Philippine Wonderland
---

# Herencia Filipinas

This photograph documents a Moro Chieftain and his family in Northern Mindanao.

The term "Moro" was used by Spanish and American colonizers.

* Historical photograph
* Educational use
* Archival source
```

## Default behavior

When run with no arguments, `renderpdf.py` uses the current working directory:

```bash
python3.9 ../../tools/renderpdf.py
```

It looks for:

```text
./story.md
```

and writes:

```text
./<Story Title>.pdf
```

If no title is found, it falls back to:

```text
./story.pdf
```

## Illustration image behavior

The renderer inserts an image under the title if it finds one in the same directory as
`story.md`.

Lookup order:

1. `illustration.jpg`
2. `illustration.jpeg`
3. `illustration.png`
4. if none of the above exist, and there is exactly one `.jpg`, `.jpeg`, or `.png`
   file in the entry directory, that file is used

If multiple non-explicit images exist, no fallback image is chosen.

## Header fields under the title

By default, `renderpdf.py` reads the YAML/front matter field names and displays only the
ones that have meaningful values.

This means the script does not hardcode a fixed default field list.

Example:

```md
---
entry_id: entry-0000022
created_utc: 2026-04-01T11:03:55Z
location_text: Philippines
datetime: 1870-01-01
status: Draft
source: History and Description of Our Philippine Wonderland
---
```

These are prettified when shown in the PDF, for example:

- `location_text` → `Location`
- `created_utc` → `Created`
- `datetime` → `Date`

To reduce the displayed fields, use:

```bash
--header-fields "location_text,datetime,source"
```

This acts as a filter, not an expansion.

## Command-line options

### Basic usage

```bash
python3.9 ../../tools/renderpdf.py
python3.9 ../../tools/renderpdf.py .
python3.9 ../../tools/renderpdf.py /path/to/story.md
python3.9 ../../tools/renderpdf.py /path/to/entry-dir
```

### Custom output filename

```bash
python3.9 ../../tools/renderpdf.py . my-output.pdf
```

### Image height

```bash
python3.9 ../../tools/renderpdf.py --image-height-mm 70
```

### Image alignment

```bash
python3.9 ../../tools/renderpdf.py --image-align left
python3.9 ../../tools/renderpdf.py --image-align center
python3.9 ../../tools/renderpdf.py --image-align right
```

### Heading colors

Provide a comma-separated list of hex RGB colors:

```bash
python3.9 ../../tools/renderpdf.py --heading-colors "#223344,#553377,#aa2244"
```

These colors are cycled through speaker headings in dialogue mode.

### Header fields filter

```bash
python3.9 ../../tools/renderpdf.py --header-fields "location_text,source"
```

## Output naming

The output filename is derived from the story title.

For example:

```md
# Giro Giro of Mount Isa
```

becomes:

```text
Giro Giro of Mount Isa.pdf
```

Illegal filename characters are removed. If no title is found, the fallback is:

```text
story.pdf
```

## Notes

- The script includes a compatibility shim for some Python/OpenSSL/ReportLab builds
  where `hashlib.md5(usedforsecurity=False)` is not supported.
- For reliable ReportLab execution, use the same Python interpreter for both install and run.
  Example:

```bash
python3.9 -m pip install reportlab
python3.9 ../../tools/renderpdf.py
```

## Tests

A matching pytest file is provided as:

```text
tests/test_renderpdf.py
```

Suggested run command:

```bash
python3.9 -m pytest tests/test_renderpdf.py
```
