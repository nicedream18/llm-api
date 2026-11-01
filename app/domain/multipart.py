"""Small, dependency-free helpers for forwarding multipart gateway requests."""

from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser

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


def replace_model(payload: bytes, model: str, upstream_model: str) -> bytes:
    """Replace only the text model field, preserving file bytes and boundaries."""
    if not model or model == upstream_model:
        return payload
    match = _MODEL_FIELD.search(payload)
    if not match:
        return payload
    return payload[: match.start("value")] + upstream_model.encode("utf-8") + payload[match.end("value") :]
