# CMS Directory Structure

## Overview

The Heichalot Historical Reconstruction System stores all historical reconstructions in a simple filesystem structure called the **CMS directory**.

CMS stands for **Content Management System**, but in this project it is implemented directly using the filesystem rather than a database.

Each reconstruction entry is stored as its own directory containing all information needed to reproduce the reconstruction.

This approach has several advantages:

- transparency of stored data
- easy inspection by humans
- compatibility with version control systems
- long-term archival durability

---

## Top-Level Structure

The main project directory typically contains the following structure:


project-root/
cms/
tools/
scenes/
docs/


### cms/

Contains the historical reconstruction entries.

### tools/

Contains Python scripts used to create and process entries.

### scenes/

Contains exported scenes used for visualization.

### docs/

Contains the system documentation.

---

## Entry Directories

Inside the `cms/` directory, each entry represents a historical reconstruction.

Example:


cms/
entry-0000001/
entry-0000002/
entry-0000003/


Each entry directory contains the complete data needed to reconstruct a location at a particular time.

The entry identifier is sequential and padded with zeros to allow easy sorting.

---

## Entry Directory Layout

A typical entry directory looks like this:


entry-0000003/
story.md
assets/
reconstruction.blend


### story.md

The primary document describing the reconstruction.

This file contains both metadata and narrative explanation.

### assets/

Stores supporting files used by the entry.

Examples include:

- basemap images
- generated geometry
- processed textures
- exported models

### Blender files

Optional modeling files used during reconstruction.

These allow the scene to be modified or regenerated later.

---

## Assets Directory

The `assets/` directory contains files that support the reconstruction.

Example:


assets/
basemap.png
terrain.glb
buildings.glb


Typical asset types include:

- PNG or JPG map scans
- GLB or GLTF geometry files
- textures
- generated terrain meshes

Assets are separated from the narrative text so that the `story.md` file remains readable.

---

## Basemap Files

The basemap is the primary image used to build the reconstruction.

The filename is referenced from the metadata section of `story.md`.

Example:


base_map: basemap.png


The basemap is usually stored inside the `assets/` directory.

---

## Generated Assets

Some files are produced automatically by system tools.

Examples include:

- generated meshes
- processed geometry
- exported scene files

These are recorded in the `generated_assets` field of the `story.md` metadata.

Example:


generated_assets:
terrain_mesh: assets/terrain.glb


---

## Entry Independence

Each entry directory is designed to be **self-contained**.

This means that an entry can be:

- copied to another system
- archived
- version controlled
- inspected independently

The goal is that a reconstruction can be understood simply by reading the files contained within its directory.

---

## Naming Conventions

Entry directories follow the pattern:


entry-XXXXXXX


Where `XXXXXXX` is a zero-padded numeric identifier.

The prefix may be configurable depending on project needs.

---

## Long-Term Storage

Because entries are plain directories containing standard files, they can be preserved using normal archival methods such as:

- Git repositories
- ZIP archives
- offline storage

No specialized database export is required.

---

## Philosophy of the CMS

The CMS structure is intentionally simple.

Rather than building a complex database system, the project relies on the filesystem as the storage layer.

This keeps the system transparent and ensures that the archive remains readable even if the surrounding software evolves.