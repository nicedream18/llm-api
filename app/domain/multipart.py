"""Small, dependency-free helpers for forwarding multipart gateway requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from itertools import pairwise

_MODEL_FIELD = re.compile(
    rb"(?P<prefix>Content-Disposition:[^\r\n]*\bname=[\"']model[\"'][^\r\n]*\r\n(?:[A-Za-z-]+:[^\r\n]*\r\n)*\r\n)(?P<value>[^\r\n]*)",
    re.IGNORECASE,
)


def multipart_fields(content_type: str | None, payload: bytes) -> dict[str, str]:
    """Extract non-file fields without reading or persisting uploaded files."""
    if not content_type or not content_type.lower().startswith("multipart/"):
        return {}
    header = b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n"
    message = BytesParser(policy=policy.default).parsebytes(header + payload)
    if not message.is_multipart():
        return {}
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if disposition != "form-data" or not name or filename:
            continue
        decoded = part.get_payload(decode=True)
        value = decoded if isinstance(decoded, bytes) else b""
        charset = part.get_content_charset() or "utf-8"
        fields[str(name)] = value.decode(charset, "replace")
    return fields


def multipart_files(content_type: str | None, payload: bytes) -> dict[str, tuple[str, str, bytes]]:
    """Return uploaded files as name -> (filename, media type, bytes)."""
    if not content_type or not content_type.lower().startswith("multipart/"):
        return {}
    header = b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n"
    message = BytesParser(policy=policy.default).parsebytes(header + payload)
    if not message.is_multipart():
        return {}
    files: dict[str, tuple[str, str, bytes]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if not name or not filename:
            continue
        decoded = part.get_payload(decode=True)
        files[str(name)] = (str(filename), str(part.get_content_type()), decoded if isinstance(decoded, bytes) else b"")
    return files


def replace_model(payload: bytes, model: str, upstream_model: str) -> bytes:
    """Replace only the text model field, preserving file bytes and boundaries."""
    if not model or model == upstream_model:
        return payload
    match = _MODEL_FIELD.search(payload)
    if not match:
        return payload
    return payload[: match.start("value")] + upstream_model.encode("utf-8") + payload[match.end("value") :]


# These offsets allow text replacements without MIME re-serialization of files.


@dataclass(frozen=True)
class TextPart:
    name: str
    value: str
    start: int
    end: int
    charset: str


def multipart_text_parts(content_type: str | None, payload: bytes) -> list[TextPart]:
    header = BytesParser(policy=policy.default).parsebytes(b"Content-Type: " + (content_type or "").encode("latin-1") + b"\r\n\r\n")
    boundary = header.get_boundary()
    if not boundary:
        raise ValueError("Missing multipart boundary")
    delimiter = re.compile(rb"(?:\A|\r\n)--" + re.escape(boundary.encode("ascii")) + rb"(?P<close>--)?(?:\r\n|\Z)")
    markers = list(delimiter.finditer(payload))
    if len(markers) < 2 or not markers[-1].group("close"):
        raise ValueError("Incomplete multipart body")
    result = []
    for marker, following in pairwise(markers):
        if marker.group("close"):
            raise ValueError("Unexpected multipart terminator")
        start = marker.end()
        header_end = payload.find(b"\r\n\r\n", start, following.start())
        if header_end < 0:
            raise ValueError("Missing part headers")
        headers = BytesParser(policy=policy.default).parsebytes(payload[start:header_end] + b"\r\n\r\n")
        name = headers.get_param("name", header="content-disposition")
        if headers.get_content_disposition() != "form-data" or not name or headers.get_filename() is not None:
            continue
        start = header_end + 4
        charset = headers.get_content_charset() or "utf-8"
        result.append(TextPart(str(name), payload[start:following.start()].decode(charset), start, following.start(), charset))
    return result


def replace_text_parts(payload: bytes, parts: list[TextPart], values: list[str]) -> bytes:
    for part, value in reversed(list(zip(parts, values, strict=True))):
        payload = payload[:part.start] + value.encode(part.charset) + payload[part.end:]
    return payload
