# show_zoom_options.md

(show-zoom-options)=

# SHOW zoom options

The `SHOW` command supports optional soft zoom parameters for background images.

This allows a still image to slowly zoom in or out over the duration of the `SHOW`.

## Syntax

Basic `SHOW`:

```text
[SHOW background.png FOR 60s]
```

Zoom with default curve:

```text
[SHOW background.png FOR 60s ZOOM 1.0->1.2]
```

Zoom with explicit curve:

```text
[SHOW background.png FOR 60s ZOOM 1.0->1.2 CURVE ease_in_out]
```

## Parameters

### `ZOOM start->end`

Defines the image scale at the beginning and end of the `SHOW`.

Examples:

```text
[SHOW background.png FOR 10s ZOOM 1.0->1.1]
[SHOW background.png FOR 10s ZOOM 1.0->1.25]
[SHOW background.png FOR 10s ZOOM 1.15->1.0]
```

Interpretation:

- `1.0` means normal size.
- Values greater than `1.0` zoom in.
- A higher end value than start value creates a push-in.
- A lower end value than start value creates a pull-back or zoom-out.

Example:

```text
[SHOW background.png FOR 12s ZOOM 1.0->1.15]
```

This starts at normal size and slowly zooms in to 115 percent over 12 seconds.

## `CURVE`

The optional `CURVE` parameter controls the feel of the zoom motion.

If omitted, the default is:

```text
linear
```

Supported curve names:

- `linear`
- `ease_in`
- `ease_out`
- `ease_in_out`
- `strong_ease_in`
- `strong_ease_out`
- `strong_ease_in_out`

Example:

```text
[SHOW background.png FOR 8s ZOOM 1.0->1.25 CURVE strong_ease_in_out]
```

## Curve meanings

### `linear`

Constant speed from start to end.

```text
[SHOW background.png FOR 10s ZOOM 1.0->1.2 CURVE linear]
```

This can feel mechanical or technical.

### `ease_in`

Starts slowly, then accelerates.

```text
[SHOW background.png FOR 10s ZOOM 1.0->1.2 CURVE ease_in]
```

Useful when the motion should gather momentum.

### `ease_out`

Starts more quickly, then settles gently.

```text
[SHOW background.png FOR 10s ZOOM 1.0->1.2 CURVE ease_out]
```

Useful when the move should arrive softly.

### `ease_in_out`

Starts slowly, speeds up in the middle, then slows near the end.

```text
[SHOW background.png FOR 12s ZOOM 1.0->1.15 CURVE ease_in_out]
```

This is usually the safest cinematic default.

### `strong_ease_in`

A stronger version of `ease_in`.

```text
[SHOW background.png FOR 10s ZOOM 1.0->1.2 CURVE strong_ease_in]
```

### `strong_ease_out`

A stronger version of `ease_out`.

```text
[SHOW background.png FOR 10s ZOOM 1.0->1.2 CURVE strong_ease_out]
```

### `strong_ease_in_out`

A stronger version of `ease_in_out`.

```text
[SHOW background.png FOR 8s ZOOM 1.0->1.25 CURVE strong_ease_in_out]
```

Useful when the zoom needs to read more clearly on screen.

## Notes

- `CURVE` may only be used when `ZOOM` is present.
- The zoom parameters are emitted into `video.render.json` as `zoomStart`, `zoomEnd`, and `zoomCurve`.
- Remotion performs the actual interpolation and easing during render.

Example JSON output:

```json
{
  "type": "show",
  "file": "background.png",
  "durationFrames": 1800,
  "zoomStart": 1.0,
  "zoomEnd": 1.2,
  "zoomCurve": "ease_in_out"
}
```

## Recommendations

For most story work:

```text
[SHOW background.png FOR 12s ZOOM 1.0->1.15 CURVE ease_in_out]
```

For a stronger dramatic push:

```text
[SHOW background.png FOR 8s ZOOM 1.0->1.25 CURVE strong_ease_in_out]
```

For a gentle pull-back:

```text
[SHOW background.png FOR 10s ZOOM 1.15->1.0 CURVE ease_out]
```

## Implementation status

The following are implemented end-to-end:

- parser support in `rendervideo.py`
- parser tests
- JSON emission
- Remotion render support in `ShowImage.tsx`

This means the syntax is now active rather than placeholder-only.
