# Debate Format

## Overview

The Heichalot Historical Reconstruction System allows discussion and critique of each reconstruction entry.

Debate records are stored separately from the main `story.md` document in order to preserve a clear distinction between:

- the **archivist's reconstruction narrative**
- the **discussion surrounding that reconstruction**

Each entry may contain a `debate/` directory holding individual commentary files.

These comments may originate from:

- human reviewers
- historians
- archivists
- AI analysis systems

The debate system is intentionally simple and designed to remain readable by both humans and machines.

---

## Debate Directory

Debate files are stored inside the entry directory.

Example structure:


cms/
└── entry-0000003/
├── story.md
├── assets/
└── debate/
├── 2026-03-06T10-30-00Z-ai-review.md
├── 2026-03-06T11-12-00Z-human-comment.md
└── 2026-03-07T08-05-00Z-counterpoint.md


Each file represents **a single debate comment**.

This structure keeps discussion modular and easy to review.

---

## File Naming Convention

Debate files should follow a timestamp-first naming scheme.

Example:


YYYY-MM-DDTHH-MM-SSZ-description.md


Example filenames:


2026-03-06T10-30-00Z-ai-review.md
2026-03-06T11-12-00Z-human-note.md
2026-03-07T08-05-00Z-bridge-question.md


Advantages of this format:

- chronological sorting
- easy identification
- filesystem safe
- easy AI parsing

---

## File Structure

Each debate file consists of:

1. YAML metadata header
2. Markdown comment body

Example structure:

metadata

comment text


This format matches the structure used in `story.md`.

---

## Required Metadata Fields

The following fields should appear in every debate file.

### from

Identifies the origin of the comment.

Examples:


from: human:david
from: ai:heichalot-reviewer
from: human:anonymous


---

### date

Timestamp of the comment in ISO format.

Example:


date: 2026-03-06T10:30:00Z


---

### regarding

Identifies the entry being discussed.

Example:


regarding: entry-0000003


---

### type

Describes the nature of the comment.

Examples:


type: critique
type: hypothesis
type: clarification
type: support
type: counterargument


---

## Optional Metadata Fields

Additional fields may be included when useful.

### location

Approximate geographic location of the author.

Example:


location: Australia/Sydney


---

### confidence

Estimated confidence in the comment.

Example:


confidence: low
confidence: medium
confidence: high


---

### related_layer

References a layer involved in the discussion.

Example:


related_layer: buildings


---

### related_asset

References a specific asset.

Example:


related_asset: assets/buildings.png


---

## Example Debate File

Example:

from: ai:heichalot-reviewer
date: 2026-03-06T10:30:00Z
location: Australia/Sydney
regarding: entry-0000003
type: critique
confidence: medium
related_layer: buildings

The proposed bridge alignment appears plausible, but the relationship
between the menorah platform and the existing shoreline may require
additional visual testing.

The basemap may not accurately represent shoreline conditions for the
year specified in the reconstruction.


---

## Design Principles

The debate system follows several principles.

### Separation of Narrative and Debate

The archivist's narrative remains inside `story.md`.

Debate and commentary remain separate.

This keeps the reconstruction record clear.

---

### One Comment Per File

Each comment should exist in its own file.

Advantages:

- easy chronological ordering
- easy comparison of viewpoints
- simple AI ingestion

---

### Human and AI Friendly

Debate files are intentionally simple.

They are designed to be:

- readable in any text editor
- parseable by AI systems
- easy to archive long term

---

## Long-Term Purpose

The debate directory supports one of the core goals of the Heichalot system:

**historical reconstructions should be open to discussion and revision.**

By recording debate alongside reconstructions, the system preserves not only what was proposed, but also how the interpretation evolved over time.

This makes historical analysis more transparent and reproducible.