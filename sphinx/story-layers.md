# Story Layers

## Overview

Historical reconstructions rarely come from a single source.

Maps, surveys, drawings, aerial images, and written descriptions each describe different aspects of a place.  
To manage this complexity, the Heichalot system allows reconstructions to organize spatial information into **layers**.

A layer represents one category of spatial data such as:

- buildings
- streets
- water
- terrain
- vegetation

Layers are optional and loosely defined.  
Only the layers that exist for a reconstruction need to be recorded.

---

## Layer Definition in `story.md`

Layers are stored inside the metadata block of `story.md` using a dictionary.

Example:

```yaml
layers:
  buildings: assets/buildings.png
  streets: assets/streets.png
  water: assets/water.png
  vegetation: assets/vegetation.png

Each key represents a layer type.
Each value points to the file containing the layer data.

If a layer is not used, it simply does not appear in the dictionary.

Why Layers Are Flexible

The system intentionally avoids strict GIS schemas.

Instead, layers are:

optional

loosely defined

archivist-controlled

This keeps the workflow simple and avoids forcing users into complex data structures.

The philosophy is:

only record the layers that actually exist in the reconstruction.

Common Layer Types

While the system allows any layer names, several common layer categories have been identified.

Buildings Layer

Represents structures within the reconstruction.

Typical uses:

landmark buildings

building footprints

low-poly massing

automatically detected structures

Example:

layers:
  buildings: assets/buildings.png

Buildings may be generated manually in Blender or automatically using OpenCV detection tools.

Allotments Layer

Represents parcels of land or city blocks.

Historical maps often make property boundaries easier to detect than streets.

Allotments can be used to generate roads by subtraction.

Example workflow:

allotments → subtract → streets

Example layer:

layers:
  allotments: assets/allotments.png
Streets and Roads Layer

Represents the transportation network.

Typical data includes:

roads

lanes

bridges

rail routes

Example:

layers:
  streets: assets/streets.png

Roads may be created by:

tracing maps

subtracting allotments

automated detection

Regions Layer

Represents large zones within the map.

Examples include:

districts

neighborhoods

political zones

cultural areas

Example:

layers:
  regions: assets/regions.png

Regions are especially useful when describing historical changes.

Water Layer

Represents water features.

Examples:

rivers

coastline

canals

lakes

harbors

Example:

layers:
  water: assets/water.png

Water layers often help align historical maps with real-world geography.

Topology Layer

Represents terrain or elevation.

Typical information:

hills

slopes

terrain contours

Example:

layers:
  topology: assets/topology.png

In early reconstructions this may be approximate.

Later versions may incorporate topographic maps or terrain generation tools.

Vegetation Layer

Represents plant coverage or land use.

Examples:

forests

farmland

orchards

desert

wetlands

Example:

layers:
  vegetation: assets/vegetation.png

Vegetation layers can provide historical context for settlement patterns.

File Locations

Layer files are typically stored inside the entry's assets directory.

Example:

cms/
 └── entry-0000003/
     ├── story.md
     └── assets/
         ├── buildings.png
         ├── streets.png
         ├── water.png
         └── vegetation.png

The story.md file references these files using relative paths.

Supported File Types

Layer files may use several formats.

Examples:

png
svg
dxf
gltf
blend

The format depends on the workflow stage.

Examples:

Stage	Format
Map tracing	PNG / SVG
CAD tracing	DXF
3D modeling	Blender
Viewer export	GLTF
Blender Integration

Many layers can be generated using existing Blender tools.

Examples include:

GIS terrain add-ons

procedural vegetation tools

road generation tools

building generation add-ons

These tools generate geometry that can later be exported into the system.

The CMS records the results rather than enforcing a modeling workflow.

Automation Potential

Some layers may be generated automatically.

Examples include:

OpenCV Detection

Used to detect:

building footprints

allotments

block shapes

Terrain Generation

Used to approximate historical terrain.

Vegetation Simulation

Used to generate forests or farmland.

Automation tools can accelerate the reconstruction process while still allowing manual refinement.

Historical Debate

Layer separation allows different interpretations to coexist.

Historians may disagree about:

building locations

street layouts

district boundaries

land ownership

Rather than replacing earlier work, alternative interpretations can be recorded as additional layers.

Long-Term Goal

The layer system supports one of the central goals of the project:

allowing multiple reconstructions of the same place to exist and be compared.

By storing spatial evidence in layers, the system allows reconstructions to evolve while preserving earlier interpretations.


---

One **very small but powerful addition** you might consider later (not needed yet):

```yaml
layers:
  buildings:
    file: assets/buildings.png
    source: opencv