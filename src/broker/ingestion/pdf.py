import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from broker.logging import log

# Section headers we try to locate. Order roughly matches paper structure;
# the parser scans forward and splits at the first matching header per section.
SECTION_PATTERNS = {
    "abstract": re.compile(r"^\s*(abstract)\s*$", re.IGNORECASE | re.MULTILINE),
    "introduction": re.compile(r"^\s*\d*\.?\s*(introduction)\s*$", re.IGNORECASE | re.MULTILINE),
    "related_work": re.compile(r"^\s*\d*\.?\s*(related\s+work|background)\s*$", re.IGNORECASE | re.MULTILINE),
    "method": re.compile(r"^\s*\d*\.?\s*(method|methodology|approach|model)\s*$", re.IGNORECASE | re.MULTILINE),
    "experiments": re.compile(r"^\s*\d*\.?\s*(experiments|evaluation|results)\s*$", re.IGNORECASE | re.MULTILINE),
    "conclusion": re.compile(r"^\s*\d*\.?\s*(conclusion|discussion)\s*$", re.IGNORECASE | re.MULTILINE),
    "references": re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE),
}


@dataclass
class ParsedPaper:
    full_text: str
    sections: dict[str, str] = field(default_factory=dict)
    page_count: int = 0

    def section(self, name: str, fallback_chars: int = 2000) -> str:
        """Return a named section or the first N chars of full_text as fallback."""
        return self.sections.get(name) or self.full_text[:fallback_chars]


def _extract_text(pdf_path: Path) -> tuple[str, int]:
    with pdfplumber.open(pdf_path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages), len(pdf.pages)


def _split_sections(text: str) -> dict[str, str]:
    """Best-effort section split. We find header offsets, sort by position, slice between them."""
    offsets: list[tuple[int, str]] = []
    for name, pattern in SECTION_PATTERNS.items():
        m = pattern.search(text)
        if m:
            offsets.append((m.start(), name))

    if not offsets:
        return {}

    offsets.sort()
    sections: dict[str, str] = {}
    for i, (start, name) in enumerate(offsets):
        end = offsets[i + 1][0] if i + 1 < len(offsets) else len(text)
        sections[name] = text[start:end].strip()
    return sections


def parse_pdf(pdf_path: str | Path) -> ParsedPaper:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(path)

    try:
        full_text, page_count = _extract_text(path)
    except Exception as e:
        log.warning("pdf_parse_failed", path=str(path), error=str(e))
        return ParsedPaper(full_text="", sections={}, page_count=0)

    sections = _split_sections(full_text)
    return ParsedPaper(full_text=full_text, sections=sections, page_count=page_count)
