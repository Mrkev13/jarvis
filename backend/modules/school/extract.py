"""Bounded, local text extraction from stored study materials (MRK-42).

The binary stays authoritative; text is derived and may be rebuilt. Nothing is executed, rendered or sent anywhere
(no LLM): PDF via pypdf, PPTX/DOCX by reading their XML parts from the zip in memory (DOCTYPE/entities refused,
entry sizes capped), TXT as UTF-8. Any failure yields a status, never an exception or a deletion.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree
from xml.parsers import expat

MAX_TEXT_CHARS = 200_000
MAX_PDF_PAGES = 300
MAX_XML_PART_BYTES = 20 * 1024 * 1024
MAX_XML_TOTAL_BYTES = 100 * 1024 * 1024
MAX_SLIDES = 500
# PDF page boundary marker line (U+27E6/U+27E7 – not expected in study texts)
PAGE_MARK_OPEN, PAGE_MARK_CLOSE = '\u27e6', '\u27e7'

_A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
_SLIDE_RE = re.compile(r'^ppt/slides/slide(\d+)\.xml$')

logging.getLogger('pypdf').setLevel(logging.ERROR)  # malformed-PDF chatter is not actionable


@dataclass(frozen=True)
class Extraction:
    status: str  # ok | empty | truncated | failed | unsupported
    text: str | None


# C0 control characters other than tab/newline/CR/FF/VT (those are normalised as whitespace below) and DEL.
# NUL in particular: PDF text layers can contain it, SQLite stores it, PostgreSQL rejects it in text columns – one
# such file used to abort the whole sync/import transaction.
_CONTROL = re.compile(r'[\x00-\x08\x0e-\x1f\x7f]')


def _finish(parts) -> Extraction:
    text = _CONTROL.sub('', '\n'.join(p for p in parts if p))
    text = re.sub(r'[ \t\r\f\v]+', ' ', text).strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    if not text:
        return Extraction('empty', None)
    if len(text) > MAX_TEXT_CHARS:
        return Extraction('truncated', text[:MAX_TEXT_CHARS])
    return Extraction('ok', text)


def page_marker(number: int) -> str:
    """Line marking the start of PDF page `number` in extracted text (MRK-44 reading uses it for locations).
    Text extracted before MRK-44 has no markers; readers then report no page numbers rather than guess."""
    return f'{PAGE_MARK_OPEN}{number}{PAGE_MARK_CLOSE}'


def _pdf(data: bytes) -> Extraction:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts, total, truncated = [], 0, False
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES or total > MAX_TEXT_CHARS:
            truncated = True
            break
        chunk = (page.extract_text() or '').strip()
        if chunk:  # pages without a text layer (scans) get no marker either
            parts += [page_marker(index + 1), chunk]
            total += len(chunk)
    if not parts:
        return Extraction('empty', None)  # e.g. a scanned PDF: no text layer, no OCR
    result = _finish(parts)
    return Extraction('truncated', result.text) if truncated and result.text else result


def _xml(archive: zipfile.ZipFile, name: str, budget: list[int]):
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_PART_BYTES or info.file_size > budget[0]:
        raise ValueError('xml part too large')
    budget[0] -= info.file_size
    raw = archive.read(name)
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('doctype refused')
    _refuse_dtd(raw)
    return ElementTree.fromstring(raw)


def _refuse_dtd(raw: bytes) -> None:
    """Encoding-independent pre-scan (also UTF-16 parts): any DTD or entity declaration aborts. ElementTree
    never resolves external entities and expat keeps its amplification limits; this refuses DTDs outright."""
    def refuse(*_args):
        raise ValueError('DTD refused')
    scanner = expat.ParserCreate()
    scanner.StartDoctypeDeclHandler = refuse
    scanner.EntityDeclHandler = refuse
    scanner.Parse(raw, True)


def _pptx(data: bytes) -> Extraction:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        slides = sorted(((int(m.group(1)), n) for n in archive.namelist() if (m := _SLIDE_RE.match(n))))
        budget, parts = [MAX_XML_TOTAL_BYTES], []
        for number, name in slides[:MAX_SLIDES]:
            root = _xml(archive, name, budget)
            texts = [t.text for t in root.iter(f'{_A}t') if t.text]
            if texts:
                parts.append(f'[{number}] ' + ' '.join(texts))
    result = _finish(parts)
    return Extraction('truncated', result.text) if len(slides) > MAX_SLIDES and result.text else result


def _docx(data: bytes) -> Extraction:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = _xml(archive, 'word/document.xml', [MAX_XML_TOTAL_BYTES])
    parts = [''.join(t.text or '' for t in p.iter(f'{_W}t')) for p in root.iter(f'{_W}p')]
    return _finish(parts)


def _txt(data: bytes) -> Extraction:
    return _finish([data.decode('utf-8', errors='replace')])


_EXTRACTORS = {'pdf': _pdf, 'pptx': _pptx, 'docx': _docx, 'txt': _txt}


def extract_text(data: bytes, material_type: str) -> Extraction:
    extractor = _EXTRACTORS.get(material_type)
    if extractor is None:
        return Extraction('unsupported', None)
    try:
        return extractor(data)
    except Exception:  # noqa: BLE001 - extraction never breaks a sync or deletes the binary
        return Extraction('failed', None)
