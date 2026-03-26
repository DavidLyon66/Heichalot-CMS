# renderhtml.py

`renderhtml.py` converts a CMS `story.md` file into simple semantic HTML.

The intent of this tool is to generate **plain, reusable content HTML** rather than a complete website theme. It uses basic tags such as headings, paragraphs, emphasis, and bullet lists so that developers can drop the output into their own web system and let their own headers, footers, CSS, and templates handle presentation.

## Purpose

This tool is designed for fast publication and archival workflows:

- convert `story.md` into a readable HTML page
- optionally generate only the body fragment for embedding
- preserve speaker structure such as `Narrator` and `Ai`
- keep output simple enough to style in another system

## Typical input

The input is expected to be a CMS story file with:

- YAML frontmatter at the top
- a Markdown title line beginning with `#`
- triple-quoted speaker blocks such as:

```md
"""Narrator
This is the first paragraph.

* Point one
* Point two
"""
```

## Basic behavior

The renderer should:

- extract the document title
- parse speaker blocks into structured sections
- group consecutive text lines into paragraphs
- convert bullet lines into `<ul><li>...</li></ul>`
- escape HTML safely
- generate either a full HTML page or an HTML fragment

## Output modes

### Default mode

By default, `renderhtml.py` should generate a full standalone HTML page:

```html
<!doctype html>
<html lang="en">
<head>...</head>
<body>
  <article class="story-entry">...</article>
</body>
</html>
```

This is useful for quick local viewing and fast publication.

### Fragment mode

With `--fragment`, the tool should generate only the content body, typically rooted at an `<article>` element.

This is useful when another web system will wrap the output in its own layout.

## Suggested command line usage

Render a single `story.md` file:

```bash
python3 renderhtml.py /path/to/story.md
```

Render from a CMS entry directory containing `story.md`:

```bash
python3 renderhtml.py /path/to/cms/entry-0000013
```

Render only the fragment:

```bash
python3 renderhtml.py /path/to/cms/entry-0000013 --fragment
```

## Suggested output locations

If the input is a file:

```text
story.html
```

If the input is a CMS entry directory:

```text
output/story.html
```

## HTML structure

A typical output structure is:

```html
<article class="story-entry">
  <h1>Remote-Viewing the Romanian Pyramids</h1>

  <section class="story-block speaker-narrator">
    <h2>Narrator</h2>
    <p>Excellent. Let's change topics...</p>
  </section>

  <section class="story-block speaker-ai">
    <h2>Ai</h2>
    <p><strong>Findings:</strong></p>
    <ul>
      <li>Origin: Constructed</li>
      <li>Creators: Extraterrestrial (ET)</li>
    </ul>
  </section>
</article>
```

## Design notes

### Keep layout responsibility outside this tool

`renderhtml.py` should not try to own:

- site navigation
- global headers or footers
- branding
- complex CSS themes

Those should remain in the consuming web system.

### Preserve semantic structure

Where possible, the renderer should produce semantic HTML rather than flattening everything into line breaks.

That means:

- prose should go into `<p>` tags
- bullet lists should become `<ul>` structures
- speaker names should be rendered as headings or labels

### Slide-like bullet sections

Some story blocks naturally contain a short heading followed by bullet items. These may later be treated by video tooling as slide-like content blocks. For now, `renderhtml.py` should simply preserve them as paragraphs plus bullet lists.

## Relationship to other tools

This tool fits into the broader pipeline:

```text
story.md
  -> renderhtml.py
  -> renderpdf.py
  -> story2aiproduction.py
  -> story2world.py
```

It should therefore stay simple, predictable, and easy to consume from other tools.

## Future improvements

Possible later enhancements include:

- support for multiple language variants
- optional inclusion of AI-generated images
- richer block typing from the story parser
- better handling of bold and inline emphasis
- developer-selectable CSS class prefixes

## Testing

A basic pytest test should confirm:

- title extraction
- speaker block parsing
- paragraph rendering
- bullet list rendering
- full-page output mode
- fragment output mode

