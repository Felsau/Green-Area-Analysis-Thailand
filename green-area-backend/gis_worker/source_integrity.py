"""Versioned hash schemes for reviewed source text versus raw artifact bytes.

Two schemes, never mixed:

* ``source-text-lf-sha256-v1`` -- for reviewed *text* (Python sources, reviewed
  JSON registries). The only normalisation is CRLF -> LF, so the same reviewed
  text checked out on Windows (CRLF) or Linux (LF) has one identity. Nothing else
  is touched: no whitespace stripping, no comment removal, no AST rewriting, no
  BOM removal. A lone CR, a NUL byte or invalid UTF-8 is rejected instead of
  being normalised, so a change in logic, constants or calls still changes the
  hash.
* ``raw-bytes-sha256`` -- for artifacts (ZIP, Shapefile, GeoTIFF, fixtures,
  uploaded files, SQL migrations, ledger values). Every byte counts.

``raw-crlf-sha256-v0`` names the historical identities that were reviewed on a
Windows CRLF checkout before this scheme existed. They are kept unchanged (they
are bound in applied migrations 035/044 and in old manifests/results) and are
only ever *derived* from the reviewed LF text by ``legacy_crlf_sha256``; they are
never computed from file bytes and never reinterpreted as the new scheme.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

SOURCE_TEXT_SCHEME = 'source-text-lf-sha256-v1'
RAW_BYTES_SCHEME = 'raw-bytes-sha256'
LEGACY_CRLF_SCHEME = 'raw-crlf-sha256-v0'
SCHEMES = (SOURCE_TEXT_SCHEME, RAW_BYTES_SCHEME, LEGACY_CRLF_SCHEME)
MAX_SOURCE_BYTES = 2_000_000


class SourceIntegrityError(ValueError):
    """Fixed public code only."""


def _require(condition, code):
    if not condition:
        raise SourceIntegrityError(code)


def canonical_source_text(raw: bytes) -> bytes:
    """Return reviewed text with CRLF line endings rewritten to LF, and nothing else."""
    _require(isinstance(raw, (bytes, bytearray)) and len(raw) <= MAX_SOURCE_BYTES, 'SOURCE_TEXT_INVALID')
    raw = bytes(raw)
    _require(b'\x00' not in raw, 'SOURCE_TEXT_INVALID')
    try:
        raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        raise SourceIntegrityError('SOURCE_TEXT_INVALID') from None
    text = raw.replace(b'\r\n', b'\n')
    # Old Mac line endings or stray CRs are not a platform checkout difference.
    _require(b'\r' not in text, 'SOURCE_TEXT_INVALID')
    return text


def source_text_sha256(raw: bytes) -> str:
    return hashlib.sha256(canonical_source_text(raw)).hexdigest()


def raw_sha256(raw: bytes) -> str:
    _require(isinstance(raw, (bytes, bytearray)), 'ARTIFACT_INVALID')
    return hashlib.sha256(bytes(raw)).hexdigest()


def legacy_crlf_sha256(raw: bytes) -> str:
    """Historical v0 identity of the same reviewed text (Windows CRLF checkout)."""
    return hashlib.sha256(canonical_source_text(raw).replace(b'\n', b'\r\n')).hexdigest()


def digest(raw: bytes, scheme: str) -> str:
    if scheme == SOURCE_TEXT_SCHEME:
        return source_text_sha256(raw)
    if scheme == RAW_BYTES_SCHEME:
        return raw_sha256(raw)
    if scheme == LEGACY_CRLF_SCHEME:
        return legacy_crlf_sha256(raw)
    raise SourceIntegrityError('HASH_SCHEME_UNKNOWN')


def read_regular_file(path: Path, *, limit: int = MAX_SOURCE_BYTES) -> bytes:
    path = Path(path)
    _require(path.is_file() and not path.is_symlink(), 'SOURCE_UNAVAILABLE')
    raw = path.read_bytes()
    _require(len(raw) <= limit, 'SOURCE_TEXT_INVALID')
    return raw


def verify(raw: bytes, expected: str, scheme: str) -> bool:
    """True only for an exact match under the *declared* scheme (no fallback)."""
    try:
        return digest(raw, scheme) == expected
    except SourceIntegrityError:
        return False
