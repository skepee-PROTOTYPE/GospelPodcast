# GospelPodcast — Copilot Instructions

These rules describe the intended audio quality and structural behaviour of the podcast generator.
They MUST be preserved whenever modifying `gospel/text_normalizer.py` or `gospel/audio_generator.py`.

---

## 1. Section pauses (first reading → gospel → pope comment)

Each liturgy section MUST be separated by a silent pause of `SECTION_SILENCE_S` seconds (default 2.5 s).
This is achieved by `_build_episode_ssml()` inserting `<break time="2.5s"/>` between segments.

**Critical precondition:** `build_liturgy_segments()` must return **multiple segments** (one per section).
If it falls back to returning the whole description as a single string, there are NO pauses.

**Sunday / feast day structure:** On Sundays and major feasts, Vatican News includes a second reading
(`Seconda Lettura` / `Second Reading` / `Deuxième Lecture` / etc.) between the first reading and the psalm.
`build_liturgy_segments()` detects this via the `"seconda"` key in `LITURGY_PATTERNS` and emits it as an
additional segment — so episodes may have up to 4 sections:
`Prima Lettura → Seconda Lettura → Vangelo → Pope comment`. Both readings MUST appear in the output.

**Why it breaks silently:** The Vatican News RSS feed sometimes delivers the entire description as a
single flat paragraph (no `<br>` tags). The line-based section detection then finds index -1 for most
sections and falls back to a single segment. The fix is the *positional fallback* in
`_build_segments_positional()`, which de-anchors the `^`-prefixed patterns and matches by character
position in the flat string. **Never remove this fallback.**

---

## 2. Salmo responsoriale MUST be skipped entirely

The responsorial psalm section is identified by the `"salmo"` key in `LITURGY_PATTERNS` per language.
It must **never** appear in the returned segments list. Both code paths enforce this:
- Line-based path: the psalm lines are simply not included between `prima_end` and `idx_vangelo`.
- Positional path: `pos_salmo` is used only as an end boundary for the first/second reading;
  the text from `pos_salmo` to `pos_vangelo` is discarded.

---

## 3. Pope name and event location MUST be announced before the speech

The pope attribution is extracted from the description **after `html_to_plain_text()` but before `normalize_for_tts()`** (which would strip the parentheses via `_smooth_for_tts`). Using a middle step is critical:
- Raw HTML feeds end each `<p>` with `</i></p>` — the trailing HTML tag after `)` breaks the `\(([^()]+)\)\s*$` regex.
- `normalize_for_tts` strips parentheses entirely — the attribution would be lost.
- `html_to_plain_text` removes only HTML tags, leaving parentheses intact ✓

The resulting segment starts with `__POPE__` and a header line:
```
__POPE__ Commento di Papa Francesco, Angelus del 28 ottobre 2018.
<pope body text>
```

`_section_to_ssml()` renders this header in `<emphasis>` so TTS announces the pope name and event
before reading the reflection. The body text receives `<prosody pitch="-4%" rate="95%">`.

**Pope name detection regex** (in `_extract_pope_meta`): matches Francesco · Francis · François ·
Francisco · Franziskus · Benedetto · Benedict · Benedikt · Giovanni Paolo · John Paul · Jean Paul ·
Juan Pablo · João Paulo · Johannes Paul · Paolo VI · Paul VI · Pablo VI · Paulo VI · papa · pope ·
pape · papst.

**Gospel / pope body split** (positional path) uses two heuristics in order:
1. `GOSPEL_CLOSING_PATTERNS` — language-specific phrase that ends the gospel reading
   (e.g. "Parola del Vangelo", "Palavra da Salvação", "Gospel of the Lord").
2. `POPE_COMMENT_INTRO_PATTERNS` — opening phrase of the pope's reflection
   (e.g. "Fratelli e sorelle", "Irmãos e irmãs", "Dear brothers and sisters").

If neither is found, only the header segment is emitted (no body).

---

## 4. Bible book names: ONLY the book name is spoken, NOT chapter/verse numbers

Section headers (e.g. "Dal libro della Genesi 1,1-13") must have the trailing verse reference
stripped before TTS reads them. The function `_strip_verse_refs_from_header()` removes trailing
patterns like "1 1 a 13" or just "26" from a header line. `_strip_section_verse_refs()` applies
this to the first two lines of every segment (the section label and the book-source line).

**Inline parenthetical citations** (e.g. `(Mt 5,17)` or `(cfr Lc 23,34)`) that appear inside the
body text of the pope's reflection are ALSO removed. By the time `_smooth_for_tts()` runs, these
have been expanded by `expand_bible_refs()` + `normalize_verse_refs()` to `(Matteo 5 17)` /
`(confronta Luca 23 34)`. The function removes entire parenthetical groups that contain at least one
digit via `re.sub(r"\([^()]{0,120}\d[^()]{0,60}\)", " ", ...)` before stripping lone parentheses.

Examples of correct TTS output:
- `"Dal libro della Genesi 1,1-13"` → `"Dal libro della Genesi"`
- `"Prima lettura dal Deuteronomio 26,16-19"` → `"Prima lettura dal Deuteronomio"`
- `"Proclamação do Evangelho ... segundo Mateus 17,1-9"` → `"Proclamação do Evangelho ... segundo Mateus"`
- `"...il papa cita (Mt 5,17) nella sua riflessione..."` → `"...il papa cita nella sua riflessione..."`

**Bare (non-parenthetical) citations** in the pope body (e.g. `»Mt 5,17` without wrapping parentheses)
also become `Matteo 5 17` after expansion. These are caught by `_strip_bare_verse_refs(text, language)`,
which matches `BookName digit digit` patterns (requiring at least two digit groups to avoid false
positive on single-number sentences). It is called on the assembled pope body in **all three code paths**:
`build_liturgy_segments` (line-based), `_build_segments_positional` (positional fallback), and
`html_scraper._pope_segment()`. It is intentionally **not applied** to reading/gospel segments, where
the book name in the header must be preserved.

- `"»Mt 5,17"` → expanded to `"Matteo 5 17"` → `_strip_bare_verse_refs` removes it → `""`
- Single-number sentences like `"nel capitolo 5"` are **not** affected (requires 2 digit groups).
- Book name without digits (`"il vangelo di Marco"`) is **not** affected.

Vatican News feeds also emit a **standalone abbreviated reference line** (e.g. `"Gn 37,3-4"` or `"Matteo 21,33-43"`) as a separate line after the book-source header. `_strip_section_verse_refs()` detects and **drops entirely** any of the first 4 lines of a segment that match a book abbreviation or full book name followed only by verse numbers. The drop regex covers both short abbreviations (`Gn`, `Mt`) and full capitalised names (`Matteo`, `Giovanni Paolo`).

This stripping is applied in **both** the line-based and the positional code paths.

---

## 5. Semicolons must NOT produce mid-sentence pauses

Semicolons in the gospel text (e.g. "non crediate; non temere") are converted to **commas** in
`_smooth_for_tts()`, NOT to `__PAUSE__` markers. Neural2 voices produce natural brief pauses at
commas without requiring explicit `<break>` tags. Adding a hard `<break time="0.3s"/>` at every
semicolon creates choppy, unnatural delivery in long gospel quotes.

`__PAUSE__` markers are retained in `_escape_and_mark()` for future programmatic use but are **no
longer generated** by the semicolon substitution. Do NOT revert this to `__PAUSE__`.

```python
# CORRECT — semicolons become commas for natural Neural2 prosody:
smoothed = re.sub(r"[ \t]*;[ \t]*", ", ", smoothed)

# WRONG — do NOT use:
# smoothed = re.sub(r"[ \t]*;[ \t]*", " __PAUSE__ ", smoothed)
```

---

## 6. Key constants and where they live

| Constant / function | File | Purpose |
|---|---|---|
| `SECTION_SILENCE_S = 2.5` | `audio_generator.py` | Seconds of silence between sections |
| `LITURGY_PATTERNS` | `text_normalizer.py` | Per-language regex to detect section headers |
| `GOSPEL_CLOSING_PATTERNS` | `text_normalizer.py` | Phrases that end the gospel (used to split pope body) |
| `POPE_COMMENT_INTRO_PATTERNS` | `text_normalizer.py` | Opening phrases of pope reflection |
| `POPE_COMMENT_LABELS` | `text_normalizer.py` | Per-language "Comment by Pope" announcement string |
| `_build_segments_positional()` | `text_normalizer.py` | Positional fallback for flat-text feeds |
| `_strip_verse_refs_from_header()` | `text_normalizer.py` | Removes trailing chapter/verse numbers from headers |
| `_strip_bare_verse_refs()` | `text_normalizer.py` | Removes bare `BookName digit digit` patterns from pope body (non-parenthetical refs) |
| `_smooth_for_tts()` | `text_normalizer.py` | Cleans punctuation; semicolons→commas; removes parenthetical verse citations |
| `_section_to_ssml()` | `audio_generator.py` | Converts one segment to SSML with pope prosody |
| `_build_episode_ssml()` | `audio_generator.py` | Assembles full episode SSML with section breaks |
---

## 7. SSML chunking must never split inside block-level tags

When a segment (typically the Gospel on Sundays) exceeds `_SSML_BYTE_LIMIT` (4800 bytes),
`_synth_segment_safe()` splits the SSML at `<break>` boundaries. **Splits must only occur at
`<break>` tags that are at the outer (depth-0) nesting level** — never inside an open `<prosody>`
or `<emphasis>` block. Splitting inside a block tag produces orphaned opening/closing tags that
Neural2 voices reject with `400 Invalid SSML`. The chunker tracks `tag_depth` (incremented on
`<prosody>`/`<emphasis>` open, decremented on close) and only splits when `tag_depth == 0`.

---

## 8. Test cases that must keep working

```python
from gospel.text_normalizer import build_liturgy_segments

# PT flat text — 3 segments expected (reading, gospel, pope)
desc = ("Leitura da Profecia de Daniel 9,4b-10 ..."
        " Proclamação do Evangelho ... segundo Lucas 6,36-38 ..."
        " Palavra da Salvação. <pope body> ( Papa Francisco, Audiência )")
segs = build_liturgy_segments(desc, lang="pt")
assert len(segs) == 3
assert segs[-1].startswith("__POPE__")

# IT multiline — salmo must NOT appear in output
desc_it = ("Prima Lettura\nDal libro della Genesi 1,1-13\n...\n"
           "Salmo Responsoriale\nR. ...\n"
           "Dal Vangelo secondo Marco 10,46-52\n...")
segs_it = build_liturgy_segments(desc_it, lang="it")
assert not any("salmo" in s.lower() for s in segs_it)
```
