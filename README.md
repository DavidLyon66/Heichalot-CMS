# Heichalot-CMS
A Content-Management-System designed for Remote-Viewing Stories and Diaspora Information

![Project Logo](images/philosophy.png "Project Philosophy")

## Introduction

The Heichalot CMS is a lightweight framework for story, searching and analysing remote-viewing and historical information.

It provides the ability for recording, reconstructing, and debating historical locations using structured data, images, and simple 3D models.

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

## Installation using Miniconda

Open **Anaconda Prompt** or **Miniconda Prompt**.

```cmd
conda create -n heichalotcms python=3.11
conda activate heichalotcms
git clone https://github.com/DavidLyon66/Heichalot-CMS.git
cd Heichalot-CMS
pip install -e .
```

