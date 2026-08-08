from __future__ import annotations

import asyncio
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lexora_ai.domain import CaseLawSourceCreate, CaseLawStatus, LegalSourceReviewStatus

_CASE_NUMBER_RE = re.compile(r"指导性?案例\d+号")
_PUBLISHED_RE = re.compile(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})")
_SECTION_LABELS = ("裁判要点", "相关法条", "基本案情", "裁判结果", "裁判理由")


class SpcGuidingCaseError(ValueError):
    pass


class _GuidingCaseHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._div_depth = 0
        self._detail_depth: int | None = None
        self._title_depth: int | None = None
        self._meta_depth: int | None = None
        self._content_depth: int | None = None
        self._paragraph: list[str] | None = None
        self.title_parts: list[str] = []
        self.meta_parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div":
            self._div_depth += 1
            classes = set(dict(attrs).get("class", "").split())
            if "detail" in classes and self._detail_depth is None:
                self._detail_depth = self._div_depth
            elif self._detail_depth is not None and "title" in classes:
                self._title_depth = self._div_depth
            elif self._detail_depth is not None and "detail_mes" in classes:
                self._meta_depth = self._div_depth
            elif self._detail_depth is not None and "txt_txt" in classes:
                self._content_depth = self._div_depth
        elif tag == "p" and self._content_depth is not None:
            self._flush_paragraph()
            self._paragraph = []
        elif tag == "br" and self._content_depth is not None:
            self._flush_paragraph()

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._content_depth is not None:
            self._flush_paragraph()
        if tag != "div":
            return
        if self._div_depth == self._title_depth:
            self._title_depth = None
        if self._div_depth == self._meta_depth:
            self._meta_depth = None
        if self._div_depth == self._content_depth:
            self._flush_paragraph()
            self._content_depth = None
        if self._div_depth == self._detail_depth:
            self._detail_depth = None
        self._div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_depth is not None:
            self.title_parts.append(data)
        if self._meta_depth is not None:
            self.meta_parts.append(data)
        if self._content_depth is not None:
            if self._paragraph is None:
                self._paragraph = []
            self._paragraph.append(data)

    def close(self) -> None:
        super().close()
        self._flush_paragraph()

    def _flush_paragraph(self) -> None:
        if self._paragraph is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._paragraph)).strip()
        if text:
            self.paragraphs.append(text)
        self._paragraph = None


class SpcGuidingCaseConnector:
    async def fetch(self, source_url: str) -> CaseLawSourceCreate:
        self._validate_url(source_url)
        html = await asyncio.to_thread(self._download, source_url)
        return self.parse(source_url, html)

    def parse(self, source_url: str, html: str) -> CaseLawSourceCreate:
        self._validate_url(source_url)
        parser = _GuidingCaseHtmlParser()
        parser.feed(html)
        parser.close()
        page_title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
        if not page_title or not parser.paragraphs:
            raise SpcGuidingCaseError("official guiding-case page has no readable case content")

        case_number_match = _CASE_NUMBER_RE.search(page_title)
        if case_number_match is None:
            case_number_match = next(
                (_CASE_NUMBER_RE.search(item) for item in parser.paragraphs if _CASE_NUMBER_RE.search(item)),
                None,
            )
        if case_number_match is None:
            raise SpcGuidingCaseError("official guiding-case number was not found")
        case_number = case_number_match.group(0)
        title = re.sub(rf"^{re.escape(case_number)}\s*[：:]?\s*", "", page_title).strip()
        if not title:
            raise SpcGuidingCaseError("official guiding-case title was not found")

        meta = re.sub(r"\s+", " ", "".join(parser.meta_parts))
        published_match = _PUBLISHED_RE.search(meta)
        published_on = date.fromisoformat(published_match.group(1)) if published_match else None
        content, keywords = self._normalize_content(parser.paragraphs)
        return CaseLawSourceCreate(
            case_number=case_number,
            title=title,
            keywords=keywords,
            issuing_authority="最高人民法院",
            status=CaseLawStatus.active,
            published_on=published_on,
            source_name="最高人民法院指导性案例",
            source_url=source_url,
            content=content,
            review_status=LegalSourceReviewStatus.pending,
        )

    @staticmethod
    def _normalize_content(paragraphs: list[str]) -> tuple[str, list[str]]:
        lines: list[str] = ["案例信息"]
        keywords: list[str] = []
        pending_keywords = False
        for paragraph in paragraphs:
            text = paragraph.strip()
            if "关键词" in text:
                payload = text.split("关键词", maxsplit=1)[1].strip(" ：:")
                if payload:
                    keywords = [item for item in re.split(r"[\s　/／]+", payload) if item]
                lines.append("关键词")
                if keywords:
                    lines.append(" ".join(keywords))
                pending_keywords = not bool(payload)
                continue
            if pending_keywords:
                keywords = [item for item in re.split(r"[\s　/／]+", text) if item]
                lines.append(" ".join(keywords))
                pending_keywords = False
                continue
            section = next((label for label in _SECTION_LABELS if text.startswith(label)), None)
            if section is not None:
                lines.append(section)
                remainder = text.removeprefix(section).strip(" ：:")
                if remainder:
                    lines.append(remainder)
                continue
            lines.append(text)
        content = "\n".join(lines).strip()
        if "裁判要点" not in lines or "基本案情" not in lines:
            raise SpcGuidingCaseError("official guiding-case sections are incomplete")
        return content, keywords

    @classmethod
    def _download(cls, source_url: str) -> str:
        request = Request(
            source_url,
            headers={"User-Agent": "Lexora/0.1 official-source-sync"},
        )
        with urlopen(request, timeout=20) as response:
            final_url = response.geturl()
            cls._validate_url(final_url)
            return response.read().decode("utf-8")

    @staticmethod
    def _validate_url(source_url: str) -> None:
        parsed = urlparse(source_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname == "court.gov.cn" or hostname.endswith(".court.gov.cn")
        ):
            raise SpcGuidingCaseError("only official HTTPS *.court.gov.cn pages are allowed")
