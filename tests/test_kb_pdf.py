import pytest

from app.application.services.kb_service import extract_pdf_text


def test_pdf_text_extractor_reads_page_text(monkeypatch):
    class Page:
        @staticmethod
        def extract_text():
            return "Page one"

    class Reader:
        def __init__(self):
            self.pages = [Page()]

    monkeypatch.setattr("pypdf.PdfReader", lambda stream, strict=False: Reader())

    assert extract_pdf_text(b"%PDF-1.7\nbody") == "Page one"


@pytest.mark.parametrize("content", [b"plain text", b"%PDF-1.7\n"])
def test_pdf_text_extractor_rejects_invalid_or_empty_documents(content):
    with pytest.raises(ValueError):
        extract_pdf_text(content)
