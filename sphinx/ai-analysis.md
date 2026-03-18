# AI Analysis

## Overview

The Heichalot Historical Reconstruction System is designed to allow both humans and AI systems to analyze, critique, and expand historical reconstructions.

Because the system uses simple file formats such as:

- Markdown
- YAML
- PNG / SVG / GLTF assets

it can be easily interpreted by automated analysis tools.

AI systems may examine reconstruction entries to:

- evaluate plausibility
- identify inconsistencies
- suggest alternative interpretations
- generate debate commentary

The system does not grant AI authority over reconstructions.  
Instead, AI acts as an **additional participant in the debate process**.

---

## Why AI Integration Matters

Historical reconstructions often involve interpretation rather than certainty.

AI analysis allows:

- multiple interpretations to be examined
- inconsistencies to be detected
- alternative spatial hypotheses to be proposed

Because all reconstruction data is stored in simple formats, AI systems can inspect the same information that human reviewers see.

---

## Files AI Systems Can Read

An AI system analyzing a reconstruction entry typically reads the following files.

### story.md

The central reconstruction document.

Contains:

- location metadata
- time period
- basemap information
- spatial scaling
- narrative explanation

Example metadata:

```yaml
location_text: Australia/Sydney/Bondi Beach
year: 2027
base_map: basemap.png
px_to_m: [1.0, 1.0]
layers:
  buildings: assets/buildings.png
  streets: assets/streets.png
Layer Files

Layer files describe spatial components of the reconstruction.

Examples:

assets/buildings.png
assets/streets.png
assets/water.png
assets/topology.png

AI systems may analyze these layers to infer:

building density

road connectivity

terrain relationships

spatial plausibility

3D Scene Assets

Exported geometry may also be analyzed.

Examples:

scene.glb
buildings.glb
terrain.glb

These files allow AI to inspect spatial relationships in three dimensions.

Debate Files

Existing debate commentary can also be reviewed.

Example:

debate/
  2026-03-06T10-30-00Z-ai-review.md
  2026-03-06T11-12-00Z-human-comment.md

AI systems may evaluate existing arguments before generating new ones.

AI Analysis Workflow

A typical AI analysis process may follow these steps.

1 load reconstruction entry
2 read story.md metadata
3 inspect layer definitions
4 analyze spatial assets
5 review existing debate comments
6 generate analysis
7 write new debate comment

The result becomes a new file inside the debate/ directory.

AI Debate Contribution

AI systems contribute to discussion by writing new debate files.

Example:

cms/
 └── entry-0000003/
     └── debate/
         └── 2026-03-10T14-22-00Z-ai-analysis.md

Each AI comment follows the same format used for human debate comments.

Example:

---
from: ai:historical-review
date: 2026-03-10T14:22:00Z
regarding: entry-0000003
type: critique
confidence: medium
related_layer: streets
---

The street layout appears consistent with late colonial
port cities, however the spacing between building rows
may be larger than expected for the time period.

Further comparison with historical port city layouts
may help validate the reconstruction.

This keeps AI commentary transparent and auditable.

AI Analysis Types

AI systems may perform different kinds of analysis.

Examples include:

Spatial Plausibility

Evaluate whether building layouts match historical patterns.

Geographic Consistency

Compare reconstruction location with real-world geography.

Historical Pattern Comparison

Compare layouts with other cities from the same period.

Structural Reasoning

Evaluate whether roads, buildings, and terrain relationships appear plausible.

AI as Participant, Not Authority

The system treats AI commentary as one voice within the debate process.

AI analysis does not replace human interpretation.

Instead, it provides:

additional perspectives

pattern recognition

automated comparison

Human archivists remain responsible for final reconstruction narratives.

Transparency of AI Contributions

All AI-generated commentary is stored as debate files.

This ensures:

visibility of AI reasoning

traceability of conclusions

historical record of analysis

Future researchers can examine how both humans and AI interpreted a reconstruction.

Long-Term Vision

The AI analysis system supports a broader goal of the project:

historical reconstructions should be continuously examined and refined.

By allowing AI systems to participate in debate, the system encourages:

ongoing critique

comparison between interpretations

improvement of reconstruction accuracy

The result is a historical archive that records not only the reconstruction itself, but also the process of understanding it.


---

### Optional future enhancement (worth noting for later)

Eventually you could add a **tool like:**


tools/aianalyze.py


Which would:


scan cms/<entryID>
read story.md
inspect layers
generate debate/<timestamp>-ai-analysis.md


That would turn the system into something very powerful: **a reconstruction archive that automatically invites critique**.
