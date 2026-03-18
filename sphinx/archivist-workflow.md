# Archivist Workflow

## Overview

The Heichalot Historical Reconstruction System is designed to support the work of an **Archivist**.

An Archivist collects historical materials and constructs spatial reconstructions that represent a place at a specific moment in time.

The system provides a simple workflow that allows these reconstructions to be documented and reproduced.

---

## Typical Workflow

The Archivist workflow consists of five primary steps:

1. Create a new entry
2. Import a historical basemap
3. Generate initial geometry
4. Add narrative explanation
5. Export a scene for viewing

Each step produces files that remain inside the entry directory.

---

## Step 1: Create a New Entry

A new reconstruction begins by creating a new entry.

This is typically done using a Python tool such as:


createentry.py


The tool creates a new directory under the `cms/` directory and generates an initial `story.md` file.

Example result:


cms/
entry-0000004/
story.md
assets/


The Archivist can then begin adding materials to this entry.

---

## Step 2: Add a Basemap

The next step is to provide a historical map or image representing the location.

Examples include:

- scanned historical maps
- aerial imagery
- hand-drawn reconstructions

The basemap is referenced in the metadata section of `story.md`.

Example:


base_map: basemap.png


This image becomes the foundation for the spatial reconstruction.

---

## Step 3: Generate Initial Geometry

Tools can generate simple geometry from the basemap.

Examples include:

- terrain surfaces
- building footprints
- map-derived meshes

This step can be performed automatically using image analysis or manually using modeling software such as Blender.

The goal is not perfect accuracy but a plausible spatial representation.

---

## Step 4: Add Narrative Explanation

After the initial geometry is created, the Archivist writes a narrative explanation in the `story.md` file.

This narrative describes:

- the historical context
- sources used for reconstruction
- assumptions made during modeling
- areas of uncertainty

The narrative is written in Markdown so that it remains readable and easy to edit.

---

## Step 5: Export the Scene

The reconstruction can be exported for visualization.

Exported scenes may be viewed using browser-based tools such as ThreeJS.

These viewers allow researchers to explore the reconstructed environment interactively.

Exporting a scene does not modify the archival data.

---

## Iterative Refinement

Reconstruction is an iterative process.

The Archivist may repeatedly:

- refine geometry
- adjust basemap alignment
- update the narrative explanation
- add additional assets

Because the entry directory records the entire process, changes remain traceable.

---

## Multiple Time Periods

A location may have multiple entries representing different time periods.

Example:


entry-0000005 (Singapore 1820)
entry-0000012 (Singapore 1857)
entry-0000031 (Singapore 1900)


These entries allow the location to be studied as it evolves across time.

---

## Role of the Archivist

The system does not attempt to automate historical interpretation.

Instead, it records the reasoning and evidence used by the Archivist.

The Archivist therefore remains responsible for:

- evaluating sources
- interpreting incomplete evidence
- explaining reconstruction decisions

The software simply provides a framework for preserving that work.

---

## Long-Term Value

By combining spatial reconstruction with written explanation, each entry becomes a durable historical artifact.

Future researchers can examine both the narrative and the underlying reconstruction to understand how the interpretation was produced.