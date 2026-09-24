"""Small permissive-license PDF adapter used by the standalone package."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path


class PdfBackendUnavailable(ImportError):
    """Raised when optional PDF rendering dependencies are not installed."""


def _pdfium():
    try:
        import pypdfium2
    except ImportError as exc:  # pragma: no cover - depends on optional extras
        raise PdfBackendUnavailable(
            "PDF 处理需要 pypdfium2 和 Pillow；请安装 requirements-import.txt"
        ) from exc
    return pypdfium2


class PdfDocument:
    """Context-managed page count, text extraction and PNG rendering."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._document = _pdfium().PdfDocument(str(self.path))

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        document = self._document
        if document is not None:
            document.close()
            self._document = None

    def __len__(self) -> int:
        if self._document is None:
            raise RuntimeError("PDF 文档已关闭")
        return len(self._document)

    def read_page(self, index: int, *, dpi: int) -> tuple[bytes, str]:
        """Return a zero-based physical page as PNG bytes and native text."""
        if self._document is None:
            raise RuntimeError("PDF 文档已关闭")
        page = self._document[index]
        text_page = bitmap = image = None
        try:
            text_page = page.get_textpage()
            native_text = text_page.get_text_range() or ""
            bitmap = page.render(scale=dpi / 72)
            image = bitmap.to_pil()
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue(), native_text
        finally:
            if image is not None:
                image.close()
            if bitmap is not None:
                bitmap.close()
            if text_page is not None:
                text_page.close()
            page.close()

    def render_page(self, index: int, *, dpi: int) -> bytes:
        png, _ = self.read_page(index, dpi=dpi)
        return png


def physical_page_count(path: Path | str) -> int:
    with PdfDocument(path) as document:
        return len(document)
