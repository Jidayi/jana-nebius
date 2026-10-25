"""Representative bounded intake corpus. Real codecs; OCR/ASR model quality is measured separately."""

from __future__ import annotations

import asyncio
import io
import zipfile

import pytest
from agent_core.config import Settings
from agent_core.tools.study_document import DocumentError, extract
from pypdf import PdfWriter
from study_worker import decode


def container(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return out.getvalue()


DOC = {"word/document.xml": "<document><p>Enzymes are catalysts.</p><p>Δx and αβ.</p></document>"}
ODT = {"content.xml": "<document><p>Enzymes are catalysts.</p><p>Δx and αβ.</p></document>"}
ODP = {
    "content.xml": '<document xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">'
    "<draw:page><p>Cells use energy.</p></draw:page></document>"
}
PPT = {
    "ppt/presentation.xml": '<p xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sldId r:id="r1"/></p>',
    "ppt/_rels/presentation.xml.rels": '<rels><rel Id="r1" Target="slides/slide1.xml"/></rels>',
    "ppt/slides/slide1.xml": "<slide><p>Cells contain DNA.</p></slide>",
    "ppt/slides/_rels/slide1.xml.rels": '<rels><rel Id="note" Target="../notesSlides/notesSlide1.xml"/>'
    '<rel Id="remote" TargetMode="External" Target="https://canary.invalid/image"/></rels>',
    "ppt/notesSlides/notesSlide1.xml": "<notes><p>DNA stores information.</p></notes>",
}


@pytest.mark.parametrize(
    ("kind", "data", "expected"),
    [
        ("document", "Enzymes are catalysts. Δx αβ 🧪 e\u0301".encode(), "🧪"),
        ("document", container(DOC), "Δx"),
        ("document", container(ODT), "Enzymes"),
        ("slides", container(ODP), "Cells use energy"),
        ("slides", container(PPT), "Speaker notes:\nDNA stores information"),
    ],
    ids=["utf8", "docx", "odt", "odp", "pptx"],
)
def test_m42_formats_in_actual_sandbox(kind, data, expected):
    units = asyncio.run(extract(data, kind, "renamed title", Settings()))
    assert expected in "\n".join(u["text"] for u in units)
    assert "canary.invalid" not in str(units)


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({**DOC, "word/vbaProject.bin": "macro"}, "unsupported_format"),
        (
            {**DOC, "word/document.xml": '<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><d><p>&x;</p></d>'},
            "corrupt_source",
        ),
        ({**DOC, "bomb.txt": "a" * 20_000_001}, "source_too_large"),
    ],
)
def test_m42_unsafe_archives_refused_without_execution(files, reason):
    with pytest.raises(DocumentError, match=reason):
        decode(container(files), "document", "", 300)


@pytest.mark.parametrize("pages", [30, 300, 301])
def test_m42_pdf_page_boundaries(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    out = io.BytesIO()
    writer.write(out)
    if pages > 300:
        with pytest.raises(DocumentError, match="source_too_large"):
            decode(out.getvalue(), "pdf", "", 300)
    else:
        units = decode(out.getvalue(), "pdf", "", 300)
        assert len(units) == pages and all(u["ocr"] for u in units)


def test_m42_utf8_source_size_boundary():
    assert len(decode(b"x" * (30 * 4000), "document", "", 30)[0]["text"]) == 120000
    with pytest.raises(DocumentError, match="source_too_large"):
        decode(b"x" * (30 * 4000 + 1), "document", "", 30)
