# Python Tools Overview

## Overview

The Heichalot Historical Reconstruction System uses a small set of Python tools to support the Archivist workflow.

These tools operate directly on the filesystem and are intentionally lightweight.  
They are designed to work with plain text files and standard asset formats rather than requiring a database or large application framework.

The Python toolchain currently serves three primary purposes:

- creating and managing CMS entries
- processing source images and metadata
- exporting reconstructions for viewing

---

## Tool Philosophy

The tools are designed to be:

- simple
- inspectable
- scriptable
- easy to debug
- minimally stateful

Where possible, a tool should perform one clearly defined task and leave behind visible files that explain what happened.

The toolchain is not intended to hide the reconstruction process.  
It is intended to make the process easier to repeat.

---

## Main Tool Categories

The tools currently fall into four categories:

1. entry management tools
2. context and configuration tools
3. Blender-side processing tools
4. visualization and export tools

---

## Entry Management Tools

### `createentry.py`

Creates a new entry directory inside the CMS.

Typical tasks:

- create the next sequenced entry id
- create `story.md`
- create the `assets/` directory
- update the entry counter in the config file

This tool is usually the starting point for a new reconstruction.

---

## Context and Configuration Tools

### `setcmscontext.py`

Sets the current working context used by the system.

Typical tasks:

- store the current project root
- store the active historical location
- store the active date or year

This tool allows later scripts to infer the intended environment without repeatedly entering the same values.

---

## Blender-Side Processing Tools

These scripts are run inside Blender’s Python environment.

They are used for operations that benefit from interactive 3D editing or geometry generation.

### `importbasemap.py`

Imports the basemap image into Blender as a textured plane.

Typical tasks:

- locate the basemap for the current entry
- update `story.md` if needed
- create the basemap plane
- apply scaling and centering metadata

This is the usual starting point for scene construction inside Blender.

---

### `findbuildingsonmap.py`

Attempts to extract building footprints or massing geometry from the basemap image.

Typical tasks:

- detect closed shapes using OpenCV
- generate basic meshes
- create low-poly building massing
- assist with first-pass city generation

This tool provides a fast way to move from 2D map imagery into 3D spatial representation.

---

## Visualization and Export Tools

### `rendercontext.py`

Loads a reconstruction context and displays it in the ThreeJS viewer.

Typical tasks:

- locate the current scene
- load exported assets
- build the browser-based view
- provide immediate visual feedback

This tool is used to inspect the reconstruction outside Blender.

---

### `exportstatic.py`

Exports a scene for static web hosting.

Typical tasks:

- gather the required scene files
- generate self-contained HTML output
- prepare assets for deployment to a website

This allows reconstructions to be shared or published.

---

## Shared Helper Modules

### `cms.py`

This module contains reusable logic shared across tools.

Typical responsibilities include:

- resolving project paths
- locating CMS entries
- reading and writing `story.md`
- handling entry naming and numbering
- finding the current context

This is the core infrastructure layer of the Python toolchain.

---

### `cms_blender.py`

This module adapts the CMS logic for Blender-side scripts.

Typical responsibilities include:

- locating the current entry from the Blender file location
- falling back to the configured current project state
- providing Blender scripts with access to CMS-aware behavior

This reduces duplication between command-line and Blender scripts.

---

## Design Principles

The Python toolchain follows several design principles:

### 1. Filesystem First

The tools operate on visible files and directories rather than hiding data in a database.

### 2. Minimal State

Only a small amount of configuration is stored outside the CMS, primarily in the user config file.

### 3. Human Readability

Generated files should remain understandable to human users wherever possible.

### 4. Reproducibility

The same tool run against the same entry should produce the same result unless the entry itself changes.

---

## Typical Toolchain Sequence

A common workflow might look like this:

1. Run `createentry.py`
2. Add a basemap image into the new entry
3. Run `importbasemap.py` in Blender
4. Run `findbuildingsonmap.py` in Blender
5. Export assets from Blender
6. Run `rendercontext.py` to inspect the result
7. Run `exportstatic.py` if a web export is required

This sequence supports both rapid experimentation and structured archival recording.

---

## Future Direction

As the system matures, the Python toolchain may grow to include:

- validation tools
- regression tests
- automated asset registration
- AI-assisted comparison tools
- map alignment utilities

Even as new tools are added, the overall philosophy should remain the same:

> each tool should do a small number of things clearly and leave behind visible, inspectable results.