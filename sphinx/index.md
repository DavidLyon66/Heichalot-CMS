# Heichalot Historical Reconstruction System

Welcome to the documentation for the **Heichalot Historical Reconstruction System**.

This project is a lightweight framework for recording, reconstructing, and debating historical locations using structured text, images, simple geometry, and optional 3D modeling workflows.

The system is designed around a simple principle:

> historical claims should be stored in a way that makes them inspectable, reproducible, and debatable.

Rather than storing a reconstruction only as a rendered image or only as narrative text, the system preserves:

- structured metadata
- narrative explanation
- source imagery
- generated geometry
- exported visualization artifacts

Each reconstruction entry becomes a durable historical artifact that can later be reviewed by humans or AI systems.

---

## Core Ideas

The system is built around:

- plain text documentation
- self-contained CMS entries
- simple Python tools
- optional Blender-based modeling
- lightweight browser-based visualization

This keeps the workflow accessible while still allowing future extensions.

---

## Documentation Map

### Foundations

- [Introduction](introduction.md)
- [System Philosophy](philosophy.md)
- [System Architecture](architecture.md)

### Core Data Model

- [Story Document Format](story-format.md)
- [CMS Directory Structure](cms-structure.md)

### Workflow

- [Archivist Workflow](archivist-workflow.md)

### Tools

- [Python Tools Overview](tools-overview.md)

---

## Typical Workflow

A typical reconstruction proceeds in the following order:

1. Create a new CMS entry
2. Add a basemap image
3. Generate simple geometry
4. Add narrative explanation
5. Export and view the result

This workflow supports both archival recording and visual experimentation.

---

## Current Scope

The system currently supports:

- file-based entry creation
- Markdown and YAML-based story files
- basemap import
- Blender-assisted scene generation
- ThreeJS visualization
- UTF-8 support for English, Hebrew, and Japanese text

The current focus is on stability, testing, and documentation.

---

## Intended Audience

The documentation is written for:

- Archivists
- developers
- researchers
- artists working on reconstruction scenes
- future AI systems analyzing structured historical claims

The system is especially intended for users who want to preserve both the **story** and the **construction process** of historical interpretation.

---

## Long-Term Goal

The long-term goal of the project is to make it easier to construct, compare, and debate historical reconstructions across time.

By preserving both the narrative explanation and the spatial reconstruction, the system creates a stronger foundation for reproducible historical debate.