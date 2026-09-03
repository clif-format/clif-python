# pyclif

Official Python implementation for [CLIF 1.0](https://github.com/clif-format/clif) — the Contextual Localization Integrated Format.

`pyclif` provides the core pieces needed by a Python localization toolchain:

- **Parser** — read CLIF text/files into a typed Python data model.
- **Serializer** — write the data model back as canonical CLIF.
- **Validator** — check required fields, fixed vocabularies, status rules, duplicate IDs, ICU brace balance, file layout, and rendered display width.
- **Converter** — bidirectional conversions for JSON, YAML, CSV, PO, XLIFF, Fluent, Android strings.xml, iOS Localizable.strings.

## Status

The parser, serializer, validator, and converters target CLIF 1.0 and are checked against the normative specification examples and the `clif-test` conformance fixtures (both the valid and the invalid ones).

## Installation

```bash
pip install clif-format
```

For development:

```bash
git clone https://github.com/clif-format/clif-python.git
cd clif-python
pip install -e ".[dev]"
```

## Quick start

```python
import pyclif

text = '''CLIF 1.0
namespace: demo
clan: settings
source-language: en-US
target-language: zh-CN

[video]
type: label

<resolution>
source: "Resolution"
target: "分辨率"
status: final
'''

doc = pyclif.parse(text)
print(doc.header.namespace)          # demo
print(doc.groups[0].path)            # video
print(doc.groups[0].entries[0].id)   # resolution
print(doc.groups[0].entries[0].target)

print(pyclif.serialize(doc))

issues = pyclif.validate(text)
for issue in issues:
    print(issue.line, issue.category, issue.message)
```

## Command line

```bash
pyclif parse path/to/file.clif
pyclif serialize path/to/file.clif
pyclif validate path/to/file.clif
pyclif convert path/to/file.clif --format po
pyclif convert path/to/file.po --from po --format clif
pyclif convert path/to/terms.clif --format xliff --xliff-version 2.2
```

Supported convert formats: `clif`, `json`, `yaml`, `csv`, `po`, `xliff`, `fluent`, `android`, `ios`.

`validate` exits `1` when the file has errors and `0` when it only has warnings or extension notes. Every diagnostic carries a line number, a category, and the offending line.

## API overview

| Function | Description |
| --- | --- |
| `pyclif.parse(text, path=None)` | Parse CLIF text into `ClifDocument`. |
| `pyclif.load(path)` | Read and parse a `.clif` file. |
| `pyclif.serialize(doc)` | Serialize a `ClifDocument` to canonical CLIF text. |
| `pyclif.validate(text, check_width=False)` | Validate CLIF text and return `list[ValidationIssue]`. |
| `pyclif.validate_document(doc, check_width=False)` | Validate an already parsed document. |
| `pyclif.effective_context / effective_type / effective_emotion / effective_max_width` | Resolve a group-inherited value for one entry. |
| `pyclif.to_dict(doc)` / `pyclif.from_dict(data)` | Convert between `ClifDocument` and a JSON-shaped dict. |
| `pyclif.to_json(doc)` / `pyclif.from_json(text)` | Convert between `ClifDocument` and JSON text. |

## Converter support

Current converter is **bidirectional** for:

- JSON (`to_json` / `from_json`, as well as `to_dict` / `from_dict`; `from_plain_json` for flat/nested localization JSON such as Minecraft-style files)
- YAML (`to_yaml` / `from_yaml`, requires PyYAML)
- CSV (`to_csv` / `from_csv`)
- PO (`to_po` / `from_po`)
- XLIFF 2.x (`to_xliff` / `from_xliff`); `to_xliff(doc, version="2.0" | "2.1" | "2.2")`, default `2.1`. Version `2.2` also writes the XLIFF 2.2 glossary module for a `variant: glossary` document, and `from_xliff` reads that module (and legacy XLIFF 1.2 exports)
- Fluent (`to_fluent` / `from_fluent`)
- Android strings.xml (`to_android_strings` / `from_android_strings`)
- iOS Localizable.strings (`to_ios_strings` / `from_ios_strings`)

API example:

```python
# CLIF -> other format
po_text = pyclif.to_po(doc)
yaml_text = pyclif.to_yaml(doc)

# other format -> CLIF
doc = pyclif.from_po(po_text)
doc = pyclif.from_yaml(yaml_text)
```

### Metadata channels

CLIF carries context as first-class data, and every converter moves that data
through the target format's own documented metadata channel — never through an
invented one:

| Format | Channel used for CLIF attributes | Channel used for context |
| --- | --- | --- |
| JSON / YAML / CSV | native fields of the CLIF-shaped document | native field |
| XLIFF 2.x | metadata module (`mda:metadata` / `mda:metaGroup category="clif"` / `mda:meta`), plus `state` on `segment` for status | `mda:meta type="context"` and a plain `note` |
| XLIFF 2.2 glossary | additionally the glossary module (`gls:glossEntry`) for `variant: glossary` | `gls:definition` |
| gettext PO | extracted comments `#. clif:<key>: <value>`; `#:` for references; `msgctxt` for the group path and entry id | plain `#.` comment |
| Fluent | message comment `# clif:<key> = <value>` (attributes are translatable content, so they are not used for metadata) | plain `#` comment |
| Android strings.xml | XML comment above the resource, `clif:<key>: <value>` | first line of that comment |
| iOS Localizable.strings | `/* ... */` block comment above the pair, `clif:<key>: <value>` | first line of that comment |

Because formats without a group level cannot express inheritance, the exporters
fold the group values into each entry (the effective context, type, emotion and
max-width) so nothing is lost.

The reverse direction is deliberately conservative. An importer reads only the
metadata the source format actually defines: namespaced `clif:` entries become
CLIF attributes, an ordinary comment becomes `context`, and everything else
falls back to a documented default (`type: sentence`, `status` derived from
whether a translation exists). **A converter never invents context, emotion,
references, widths or reviewers that the source file did not contain.**
### Round-trip fidelity

JSON, YAML, CSV, and XLIFF preserve the whole CLIF data model, so `clif -> format -> clif` is lossless. The remaining formats have no slot for some CLIF fields:

| Format | Fidelity | Dropped on the way back |
| --- | --- | --- |
| JSON / YAML / CSV | yes | — |
| XLIFF 2.0 / 2.1 / 2.2 | yes | — (CLIF-only fields travel as `clif:`-categorised notes) |
| PO | entry level | header prose (`variant`, `version`, `title`, `info`, `standard`, `dependency`) and the group structure; every entry attribute survives |
| Fluent | entry level | header prose and the group structure; Fluent attributes of foreign files cannot be represented |
| Android strings.xml | entry level | header prose and the group structure |
| iOS Localizable.strings | entry level | header prose and the group structure |

Importers coerce foreign identifiers into valid CLIF names (lowercase kebab-case) and disambiguate duplicates, so every generated document validates.

Install optional converter dependencies with:

```bash
pip install "clif-format[converters]"
```

## Conversion samples

For every supported format, conversion samples are self-contained in two directories:

```text
examples/clif_to_<format>/
├── <name>.clif      # source CLIF
└── <name>.<ext>     # CLIF -> format result

examples/<format>_to_clif/
├── <name>.<ext>     # source format file
└── <name>.clif      # format -> CLIF result
```

Supported sample formats: `json`, `yaml`, `csv`, `po`, `xliff`, `fluent`, `android`, `ios`.

The generated side of every sample is produced by `tools/regenerate_examples.py`; run it after changing a converter, and `python tools/regenerate_examples.py --check` verifies the samples are current (CI runs this).

Run the conversion tests with:

```bash
pytest tests/test_conversion.py
```

## Repository layout

```text
clif-python/
├── pyproject.toml
├── src/
│   └── pyclif/
│       ├── model.py         # dataclasses for the CLIF data model
│       ├── parser.py        # single-pass line parser
│       ├── serializer.py    # canonical serializer
│       ├── validator.py     # semantic validation and inheritance helpers
│       ├── converter.py     # bidirectional format converters
│       └── cli.py           # pyclif command line
├── tools/
│   └── regenerate_examples.py
├── examples/
└── tests/
```

## License

MIT
