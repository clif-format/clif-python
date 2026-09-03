from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import ClifParseError
from .model import ClifDocument, Entry, Group, Header

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
VERSION_RE = re.compile(r"^\s*CLIF\s+1\.0\s*$")
SECTION_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
ENTRY_RE = re.compile(r"^\s*<([^<>]+)>\s*$")
LANG_RE = re.compile(r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$")

HEADER_KEYS = {
    "namespace",
    "clan",
    "source-language",
    "target-language",
    "version",
    "variant",
    "title",
    "info",
    "standard",
    "dependency",
}
GROUP_KEYS = {"context", "type", "emotion", "max-width"}
ENTRY_KEYS = {
    "source",
    "target",
    "type",
    "emotion",
    "status",
    "context",
    "max-width",
    "reference",
    "reviewer",
}
STRING_KEYS = {"version", "title", "info", "standard", "source", "target", "context", "reviewer"}
LIST_KEYS = {"emotion", "dependency", "reference"}
NAME_KEYS = {"namespace", "clan"}
LANG_KEYS = {"source-language", "target-language"}
INT_KEYS = {"max-width"}
TAG_KEYS = {"variant", "type", "status"}

ESCAPES = {'"': '"', "'": "'", "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}

_LIST_HINTS = {
    "emotion": "emotion: [neutral]",
    "dependency": 'dependency: ["../terms/terms.zh-CN.clif"]',
    "reference": 'reference: ["src/ui.cpp:12"]',
}


def _normalize_lines(text: str) -> list[str]:
    if text.startswith("\ufeff"):
        text = text[1:]
    if "\r" in text:
        text = text.replace("\r\n", "\n")
        if "\r" in text:
            raise ClifParseError("bare CR is not a valid line ending")
    return text.split("\n")


def _is_ignorable(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


def _starts_quote(text: str) -> bool:
    return text.startswith('"') or text.startswith("'")


def _unescape(text: str, quote: str) -> str:
    allowed = {'"', "\\", "n", "r", "t"} if quote == '"' else {"'", "\\", "n", "r", "t"}
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            if i + 1 >= len(text):
                raise ClifParseError("trailing backslash")
            nxt = text[i + 1]
            if nxt not in allowed:
                raise ClifParseError(f"unknown escape sequence \\{nxt}")
            out.append(ESCAPES[nxt])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_string_at(text: str) -> tuple[str, str]:
    if text.startswith('"'):
        quote = '"'
    elif text.startswith("'"):
        quote = "'"
    else:
        raise ClifParseError("expected a quoted string")

    i = 1
    out: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == quote:
            value = _unescape("".join(out), quote)
            return value, text[i + 1 :]
        if ch == "\\":
            if i + 1 >= len(text):
                raise ClifParseError("trailing backslash")
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch in "\n\r\t" or ord(ch) < 0x20:
            raise ClifParseError("raw control character inside string")
        out.append(ch)
        i += 1
    raise ClifParseError("unterminated string")


def _parse_adjacent_strings(text: str) -> str:
    text = text.strip()
    if not text:
        raise ClifParseError("empty value")
    parts: list[str] = []
    rest = text
    while rest:
        if not _starts_quote(rest):
            raise ClifParseError("expected a quoted string")
        value, after = _parse_string_at(rest)
        parts.append(value)
        rest = after.lstrip()
    return "".join(parts)


def _find_separator(text: str) -> int | None:
    """Index of the first "=" or ":" that sits outside a quoted string."""
    quote: str | None = None
    escaped = False
    for i, ch in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "=:":
            return i
    return None


def _parse_field_line(line: str) -> tuple[str, str]:
    idx = _find_separator(line)
    if idx is None:
        raise ClifParseError("expected 'key: value' or 'key = value' field")
    key = line[:idx].strip()
    value = line[idx + 1 :].strip()
    if not NAME_RE.match(key):
        raise ClifParseError(f"invalid field name '{key}' (lowercase kebab-case required)")
    return key, value


def _split_list_items(body: str) -> list[str]:
    """Split a list body on commas that sit outside quoted strings."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in body:
        if quote is not None:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if quote is not None:
        raise ClifParseError("unterminated string inside list")
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_tag(text: str) -> str:
    """Parse a fixed-vocabulary tag, which the grammar defines as a bare name."""
    text = text.strip()
    if not text:
        raise ClifParseError("empty tag")
    if _starts_quote(text):
        raise ClifParseError(
            f"tag values are unquoted lowercase names; write {text.strip(chr(34) + chr(39))}"
            " without quotes"
        )
    if not NAME_RE.match(text):
        raise ClifParseError(f"{text!r} is not a valid tag (lowercase kebab-case required)")
    return text


def _parse_list(text: str, key: str) -> list[str]:
    text = text.strip()
    if not text.startswith("["):
        raise ClifParseError(f"{key} must be a single-line list")
    if not text.endswith("]"):
        raise ClifParseError("unclosed list (closing bracket must be on the same line)")
    body = text[1:-1].strip()
    if not body:
        return []
    items: list[str] = []
    for part in _split_list_items(body):
        part = part.strip()
        if not part:
            raise ClifParseError("empty list item")
        if part.startswith("["):
            raise ClifParseError("nested lists are not allowed")
        if key in ("dependency", "reference"):
            if not _starts_quote(part):
                raise ClifParseError(f"{key} list items must be quoted strings")
            value, rest = _parse_string_at(part)
            if rest.strip():
                raise ClifParseError(f"unexpected content after closing quote in {key} list")
            items.append(value)
        elif key == "emotion":
            items.append(_parse_tag(part))
        elif _starts_quote(part):
            value, rest = _parse_string_at(part)
            if rest.strip():
                raise ClifParseError("unexpected content after closing quote in list")
            items.append(value)
        else:
            items.append(_parse_tag(part))
    return items


def _check_extension_value(text: str) -> str:
    """Validate an x- extension value and return its raw text unchanged.

    Extension values are opaque to clif_format: the spec requires parsers to ignore
    them without changing their meaning, so the raw source text is preserved
    and re-emitted verbatim by the serializer. Only well-formedness is checked.
    """
    text = text.strip()
    if not text:
        raise ClifParseError("empty value")
    if text.startswith("["):
        _parse_list(text, "extension")
    elif _starts_quote(text):
        _parse_adjacent_strings(text)
    elif not text.isdigit() and not NAME_RE.match(text) and not LANG_RE.match(text):
        raise ClifParseError(f"{text!r} is not a valid string, list, integer, or name")
    return text


def _parse_scalar(text: str, key: str) -> Any:
    text = text.strip()
    if not text:
        raise ClifParseError("empty value")
    if _starts_quote(text):
        value, rest = _parse_string_at(text)
        if rest.strip():
            raise ClifParseError("unexpected content after the closing quote")
        return value
    if key in LANG_KEYS:
        if not LANG_RE.match(text):
            raise ClifParseError(f"'{text}' is not a plausible BCP 47 language tag")
        return text
    if key in NAME_KEYS:
        if not NAME_RE.match(text):
            raise ClifParseError(f"'{text}' is not a valid name (lowercase kebab-case required)")
        return text
    if key in INT_KEYS:
        if not text.isdigit() or int(text) <= 0:
            raise ClifParseError(f"'{text}' is not a positive integer")
        return int(text)
    if NAME_RE.match(text):
        return text
    raise ClifParseError(f"'{text}' is not a valid name, string, or integer")


def _parse_value(text: str, key: str) -> Any:
    text = text.strip()
    if key in STRING_KEYS:
        return _parse_adjacent_strings(text)
    if key in LIST_KEYS:
        if not text.startswith("["):
            raise ClifParseError(
                f"{key} is a list-typed field and must be written as a list, "
                f"even for a single item (for example: {_LIST_HINTS[key]})"
            )
        return _parse_list(text, key)
    if key in TAG_KEYS:
        return _parse_tag(text)
    return _parse_scalar(text, key)


@contextmanager
def _located(line: int, text: str) -> Iterator[None]:
    """Attach the current line number and source text to a parse error.

    Value-level helpers do not know where they are being called from, so the
    main loop enriches whatever they raise. Every CLIF diagnostic has to carry
    a line number and the offending line.
    """
    try:
        yield
    except ClifParseError as exc:
        if not exc.line:
            exc.line = line
            exc.text = text
        raise


def _valid_group_path(path: str) -> bool:
    return bool(path) and all(NAME_RE.match(segment) for segment in path.split("."))


def _set_multiline_string(container: Any, key: str, fragment: str) -> None:
    if isinstance(container, Header):
        if key in {"version", "title", "info", "standard"}:
            current = getattr(container, key)
            setattr(container, key, (current or "") + fragment)
    elif isinstance(container, Group):
        if key == "context":
            container.context = (container.context or "") + fragment
    elif isinstance(container, Entry):
        if key in {"source", "target", "context", "reviewer"}:
            current = getattr(container, key)
            setattr(container, key, (current or "") + fragment)


def _append_list(container: Any, key: str, items: list[str]) -> None:
    if isinstance(container, Header):
        if key == "dependency":
            container.dependency.extend(items)
    elif isinstance(container, Group):
        if key == "emotion":
            container.emotion.extend(items)
    elif isinstance(container, Entry):
        if key == "emotion":
            container.emotion.extend(items)
        elif key == "reference":
            container.reference.extend(items)


def _assign_header(header: Header, key: str, value: str) -> None:
    if key.startswith("x-"):
        header.extensions[key] = _check_extension_value(value)
        return
    parsed = _parse_value(value, key)
    if key == "namespace":
        header.namespace = parsed
    elif key == "clan":
        header.clan = parsed
    elif key == "source-language":
        header.source_language = parsed
    elif key == "target-language":
        header.target_language = parsed
    elif key == "version":
        header.version = parsed
    elif key == "variant":
        header.variant = parsed
    elif key == "title":
        header.title = parsed
    elif key == "info":
        header.info = parsed
    elif key == "standard":
        header.standard = parsed
    elif key == "dependency":
        header.dependency = parsed
    else:  # pragma: no cover - guarded by HEADER_KEYS
        raise ClifParseError(f"unknown header key '{key}'", category="semantic")


def _assign_group(group: Group, key: str, value: str) -> None:
    if key.startswith("x-"):
        group.extensions[key] = _check_extension_value(value)
        return
    parsed = _parse_value(value, key)
    if key == "context":
        group.context = parsed
    elif key == "type":
        group.type = parsed
    elif key == "emotion":
        group.emotion = parsed
    elif key == "max-width":
        group.max_width = parsed
    else:  # pragma: no cover - guarded by GROUP_KEYS
        raise ClifParseError(f"key '{key}' is not allowed in group metadata", category="semantic")


def _assign_entry(entry: Entry, key: str, value: str) -> None:
    if key.startswith("x-"):
        entry.extensions[key] = _check_extension_value(value)
        return
    parsed = _parse_value(value, key)
    if key == "source":
        entry.source = parsed
    elif key == "target":
        entry.target = parsed
    elif key == "type":
        entry.type = parsed
    elif key == "emotion":
        entry.emotion = parsed
    elif key == "status":
        entry.status = parsed
    elif key == "context":
        entry.context = parsed
    elif key == "max-width":
        entry.max_width = parsed
    elif key == "reference":
        entry.reference = parsed
    elif key == "reviewer":
        entry.reviewer = parsed
    else:  # pragma: no cover - guarded by ENTRY_KEYS
        raise ClifParseError(f"unknown entry key '{key}'", category="semantic")


def parse(text: str, *, path: str | Path | None = None) -> ClifDocument:
    """Parse CLIF text into a :class:`ClifDocument`.

    Raises :class:`ClifParseError` when the input is not well-formed enough
    to build the data model. Semantic validation is intentionally separate;
    use :func:`clif_format.validate` for the full validator.
    """
    doc = ClifDocument(path=Path(path) if path is not None else None)
    lines = _normalize_lines(text)
    seen_version = False
    current_group: Group | None = None
    current_entry: Entry | None = None
    last_container: Any = None
    last_key: str | None = None
    seen_header: set[str] = set()
    seen_group: set[str] = set()
    seen_entry: set[str] = set()

    for idx, raw in enumerate(lines, start=1):
        line = raw
        if _is_ignorable(line):
            last_container = None
            last_key = None
            continue

        if not seen_version:
            if VERSION_RE.match(line):
                seen_version = True
                continue
            raise ClifParseError(
                "version line 'CLIF 1.0' must be the first non-blank, non-comment line",
                line=idx,
                text=raw,
            )

        section = SECTION_RE.match(line)
        if section:
            group_path = section.group(1).strip()
            if _valid_group_path(group_path):
                current_group = Group(path=group_path, line=idx)
                doc.groups.append(current_group)
                current_entry = None
                seen_group = set()
                last_container = None
                last_key = None
                continue
            # A bare list continuation looks exactly like a section line, so
            # the bracket content decides: only a valid group path is a
            # section, and anything else continues an open list field.
            if not (last_container is not None and last_key in LIST_KEYS):
                raise ClifParseError(
                    f"invalid group path '[{group_path}]'; "
                    "segments must be lowercase kebab-case names",
                    line=idx,
                    category="id",
                    text=raw,
                )

        entry = ENTRY_RE.match(line)
        if entry:
            if current_group is None:
                raise ClifParseError(
                    "entry declared before any [group] section",
                    line=idx,
                    text=raw,
                )
            entry_id = entry.group(1)
            if not NAME_RE.match(entry_id):
                raise ClifParseError(
                    f"invalid entry id '{entry_id}'; use lowercase kebab-case names",
                    line=idx,
                    category="id",
                    text=raw,
                )
            current_entry = Entry(id=entry_id, line=idx)
            current_group.entries.append(current_entry)
            seen_entry = set()
            last_container = None
            last_key = None
            continue

        if last_container is not None and last_key is not None:
            stripped = line.strip()
            if last_key in STRING_KEYS and _starts_quote(stripped):
                with _located(idx, raw):
                    fragment = _parse_adjacent_strings(stripped)
                _set_multiline_string(last_container, last_key, fragment)
                continue
            if last_key in LIST_KEYS and stripped.startswith("["):
                with _located(idx, raw):
                    items = _parse_list(stripped, last_key)
                _append_list(last_container, last_key, items)
                continue
            if _starts_quote(stripped) or stripped.startswith("["):
                raise ClifParseError(
                    f"continuation line does not match the preceding '{last_key}' field",
                    line=idx,
                    text=raw,
                )

        with _located(idx, raw):
            key, value_text = _parse_field_line(line)

        if current_group is None:
            if key in seen_header:
                raise ClifParseError(
                    f"header field '{key}' may appear at most once (CLIF has no repeatable fields)",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            if key not in HEADER_KEYS and not key.startswith("x-"):
                raise ClifParseError(
                    f"unknown header key '{key}'; known keys: {', '.join(sorted(HEADER_KEYS))}",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            seen_header.add(key)
            with _located(idx, raw):
                _assign_header(doc.header, key, value_text)
            last_container = doc.header
        elif current_entry is not None:
            if key in seen_entry:
                raise ClifParseError(
                    f"entry field '{key}' may appear at most once (CLIF has no repeatable fields)",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            if key not in ENTRY_KEYS and not key.startswith("x-"):
                raise ClifParseError(
                    f"unknown entry key '{key}'; known keys: {', '.join(sorted(ENTRY_KEYS))}",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            seen_entry.add(key)
            with _located(idx, raw):
                _assign_entry(current_entry, key, value_text)
            last_container = current_entry
        else:
            if key in seen_group:
                raise ClifParseError(
                    f"group field '{key}' may appear at most once (CLIF has no repeatable fields)",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            if key not in GROUP_KEYS and not key.startswith("x-"):
                raise ClifParseError(
                    f"key '{key}' is not allowed in group metadata "
                    f"(allowed: {', '.join(sorted(GROUP_KEYS))})",
                    line=idx,
                    category="semantic",
                    text=raw,
                )
            seen_group.add(key)
            with _located(idx, raw):
                _assign_group(current_group, key, value_text)
            last_container = current_group

        last_key = key

    if not seen_version:
        raise ClifParseError("empty file")

    return doc


def load(path: str | Path) -> ClifDocument:
    """Read and parse a ``.clif`` file from disk."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ClifParseError(f"file is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ClifParseError(f"cannot read file: {exc}") from exc
    return parse(text, path=p)
