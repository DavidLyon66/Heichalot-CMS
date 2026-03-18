# Heichalot Historical Reconstruction System

## Introduction

The Heichalot Historical Reconstruction System is a lightweight framework for recording, reconstructing, and debating historical locations using structured data, images, and simple 3D models.

The system allows an **Archivist** to take a historical map, image, or written description of a place and convert it into a reproducible digital reconstruction. These reconstructions can then be viewed, compared across time, and debated using both human and AI analysis.

The project originated from a simple question:

> How can historical claims be documented in a way that makes them difficult to distort or falsify later?

Rather than storing historical claims only as text or narrative, the system records them as a combination of:

- structured metadata
- original images and maps
- generated geometry and scenes
- narrative explanation written by the archivist

Each historical entry therefore becomes a **reproducible historical artifact** rather than only a written argument.

---

## Design Philosophy

The system is intentionally simple.

Most historical reconstruction tools are large GIS systems or complex game engines. These systems are powerful but difficult for historians or archivists to use.

Heichalot takes a different approach:

- plain text files
- minimal configuration
- simple Python tools
- optional Blender modeling
- lightweight ThreeJS viewing

This allows a reconstruction to be built quickly while still preserving enough structure for later verification.

The project emphasizes **clarity and reproducibility over technical complexity**.

---

## The Archivist Workflow

The system is built around the work of an Archivist.

An Archivist performs the following steps:

1. Create a new entry in the CMS.
2. Provide a historical basemap or image.
3. Generate simple 3D geometry from the map.
4. Add narrative explanation describing the reconstruction.
5. Export the scene for viewing or debate.

The result is a directory containing a complete historical reconstruction.

---

## The Core Artifact: `story.md`

Each reconstruction is centered around a single file:
