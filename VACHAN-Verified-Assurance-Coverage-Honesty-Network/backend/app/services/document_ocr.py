"""
Document OCR & Text Extraction Service for InsureChain VoiceGuard (Phase 6).
Extracts raw text from uploaded claim evidence (PDFs, images) using deterministic,
multi-stage fallback:
1. Direct PDF Text Extraction using pypdf.
2. Optional OCR rendering and Tesseract extraction (if PyMuPDF & pytesseract are installed).
3. Graceful Fallback (MANUAL_FALLBACK) when OCR engines are unavailable or documents are scanned images.
Never fabricates OCR text or invents extracted numbers.
"""

import io
from pathlib import Path
from typing import Optional, Tuple
import pypdf

from app.core.logging import get_logger

logger = get_logger(__name__)

# Optional dependencies for scanned document OCR
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from PIL import Image
except ImportError:
    Image = None


def is_ocr_engine_available() -> bool:
    """Returns True if PyMuPDF and Tesseract are both installed and configured."""
    return fitz is not None and pytesseract is not None and Image is not None


def extract_text_from_pdf(content: bytes) -> Tuple[str, str, float]:
    """
    Extracts text from PDF bytes.
    Returns:
        (text, extraction_method, confidence_score)
        where extraction_method is one of: PDF_TEXT, OCR_TESSERACT, MANUAL_FALLBACK.
    """
    if not content:
        return "", "MANUAL_FALLBACK", 0.0

    # 1. Attempt pypdf text-based extraction
    try:
        pdf_stream = io.BytesIO(content)
        reader = pypdf.PdfReader(pdf_stream)

        if reader.is_encrypted:
            # Try decrypting with empty password
            try:
                decrypted = reader.decrypt("")
                if decrypted == 0:
                    logger.warning("PDF is password protected and cannot be decrypted without credentials.")
                    return "", "MANUAL_FALLBACK", 0.0
            except Exception as dec_err:
                logger.warning(f"Failed to decrypt PDF: {dec_err}")
                return "", "MANUAL_FALLBACK", 0.0

        num_pages = len(reader.pages)
        if num_pages == 0:
            return "", "MANUAL_FALLBACK", 0.0

        page_texts = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    page_texts.append(page_text.strip())
            except Exception as page_err:
                logger.warning(f"Error extracting text from PDF page {i+1}: {page_err}")

        combined_text = "\n\n".join(page_texts).strip()

        # Check if meaningful text was extracted
        # A normal digital invoice/report has at least 30 characters of meaningful text
        if len(combined_text) >= 30:
            # Score confidence based on text density across pages
            avg_chars_per_page = len(combined_text) / max(num_pages, 1)
            confidence = min(0.98, max(0.70, 0.70 + (avg_chars_per_page / 1000.0) * 0.28))
            return combined_text, "PDF_TEXT", round(confidence, 2)

    except pypdf.errors.PdfReadError as pdf_err:
        logger.warning(f"Corrupted or invalid PDF format: {pdf_err}")
        return "", "MANUAL_FALLBACK", 0.0
    except Exception as exc:
        logger.warning(f"Unexpected error during pypdf extraction: {exc}")

    # 2. Scanned PDF: If pypdf yielded little or no text, try OCR if available
    if is_ocr_engine_available():
        try:
            logger.info("Attempting OCR on scanned PDF pages via PyMuPDF & Tesseract")
            doc = fitz.open(stream=content, filetype="pdf")
            ocr_pages = []
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                page_ocr = pytesseract.image_to_string(img)
                if page_ocr.strip():
                    ocr_pages.append(page_ocr.strip())
            doc.close()

            ocr_text = "\n\n".join(ocr_pages).strip()
            if len(ocr_text) >= 20:
                return ocr_text, "OCR_TESSERACT", 0.85
        except Exception as ocr_err:
            logger.warning(f"Tesseract OCR failed on scanned PDF: {ocr_err}")

    # 3. Fallback when OCR engine is unavailable or produces no text
    logger.info("PDF extraction fell back to MANUAL_FALLBACK (scanned document or unavailable OCR engine)")
    return "", "MANUAL_FALLBACK", 0.0


def extract_text_from_image(content: bytes) -> Tuple[str, str, float]:
    """
    Extracts text from image bytes (PNG, JPEG, etc.).
    Returns (text, extraction_method, confidence_score).
    """
    if not content:
        return "", "MANUAL_FALLBACK", 0.0

    if pytesseract is not None and Image is not None:
        try:
            img = Image.open(io.BytesIO(content))
            text = pytesseract.image_to_string(img).strip()
            if len(text) >= 15:
                return text, "OCR_TESSERACT", 0.80
        except Exception as img_err:
            logger.warning(f"Image OCR failed: {img_err}")

    return "", "MANUAL_FALLBACK", 0.0


def extract_document_text(
    content: bytes,
    mime_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> Tuple[str, str, float]:
    """
    High-level entry point to extract text from claim evidence bytes.
    Dispatches by MIME type or file extension.
    Returns:
        (extracted_text, extraction_method, confidence_score)
    """
    if not content:
        return "", "MANUAL_FALLBACK", 0.0

    norm_mime = (mime_type or "").lower().strip()
    norm_name = (filename or "").lower().strip()

    is_pdf = norm_mime == "application/pdf" or norm_name.endswith(".pdf")
    is_image = (
        norm_mime.startswith("image/")
        or norm_name.endswith(".png")
        or norm_name.endswith(".jpg")
        or norm_name.endswith(".jpeg")
        or norm_name.endswith(".webp")
    )

    if is_pdf:
        return extract_text_from_pdf(content)
    elif is_image:
        return extract_text_from_image(content)
    else:
        # Try PDF reader first if header matches %PDF
        if content.startswith(b"%PDF"):
            return extract_text_from_pdf(content)
        # Otherwise fallback
        return "", "MANUAL_FALLBACK", 0.0

