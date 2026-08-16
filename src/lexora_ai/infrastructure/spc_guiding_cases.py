from __future__ import annotations

import asyncio
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from lexora_ai.application.case_law_sync import CaseLawSourceLocator
from lexora_ai.domain import CaseLawSourceCreate, CaseLawStatus, LegalSourceReviewStatus

_CASE_NUMBER_RE = re.compile(r"指导性?案例\d+号")
_REFERENCE_CASE_NUMBER_RE = re.compile(r"入库编号\s*[-：:]?\s*(\d{4}(?:-\d+){4})")
_PUBLISHED_RE = re.compile(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})")
_TYPICAL_CASE_HEADING_RE = re.compile(r"^案例([一二三四五六七八九十]+)\s*[：:]\s*(.+)$")
_TYPICAL_SECTION_RE = re.compile(r"^[〖【\[]\s*(基本案情|裁判结果|典型意义)\s*[〗】\]]$")
_CHINESE_ORDINALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_SECTION_LABELS = (
    "裁判要点",
    "裁判要旨",
    "相关法条",
    "基本案情",
    "裁判结果",
    "裁判理由",
    "典型意义",
    "关联索引",
)


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
    async def fetch(self, locator: CaseLawSourceLocator) -> list[CaseLawSourceCreate]:
        self._validate_url(locator.source_url)
        html = await asyncio.to_thread(self._download, locator.source_url)
        return self.parse_many(locator, html)

    def parse(self, source_url: str, html: str) -> CaseLawSourceCreate:
        documents = self.parse_many(CaseLawSourceLocator(source_url=source_url), html)
        if len(documents) != 1:
            raise SpcGuidingCaseError("expected one official case")
        return documents[0]

    def parse_many(
        self,
        locator: CaseLawSourceLocator,
        html: str,
    ) -> list[CaseLawSourceCreate]:
        source_url = locator.source_url
        self._validate_url(source_url)
        parser = _GuidingCaseHtmlParser()
        parser.feed(html)
        parser.close()
        page_title = re.sub(r"\s+", " ", "".join(parser.title_parts)).strip()
        if not page_title or not parser.paragraphs:
            raise SpcGuidingCaseError("official guiding-case page has no readable case content")

        if locator.case_ordinals:
            return self._parse_typical_cases(
                source_url=source_url,
                meta_parts=parser.meta_parts,
                paragraphs=parser.paragraphs,
                selected_ordinals=locator.case_ordinals,
            )

        page_and_content = "\n".join((page_title, *parser.paragraphs))
        guiding_case_match = _CASE_NUMBER_RE.search(page_and_content)
        reference_case_match = _REFERENCE_CASE_NUMBER_RE.search(page_and_content)
        if guiding_case_match is not None:
            case_number = guiding_case_match.group(0)
            title = re.sub(
                rf"^{re.escape(case_number)}\s*[：:]?\s*", "", page_title
            ).strip()
            source_name = "最高人民法院指导性案例"
        elif reference_case_match is not None:
            case_number = f"入库编号 {reference_case_match.group(1)}"
            title = re.sub(
                r"^入库参考案例(?:选介)?\s*[：:]?\s*", "", page_title
            ).strip()
            source_name = "人民法院案例库入库参考案例"
        else:
            raise SpcGuidingCaseError("official case number was not found")
        if not title:
            raise SpcGuidingCaseError("official case title was not found")

        meta = re.sub(r"\s+", " ", "".join(parser.meta_parts))
        published_match = _PUBLISHED_RE.search(meta)
        published_on = date.fromisoformat(published_match.group(1)) if published_match else None
        content, keywords = self._normalize_content(parser.paragraphs)
        return [
            CaseLawSourceCreate(
                case_number=case_number,
                title=title,
                keywords=keywords,
                issuing_authority="最高人民法院",
                status=CaseLawStatus.active,
                published_on=published_on,
                source_name=source_name,
                source_url=source_url,
                content=content,
                review_status=LegalSourceReviewStatus.pending,
            )
        ]

    def _parse_typical_cases(
        self,
        *,
        source_url: str,
        meta_parts: list[str],
        paragraphs: list[str],
        selected_ordinals: tuple[int, ...],
    ) -> list[CaseLawSourceCreate]:
        meta = re.sub(r"\s+", " ", "".join(meta_parts))
        published_match = _PUBLISHED_RE.search(meta)
        if published_match is None:
            raise SpcGuidingCaseError("typical-case publication date was not found")
        published_on = date.fromisoformat(published_match.group(1))
        cases = self._split_typical_cases(paragraphs)
        missing = [ordinal for ordinal in selected_ordinals if ordinal not in cases]
        if missing:
            rendered = ", ".join(str(ordinal) for ordinal in missing)
            raise SpcGuidingCaseError(f"selected typical cases were not found: {rendered}")

        results: list[CaseLawSourceCreate] = []
        for ordinal in selected_ordinals:
            heading, body = cases[ordinal]
            ordinal_label = next(
                label for label, value in _CHINESE_ORDINALS.items() if value == ordinal
            )
            title = self._typical_case_title(heading)
            content = self._normalize_typical_case(title, body)
            results.append(
                CaseLawSourceCreate(
                    case_number=(
                        f"最高法典型案例 {published_on.isoformat()} 案例{ordinal_label}"
                    ),
                    title=title,
                    keywords=[],
                    issuing_authority="最高人民法院",
                    status=CaseLawStatus.active,
                    published_on=published_on,
                    source_name="最高人民法院典型案例",
                    source_url=source_url,
                    content=content,
                    review_status=LegalSourceReviewStatus.pending,
                )
            )
        return results

    @staticmethod
    def _split_typical_cases(
        paragraphs: list[str],
    ) -> dict[int, tuple[str, list[str]]]:
        result: dict[int, tuple[str, list[str]]] = {}
        for index, paragraph in enumerate(paragraphs):
            match = _TYPICAL_CASE_HEADING_RE.match(paragraph.strip())
            if match is None or index + 1 >= len(paragraphs):
                continue
            if _TYPICAL_SECTION_RE.match(paragraphs[index + 1].strip()) is None:
                continue
            ordinal = _CHINESE_ORDINALS.get(match.group(1))
            if ordinal is None:
                continue
            body: list[str] = []
            for following in paragraphs[index + 1 :]:
                following = following.strip()
                if _TYPICAL_CASE_HEADING_RE.match(following) or following.startswith(
                    "责任编辑"
                ):
                    break
                body.append(following)
            result[ordinal] = (match.group(2).strip(), body)
        return result

    @staticmethod
    def _typical_case_title(heading: str) -> str:
        candidates = [part.strip() for part in heading.split("——") if part.strip()]
        case_titles = [candidate for candidate in candidates if candidate.endswith("案")]
        return case_titles[-1] if case_titles else heading.strip()

    @staticmethod
    def _normalize_typical_case(title: str, paragraphs: list[str]) -> str:
        lines = ["案例信息", title]
        sections: set[str] = set()
        for paragraph in paragraphs:
            text = paragraph.strip()
            section_match = _TYPICAL_SECTION_RE.match(text)
            if section_match is not None:
                section = section_match.group(1)
                sections.add(section)
                lines.append(section)
            else:
                lines.append(text)
        required = {"基本案情", "裁判结果", "典型意义"}
        if not required.issubset(sections):
            raise SpcGuidingCaseError("official typical-case sections are incomplete")
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_content(paragraphs: list[str]) -> tuple[str, list[str]]:
        lines: list[str] = ["案例信息"]
        keywords: list[str] = []
        pending_keywords = False
        for paragraph in paragraphs:
            text = paragraph.strip()
            if text.startswith("关键词"):
                payload = text.removeprefix("关键词").strip(" ：:")
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
        if (
            not ({"裁判要点", "裁判要旨"} & set(lines))
            or "基本案情" not in lines
        ):
            raise SpcGuidingCaseError("official case sections are incomplete")
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
