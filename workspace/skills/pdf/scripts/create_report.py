from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a simple PDF report with text and optional table data.")
    parser.add_argument("output", help="Output PDF path")
    parser.add_argument("--title", default="Report")
    parser.add_argument("--content", default="", help="Plain text report body")
    parser.add_argument("--content-file", help="Optional UTF-8 text/markdown input file")
    parser.add_argument("--table-json", help="Optional JSON file containing rows or {headers, rows}")
    args = parser.parse_args()

    try:
        payload = create_report(
            Path(args.output),
            title=args.title,
            content=args.content,
            content_file=Path(args.content_file) if args.content_file else None,
            table_json=Path(args.table_json) if args.table_json else None,
        )
    except Exception as exc:
        payload = {"status": "error", "error": str(exc), "output": args.output}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "success" else 1


def create_report(
    output_path: Path,
    *,
    title: str,
    content: str,
    content_file: Path | None,
    table_json: Path | None,
) -> dict[str, Any]:
    target = output_path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if content_file is not None:
        content = content_file.expanduser().resolve().read_text(encoding="utf-8")
    rows = load_table_rows(table_json) if table_json is not None else []

    styles = getSampleStyleSheet()
    story = [Paragraph(escape_text(title), styles["Title"]), Spacer(1, 12)]
    for paragraph in split_paragraphs(content):
        story.append(Paragraph(escape_text(paragraph), styles["BodyText"]))
        story.append(Spacer(1, 8))
    if rows:
        table = Table(rows, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(Spacer(1, 12))
        story.append(table)

    doc = SimpleDocTemplate(str(target), pagesize=A4)
    doc.build(story)
    return {
        "status": "success",
        "operation": "create-report",
        "output": str(target),
        "paragraph_count": len(split_paragraphs(content)),
        "table_rows": len(rows),
    }


def load_table_rows(path: Path) -> list[list[str]]:
    data = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if isinstance(data, dict):
        headers = data.get("headers") or []
        rows = data.get("rows") or []
        result = [[str(item) for item in headers]] if headers else []
        for row in rows:
            if isinstance(row, dict):
                result.append([str(row.get(header, "")) for header in headers])
            else:
                result.append([str(item) for item in row])
        return result
    if isinstance(data, list):
        return [[str(item) for item in row] for row in data]
    return []


def split_paragraphs(content: str) -> list[str]:
    return [part.strip() for part in str(content or "").splitlines() if part.strip()]


def escape_text(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


if __name__ == "__main__":
    raise SystemExit(main())
