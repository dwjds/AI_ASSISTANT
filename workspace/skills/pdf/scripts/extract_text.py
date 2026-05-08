from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None  # type: ignore[assignment]

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract text from a PDF with pdfplumber, falling back to pypdf."
    )
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument(
        "--output-text",
        help="Optional .txt/.md output path for extracted text.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Maximum text characters included in stdout JSON.",
    )
    parser.add_argument(
        "--pages",
        help="Optional page selection such as 1,3,5-7. Pages are 1-based.",
    )
    args = parser.parse_args()

    try:
        payload = extract_pdf_text(
            Path(args.input),
            output_text=Path(args.output_text) if args.output_text else None,
            max_chars=max(100, args.max_chars),
            pages=parse_pages(args.pages),
        )
    except Exception as exc:
        payload = {"status": "error", "error": str(exc), "input": args.input}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "success" else 1


def extract_pdf_text(
    input_path: Path,
    *,
    output_text: Path | None,
    max_chars: int,
    pages: set[int] | None,
) -> dict[str, Any]:
    source = input_path.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError(f"Input is not a PDF: {source}")

    if pdfplumber is not None:
        extraction = extract_with_pdfplumber(source, pages=pages)
        engine = "pdfplumber"
    elif PdfReader is not None:
        extraction = extract_with_pypdf(source, pages=pages)
        engine = "pypdf"
    else:
        raise RuntimeError("PDF text extraction requires pdfplumber or pypdf.")

    full_text = "\n\n".join(
        item["text"] for item in extraction["pages"] if item.get("text")
    ).strip()
    output_path = None
    if output_text is not None:
        target = output_text.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(full_text, encoding="utf-8")
        output_path = str(target)

    return {
        "status": "success",
        "engine": engine,
        "input": str(source),
        "output_text": output_path,
        "page_count": extraction["page_count"],
        "selected_pages": extraction["selected_pages"],
        "extracted_pages": len(extraction["pages"]),
        "char_count": len(full_text),
        "text_preview": full_text[:max_chars],
        "truncated": len(full_text) > max_chars,
    }


def extract_with_pdfplumber(source: Path, *, pages: set[int] | None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with pdfplumber.open(str(source)) as pdf:
        page_count = len(pdf.pages)
        selected = normalize_pages(pages, page_count)
        for page_number in selected:
            page = pdf.pages[page_number - 1]
            text = page.extract_text() or ""
            results.append({"page": page_number, "text": text.strip()})
    return {"page_count": page_count, "selected_pages": selected, "pages": results}


def extract_with_pypdf(source: Path, *, pages: set[int] | None) -> dict[str, Any]:
    if PdfReader is None:
        raise RuntimeError("pypdf is unavailable.")
    reader = PdfReader(str(source))
    page_count = len(reader.pages)
    selected = normalize_pages(pages, page_count)
    results = []
    for page_number in selected:
        page = reader.pages[page_number - 1]
        results.append({"page": page_number, "text": (page.extract_text() or "").strip()})
    return {"page_count": page_count, "selected_pages": selected, "pages": results}


def parse_pages(value: str | None) -> set[int] | None:
    if not value:
        return None
    pages: set[int] = set()
    for part in value.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, end_text = chunk.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            pages.add(int(chunk))
    return {page for page in pages if page >= 1}


def normalize_pages(pages: set[int] | None, page_count: int) -> list[int]:
    if pages is None:
        return list(range(1, page_count + 1))
    return sorted(page for page in pages if 1 <= page <= page_count)


if __name__ == "__main__":
    raise SystemExit(main())
