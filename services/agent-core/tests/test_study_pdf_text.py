"""Legacy PDF symbols are decoded without guessing lost formula structure."""

from study_worker.pdf_text import normalize_pdf_text


def test_legacy_delimiter_pieces_keep_line_breaks_and_valid_superscripts():
    assert normalize_pdf_text("Φ = \uf8eb\n\uf8ec\uf8ed x² \uf8f6\uf8f7\uf8f8") == "Φ = ⎛\n⎜⎝ x² ⎞⎟⎠"
    assert normalize_pdf_text("\uf8f1\uf8f4\uf8f2\uf8f3") == "⎧⎪⎨⎩"


def test_no_blanket_unicode_normalization_or_formula_reconstruction():
    text = "x² + αᵢ − 1; unknown private symbol \ue123; flattened 1n"
    assert normalize_pdf_text(text) == text


def test_pdf_decoder_normalizes_embedded_legacy_font_mapping():
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    from study_worker import decode

    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    cmap = DecodedStreamObject()
    cmap.set_data(b"1 begincodespacerange <00> <FF> endcodespacerange\n2 beginbfchar <41> <F8F1> <42> <F8F3> endbfchar")
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/ToUnicode"): writer._add_object(cmap),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 72 700 Td (AB) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    assert decode(output.getvalue(), "pdf", "formula.pdf")[0]["text"] == "⎧⎩"
