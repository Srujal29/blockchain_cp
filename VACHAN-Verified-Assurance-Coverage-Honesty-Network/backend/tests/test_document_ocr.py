"""
Unit tests for Document OCR & Text Extraction Service (Phase 6 Stage 1).
Validates pypdf text extraction, MIME type dispatching, graceful fallbacks
for scanned/image documents without OCR engine, and corrupted file handling.
"""

import io
import pytest
import pypdf

from app.services.document_ocr import (
    extract_document_text,
    extract_text_from_pdf,
    extract_text_from_image,
    is_ocr_engine_available,
)

SAMPLE_PDF_BYTES = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj
4 0 obj<</Length 73>>stream
BT
/F1 12 Tf
100 700 Td
(City Care Hospital - Tax Invoice - Total: 15000.00) Tj
ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000236 00000 n
0000000360 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
434
%%EOF"""


def test_ocr_engine_availability_detection():
    # In sandbox/environment without Tesseract/PyMuPDF, must return False or reflect truth
    avail = is_ocr_engine_available()
    assert isinstance(avail, bool)


def test_extract_text_from_valid_pdf():
    text, method, confidence = extract_text_from_pdf(SAMPLE_PDF_BYTES)
    assert method == "PDF_TEXT"
    assert "City Care Hospital" in text
    assert "15000.00" in text
    assert confidence >= 0.70


def test_extract_text_empty_input():
    text, method, confidence = extract_document_text(b"", mime_type="application/pdf")
    assert text == ""
    assert method == "MANUAL_FALLBACK"
    assert confidence == 0.0


def test_extract_text_corrupted_pdf():
    corrupted_bytes = b"%PDF-1.4 corrupted dummy header with invalid binary data \x00\xff\xee"
    text, method, confidence = extract_document_text(corrupted_bytes, mime_type="application/pdf")
    assert text == ""
    assert method == "MANUAL_FALLBACK"
    assert confidence == 0.0


def test_extract_text_blank_pdf_page():
    # Create a blank PDF using pypdf writer with no text content
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    blank_pdf_bytes = buf.getvalue()

    text, method, confidence = extract_document_text(blank_pdf_bytes, filename="blank.pdf")
    # Blank PDF has no text and without OCR should fall back to MANUAL_FALLBACK
    assert text == ""
    assert method == "MANUAL_FALLBACK"
    assert confidence == 0.0


def test_extract_text_from_image_fallback():
    # 1x1 PNG pixel bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    text, method, confidence = extract_text_from_image(png_bytes)
    # Without pytesseract installed, must gracefully return MANUAL_FALLBACK
    assert method in ("OCR_TESSERACT", "MANUAL_FALLBACK")
    if method == "MANUAL_FALLBACK":
        assert text == ""
        assert confidence == 0.0


def test_extract_document_text_mime_dispatch():
    # PDF mime type
    text, method, conf = extract_document_text(SAMPLE_PDF_BYTES, mime_type="application/pdf")
    assert method == "PDF_TEXT"
    assert "City Care Hospital" in text

    # PDF filename
    text2, method2, conf2 = extract_document_text(SAMPLE_PDF_BYTES, filename="invoice_scan.pdf")
    assert method2 == "PDF_TEXT"
    assert "City Care Hospital" in text2

    # PDF magic byte header without mime type or filename
    text3, method3, conf3 = extract_document_text(SAMPLE_PDF_BYTES)
    assert method3 == "PDF_TEXT"
    assert "City Care Hospital" in text3


def test_encrypted_pdf_fallback():
    # Create an encrypted PDF with a password
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    writer.encrypt("supersecret")
    buf = io.BytesIO()
    writer.write(buf)
    encrypted_bytes = buf.getvalue()

    text, method, conf = extract_text_from_pdf(encrypted_bytes)
    assert text == ""
    assert method == "MANUAL_FALLBACK"
    assert conf == 0.0

