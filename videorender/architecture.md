# VideoRender Architecture

The VideoRender pipeline is a renderer-oriented subsystem within
HeichalotCMS.

Its purpose is to generate short explainer videos from structured CMS
content, using a simple author-facing script format and a separate
machine-facing render specification.

The initial implementation uses Python for orchestration and Node.js /
Remotion for rendering.

---

## Goals

The VideoRender pipeline is designed to:

- generate videos from CMS entry data
- keep author-facing scripting simple and readable
- isolate renderer complexity from CMS logic
- support reusable visual components and effects
- allow experimentation without forcing timeline editing

The system is intentionally narrow in its first form. It is not a full
video editor. It is a structured video generation pipeline.

---

## High-Level Pipeline

The pipeline is:

```text
CMS entry
   ↓
explainer.md
   ↓
tools/rendervideo.py
   ↓
explainer.render.json
   ↓
videorender (Remotion)
   ↓
video output