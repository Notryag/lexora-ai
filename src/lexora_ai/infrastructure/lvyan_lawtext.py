from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from lexora_ai.domain import (
    LegalSourceCreate,
    LegalSourceKind,
    LegalSourceReviewStatus,
    LegalSourceStatus,
)

_FRONT_MATTER_END = "\n---\n"
_ARTICLE_LINE_RE = re.compile(
    r"^-\s*\*\*(第[0-9零〇一二三四五六七八九十百千万亿两]+条"
    r"(?:之[0-9零〇一二三四五六七八九十百千万亿两]+)?)\*\*[\s\u3000]*(.*)$"
)


class LvyanLawTextError(RuntimeError):
    pass


class _LawMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    link_title: str | None = Field(default=None, alias="LinkTitle")
    author: str = Field(min_length=1)
    publication_date: date | None = None
    effective_date: date | None = None
    status: str = Field(min_length=1)
    group: str = Field(min_length=1)
    urls: list[str] = Field(default_factory=list)

    @field_validator("publication_date", "effective_date", mode="before")
    @classmethod
    def empty_date_is_unknown(cls, value):
        return None if value == "" else value


class _LawDocument(BaseModel):
    metadata: _LawMetadata
    content: str
    path: Path


_KIND_BY_GROUP = {
    "法律": LegalSourceKind.law,
    "行政法规": LegalSourceKind.administrative_regulation,
    "司法解释": LegalSourceKind.judicial_interpretation,
    "地方性法规": LegalSourceKind.local_regulation,
}
_STATUS_BY_LABEL = {
    "有效": LegalSourceStatus.effective,
    "已修改": LegalSourceStatus.amended,
    "已废止": LegalSourceStatus.repealed,
    "未生效": LegalSourceStatus.not_effective,
    "尚未生效": LegalSourceStatus.not_effective,
}


class LvyanLawTextConnector:
    def __init__(self, repository_path: Path) -> None:
        self._repository_path = repository_path.expanduser().resolve()
        self._content_path = self._repository_path / "content"
        self._documents: list[_LawDocument] | None = None

    def current_titles(self) -> list[str]:
        documents = self._load_documents()
        return sorted(
            {
                document.metadata.title
                for document in documents
                if document.metadata.status == "有效"
            }
        )

    async def fetch(self, title: str) -> LegalSourceCreate:
        candidates = [
            document
            for document in self._load_documents()
            if document.metadata.title == title and document.metadata.status == "有效"
        ]
        if not candidates:
            raise LvyanLawTextError(f"no effective lvyan-lawtext version found for {title!r}")
        candidates.sort(
            key=lambda document: document.metadata.publication_date or date.min,
            reverse=True,
        )
        selected = candidates[0]
        if (
            len(candidates) > 1
            and candidates[1].metadata.publication_date
            == selected.metadata.publication_date
        ):
            raise LvyanLawTextError(f"multiple current lvyan-lawtext versions found for {title!r}")

        metadata = selected.metadata
        source_url = next(
            (url for url in metadata.urls if url.startswith("https://flk.npc.gov.cn/")),
            f"https://flk.npc.gov.cn/detail?id={metadata.id}",
        )
        try:
            status = _STATUS_BY_LABEL[metadata.status]
        except KeyError as exc:
            raise LvyanLawTextError(f"unknown lvyan-lawtext status: {metadata.status}") from exc

        return LegalSourceCreate(
            title=metadata.title,
            kind=_KIND_BY_GROUP.get(metadata.group, LegalSourceKind.other),
            issuing_authority=metadata.author,
            status=status,
            published_on=metadata.publication_date,
            effective_on=metadata.effective_date,
            source_name="lvyan-lawtext 国家法律法规数据库快照",
            source_url=source_url,
            version_label=metadata.link_title,
            content=self._normalize_markdown(selected.content),
            review_status=LegalSourceReviewStatus.pending,
            verified_at=None,
        )

    def _load_documents(self) -> list[_LawDocument]:
        if self._documents is not None:
            return self._documents
        if not self._content_path.is_dir():
            raise LvyanLawTextError(
                f"lvyan-lawtext content directory not found: {self._content_path}"
            )
        documents: list[_LawDocument] = []
        for path in sorted(self._content_path.rglob("*.md")):
            if path.name.startswith("_"):
                continue
            documents.append(self._parse_document(path))
        self._documents = documents
        return documents

    @staticmethod
    def _parse_document(path: Path) -> _LawDocument:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n") or _FRONT_MATTER_END not in raw[4:]:
            raise LvyanLawTextError(f"invalid front matter: {path}")
        metadata_text, content = raw[4:].split(_FRONT_MATTER_END, maxsplit=1)
        try:
            metadata = _LawMetadata.model_validate(yaml.safe_load(metadata_text))
        except (yaml.YAMLError, ValidationError) as exc:
            raise LvyanLawTextError(f"invalid metadata: {path}") from exc
        if not content.strip():
            raise LvyanLawTextError(f"empty legal source content: {path}")
        return _LawDocument(metadata=metadata, content=content, path=path)

    @staticmethod
    def _normalize_markdown(content: str) -> str:
        lines: list[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line == "---":
                continue
            article = _ARTICLE_LINE_RE.match(line)
            if article:
                lines.append(f"{article.group(1)} {article.group(2).strip()}".rstrip())
                continue
            if line.startswith("#"):
                line = line.lstrip("#").strip()
            if line.startswith(">"):
                line = line.removeprefix(">").strip()
            lines.append(line.replace("**", ""))
        normalized = "\n".join(lines).strip()
        if not normalized:
            raise LvyanLawTextError("normalized legal source content is empty")
        return normalized
