from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pdfplumber
from openpyxl import Workbook


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract tables from a PDF using pdfplumber.")
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("--output-json", help="Optional JSON output path")
    parser.add_argument("--output-xlsx", help="Optional XLSX output path")
    parser.add_argument("--pages", help="Page selection such as 1,3,5-7")
    parser.add_argument("--strategy", choices=["lines", "text"], default="lines")
    parser.add_argument("--max-preview-rows", type=int, default=10)
    args = parser.parse_args()

    try:
        payload = extract_tables(
            Path(args.input),
            output_json=Path(args.output_json) if args.output_json else None,
            output_xlsx=Path(args.output_xlsx) if args.output_xlsx else None,
            pages=parse_pages(args.pages),
            strategy=args.strategy,
            max_preview_rows=max(1, args.max_preview_rows),
        )
    except Exception as exc:
        payload = {"status": "error", "error": str(exc), "input": args.input}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "success" else 1


def extract_tables(
    input_path: Path,
    *,
    output_json: Path | None,
    output_xlsx: Path | None,
    pages: set[int] | None,
    strategy: str,
    max_preview_rows: int,
) -> dict[str, Any]:
    source = input_path.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError(f"Input is not a PDF: {source}")

    settings = {
        "vertical_strategy": strategy,
        "horizontal_strategy": strategy,
        "snap_tolerance": 3,
        "intersection_tolerance": 15,
    }
    results: list[dict[str, Any]] = []
    with pdfplumber.open(str(source)) as pdf:
        selected = normalize_pages(pages, len(pdf.pages))
        for page_number in selected:
            page = pdf.pages[page_number - 1]
            for table_index, table in enumerate(page.extract_tables(settings), start=1):
                normalized = normalize_table(table)
                if not normalized:
                    continue
                results.append(
                    {
                        "page": page_number,
                        "table_index": table_index,
                        "row_count": len(normalized),
                        "column_count": max(len(row) for row in normalized),
                        "preview": normalized[:max_preview_rows],
                        "rows": normalized,
                    }
                )

    output_json_path = None
    if output_json is not None:
        target = output_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        output_json_path = str(target)

    output_xlsx_path = None
    if output_xlsx is not None:
        target = output_xlsx.expanduser().resolve()
        write_tables_xlsx(results, target)
        output_xlsx_path = str(target)

    return {
        "status": "success",
        "input": str(source),
        "table_count": len(results),
        "output_json": output_json_path,
        "output_xlsx": output_xlsx_path,
        "tables_preview": [
            {
                "page": item["page"],
                "table_index": item["table_index"],
                "row_count": item["row_count"],
                "column_count": item["column_count"],
                "preview": item["preview"],
            }
            for item in results
        ],
    }


def normalize_table(table: list[list[Any]] | None) -> list[list[str]]:
    if not table:
        return []
    rows: list[list[str]] = []
    for row in table:
        values = ["" if item is None else str(item).strip() for item in row]
        if any(values):
            rows.append(values)
    return rows


def write_tables_xlsx(tables: list[dict[str, Any]], target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    if tables:
        workbook.remove(workbook.active)
    for item in tables:
        sheet_name = f"P{item['page']}_T{item['table_index']}"[:31]
        sheet = workbook.create_sheet(sheet_name)
        for row in item["rows"]:
            sheet.append(row)
    if not tables:
        workbook.active.title = "NoTables"
    workbook.save(str(target))


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
