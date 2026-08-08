from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

import docx2txt
from pypdf import PdfReader

from lexora_ai.application.errors import MaterialParseError
from lexora_ai.domain.cases import MAX_MATERIAL_CHARS

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = frozenset({".docx", ".md", ".pdf", ".txt"})


def parse_material_file(filename: str, content: bytes) -> str:
    if not content:
        raise MaterialParseError("uploaded material is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise MaterialParseError("uploaded material must not exceed 10 MB")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise MaterialParseError("supported material formats are PDF, DOCX, TXT, and Markdown")

    try:
        if extension in {".txt", ".md"}:
            text = content.decode("utf-8-sig")
        elif extension == ".pdf":
            reader = PdfReader(BytesIO(content))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            with NamedTemporaryFile(suffix=".docx") as temporary:
                temporary.write(content)
                temporary.flush()
                text = docx2txt.process(temporary.name)
    except (OSError, UnicodeError, ValueError) as exc:
        raise MaterialParseError("failed to parse uploaded material") from exc

    normalized = text.strip()
    if not normalized:
        raise MaterialParseError("uploaded material contains no extractable text")
    if len(normalized) > MAX_MATERIAL_CHARS:
        raise MaterialParseError(
            f"extracted material must not exceed {MAX_MATERIAL_CHARS} characters"
        )
    return normalized
