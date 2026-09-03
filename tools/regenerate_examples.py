"""Regenerate the converted files under examples/.

Each examples/clif_to_<format> directory holds a source .clif file and its
converted output; each examples/<format>_to_clif directory holds a source file
in that format and the CLIF document produced from it. Running this script
rewrites every generated side from the current converters, so the examples
never drift away from the library.

Usage:
    python tools/regenerate_examples.py [--check]

With --check the script writes nothing and exits non-zero when any example is
stale, which makes it usable as a CI guard.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from clif_format import (  # noqa: E402  - path setup must precede the import
    ClifDocument,
    from_android_strings,
    from_csv,
    from_fluent,
    from_ios_strings,
    from_json,
    from_po,
    from_xliff,
    from_yaml,
    load,
    serialize,
    to_android_strings,
    to_csv,
    to_fluent,
    to_ios_strings,
    to_json,
    to_po,
    to_xliff,
    to_yaml,
)

EXAMPLES = REPO_ROOT / "examples"

Exporter = Callable[[ClifDocument], str]
Importer = Callable[[str], ClifDocument]

# format name -> (converted file suffix, exporter, importer)
FORMATS: dict[str, tuple[str, Exporter, Importer]] = {
    "json": (".json", lambda doc: to_json(doc, indent=2, ensure_ascii=False), from_json),
    "yaml": (".yaml", to_yaml, from_yaml),
    "csv": (".csv", to_csv, from_csv),
    "po": (".po", to_po, from_po),
    "xliff": (".xlf", to_xliff, from_xliff),
    "fluent": (".ftl", to_fluent, from_fluent),
    "android": ("strings.xml", to_android_strings, from_android_strings),
    "ios": ("Localizable.strings", to_ios_strings, from_ios_strings),
}


def _converted_path(directory: Path, clif_path: Path, suffix: str) -> Path:
    """Where the converted twin of a .clif file lives in an example directory."""
    if suffix.startswith("."):
        return directory / (clif_path.name[: -len(".clif")] + suffix)
    return directory / suffix


def _clif_target(directory: Path, source: Path, existing: list[Path]) -> Path:
    """The .clif file an imported example writes to.

    Example directories pair one source file with one CLIF document, and some
    source files carry a platform name (strings.xml, Localizable.strings) that
    does not share the CLIF file stem, so the existing document wins whenever
    the directory holds exactly one.
    """
    stem = source.name.split(".")[0]
    for candidate in existing:
        if candidate.name.split(".")[0] == stem:
            return candidate
    if len(existing) == 1:
        return existing[0]
    return directory / f"{stem}.clif"


def _write(path: Path, text: str, *, check: bool, stale: list[Path]) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if check:
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != text:
            stale.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def regenerate(*, check: bool = False) -> list[Path]:
    """Rewrite (or verify) every generated example. Returns the stale paths."""
    stale: list[Path] = []
    for name, (suffix, export, importer) in FORMATS.items():
        export_dir = EXAMPLES / f"clif_to_{name}"
        if export_dir.is_dir():
            for clif_path in sorted(export_dir.glob("*.clif")):
                document = load(clif_path)
                target = _converted_path(export_dir, clif_path, suffix)
                _write(target, export(document), check=check, stale=stale)

        import_dir = EXAMPLES / f"{name}_to_clif"
        if import_dir.is_dir():
            existing = sorted(import_dir.glob("*.clif"))
            for source_path in sorted(import_dir.iterdir()):
                if source_path.suffix == ".clif" or not source_path.is_file():
                    continue
                document = importer(source_path.read_text(encoding="utf-8"))
                target = _clif_target(import_dir, source_path, existing)
                _write(target, serialize(document), check=check, stale=stale)
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the examples are current instead of rewriting them",
    )
    args = parser.parse_args(argv)
    stale = regenerate(check=args.check)
    if args.check and stale:
        print("stale examples (run tools/regenerate_examples.py):", file=sys.stderr)
        for path in stale:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
