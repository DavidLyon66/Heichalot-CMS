# System Architecture

## Overview

The Heichalot Historical Reconstruction System is built around a simple file-based architecture.  
Each historical reconstruction is stored as a self-contained directory containing structured metadata, narrative text, and associated assets.

The system avoids traditional databases. Instead, the filesystem itself acts as the storage layer.  
This makes the system transparent, inspectable, and easy to archive or version control.

A reconstruction can be understood simply by examining the files that belong to it.

---

## Core Architectural Components

The system is composed of five primary components:

1. The CMS directory
2. The `story.md` document
3. The asset storage system
4. The Python toolchain
5. Visualization tools

These components are intentionally loosely coupled so that the system remains easy to extend.

---

## The CMS Directory

All historical entries are stored under the `cms/` directory.

Example structure:


cms/
entry-0000001/
entry-0000002/
entry-0000003/


Each entry directory represents a single reconstruction of a place at a specific time.

The directory contains everything required to reproduce the reconstruction.

This structure allows entries to be:

- copied
- archived
- version controlled
- independently examined

without relying on any external database.

---

## Entry Structure

A typical entry directory contains the following structure:


entry-0000003/
story.md
assets/
reconstruction.blend


### story.md

The central document describing the reconstruction.

This file contains:

- structured metadata
- narrative explanation
- references to assets

### assets/

A directory containing supporting files such as:

- images
- processed maps
- generated geometry
- exported scene files

### Blender Files

Optional modeling files used during reconstruction.  
These allow the scene to be modified or regenerated later.

---

## The Story Document

Every entry is centered around a single document:


story.md


This file acts as the **index and narrative record** for the entry.

It contains two distinct sections:

### Metadata (YAML)

The top section stores structured information used by the system.

Examples include:

- location information
- year and datetime
- map calibration
- asset references

### Narrative (Markdown)

The remainder of the file contains the Archivist's explanation of the reconstruction.

This section documents:

- interpretation
- assumptions
- historical context
- reasoning behind the reconstruction

Because the file is plain text, it can be edited with any editor.

---

## Python Toolchain

A collection of lightweight Python tools assist the Archivist.

These tools operate directly on the filesystem and modify entry directories.

Examples include:

- creating new entries
- importing basemaps
- generating geometry
- exporting scenes

Because the tools work directly with files, the workflow remains transparent and easy to debug.

---

## Blender Integration

Blender is used as an optional modeling environment.

The Archivist may use Blender to:

- import historical maps
- generate terrain surfaces
- construct simplified buildings
- export geometry

Blender files may be stored alongside the entry so that modeling work can be revisited later.

---

## Visualization

Scenes can be exported for visualization using browser-based tools such as ThreeJS.

This allows reconstructions to be explored interactively without requiring specialized software.

Visualization tools operate on exported assets rather than modifying the archival data.

---

## Data Flow

A typical workflow follows these steps:

1. Create a new entry
2. Import a basemap
3. Generate geometry
4. Add narrative explanation
5. Export a scene for visualization

Each step produces files that remain inside the entry directory.

This ensures that the reconstruction process remains inspectable.

---

## Design Goals

The architecture prioritizes several principles:

- transparency of stored data
- minimal dependencies
- long-term archival durability
- easy debugging
- simple tooling

These goals ensure that reconstructions remain understandable even years later.

---

## Extensibility

The architecture allows new tools to be added without modifying existing entries.

Possible future extensions include:

- improved geometry extraction
- AI-assisted map interpretation
- automated comparison of historical entries
- integration with external geographic data

Because each entry is self-contained, new tools can operate on existing archives without structural changes.
