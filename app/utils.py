import os
import time
import logging

from pypdf import PdfReader
from docx import Document

from app.core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("faq")


def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    text = ""
    try:
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception as e:
        logger.error(e)
    finally:
       reader.close()
    return text

def extract_text_from_docx(docx_path: str) -> str:
    """Извлекает текст из .docx файла."""
    try:
        doc = Document(docx_path)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        logger.error(f"Ошибка при чтении docx {docx_path}: {e}")
        return ""

def extract_text_from_path(path: str) -> str:
    """Извлекает текст из файла по расширению: pdf/txt/md/docx."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    elif ext == ".docx":
        return extract_text_from_docx(path)
    elif ext in {".txt", ".md"}:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="cp1251", errors="ignore") as f:
                return f.read()
    else:
        raise ValueError(f"Неподдерживаемый формат файла: {ext}")

class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        self.end = None
        return self

    def __exit__(self, *args):
        self.end = time.perf_counter()

    @property
    def elapsed(self) -> float:
        """Elapsed milliseconds since context start.

        Works both inside the context (live duration) and after it ends
        (fixed duration).
        """
        end = self.end if self.end is not None else time.perf_counter()
        return (end - self.start) * 1000