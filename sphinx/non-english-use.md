HeichalotCMS allows stories to be written in non-English
languages like Hebrew and Japenese.

story.md must be editable in Hebrew/Japanese

tags/values can be Hebrew/Japanese

no visible language marker inside the file

The answer is: very little pain, as long as we lock down UTF-8 everywhere.

All reads and writes in Python must use:

encoding="utf-8"

story.md stays plain text Markdown with YAML frontmatter.

YAML keys and values can be Hebrew or Japanese if you want.

Example:

---
מזהה_כניסה: כניסה-0000003
נוצר_בתאריך: 2026-03-06 07:57:36+00:00
מיקום: בונדי ביץ'
שנה: 2027
מצב: טיוטה
תגיות: []
מפת_בסיס: basemap.png
---

# כותרת

כאן כותבים את הסיפור.

That will parse fine with PyYAML, provided the file is UTF-8.

The real issue is not the file format

It is editor behavior.

The Archivist must use an editor that saves UTF-8 correctly.

Usually okay:

Notepad (modern Windows)

VS Code

Notepad++

Kate

gedit

Less safe:

very old Windows editors

editors that silently save ANSI/Latin-1

No visible language marker

That is fine.

You do not need a language: field in the file if you do not want one.

The system can simply treat the file as Unicode text.

Directory naming

Yes, you can absolutely make the entry prefix configurable and non-English.

For example in config:

[new_entry]
entry_prefix = כניסה-
pad_width = 7

Then new entries become:

cms/כניסה-0000003/

That is valid on modern filesystems.

One practical caution,

Even though Hebrew/Japanese directory names work, some tools and scripts can be more annoying with non-ASCII paths than with non-ASCII file contents.

So the safest compromise is often keep directory names machine-safe and allow full Hebrew/Japanese inside story.md

We support UTF-8 in story.md and allow Hebrew/Japanese in all values and tags

optionally allow Hebrew entry prefixes in config

This keeps the Archivist workflow simple even if they are not using English as their local HeichalotCMS language.
