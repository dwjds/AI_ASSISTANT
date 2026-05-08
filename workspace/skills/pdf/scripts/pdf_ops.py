from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter


def main() -> int:
    parser = argparse.ArgumentParser(description="Common PDF operations using pypdf.")
    parser.add_argument(
        "--operation",
        required=True,
        choices=[
            "inspect",
            "merge",
            "extract-pages",
            "split",
            "rotate",
            "crop",
            "encrypt",
            "decrypt",
        ],
    )
    parser.add_argument("--input", help="Input PDF path")
    parser.add_argument("--inputs", nargs="*", help="Input PDF paths for merge")
    parser.add_argument("--output", help="Output PDF path")
    parser.add_argument("--output-dir", help="Output directory for split")
    parser.add_argument("--pages", help="Page selection such as 1,3,5-7,all")
    parser.add_argument("--angle", type=int, default=90, help="Rotation angle")
    parser.add_argument("--crop", help="Crop box: left,bottom,right,top in points")
    parser.add_argument("--password", help="Password for decrypt or user password for encrypt")
    parser.add_argument("--owner-password", help="Owner password for encrypt")
    args = parser.parse_args()

    try:
        payload = run(args)
    except Exception as exc:
        payload = {"status": "error", "operation": args.operation, "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "success" else 1


def run(args: argparse.Namespace) -> dict[str, Any]:
    operation = args.operation
    if operation == "inspect":
        return inspect_pdf(required_pdf(args.input))
    if operation == "merge":
        return merge_pdfs(args.inputs or [], required_output(args.output))
    if operation == "extract-pages":
        return extract_pages(required_pdf(args.input), required_output(args.output), args.pages)
    if operation == "split":
        return split_pdf(required_pdf(args.input), required_dir(args.output_dir), args.pages)
    if operation == "rotate":
        return rotate_pdf(required_pdf(args.input), required_output(args.output), args.pages, args.angle)
    if operation == "crop":
        return crop_pdf(required_pdf(args.input), required_output(args.output), args.pages, args.crop)
    if operation == "encrypt":
        return encrypt_pdf(required_pdf(args.input), required_output(args.output), args.password, args.owner_password)
    if operation == "decrypt":
        return decrypt_pdf(required_pdf(args.input), required_output(args.output), args.password)
    raise ValueError(f"Unsupported operation: {operation}")


def inspect_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path))
    metadata = reader.metadata or {}
    return {
        "status": "success",
        "operation": "inspect",
        "input": str(path),
        "page_count": len(reader.pages),
        "encrypted": bool(reader.is_encrypted),
        "metadata": {str(key).lstrip("/"): str(value) for key, value in metadata.items()},
    }


def merge_pdfs(inputs: list[str], output: Path) -> dict[str, Any]:
    if not inputs:
        raise ValueError("--inputs is required for merge.")
    writer = PdfWriter()
    details = []
    for item in inputs:
        path = required_pdf(item)
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
        details.append({"input": str(path), "pages": len(reader.pages)})
    write_pdf(writer, output)
    return {"status": "success", "operation": "merge", "output": str(output), "inputs": details}


def extract_pages(input_path: Path, output: Path, pages_spec: str | None) -> dict[str, Any]:
    reader = PdfReader(str(input_path))
    selected = normalize_pages(parse_pages(pages_spec), len(reader.pages))
    writer = PdfWriter()
    for page_number in selected:
        writer.add_page(reader.pages[page_number - 1])
    write_pdf(writer, output)
    return {
        "status": "success",
        "operation": "extract-pages",
        "input": str(input_path),
        "output": str(output),
        "pages": selected,
    }


def split_pdf(input_path: Path, output_dir: Path, pages_spec: str | None) -> dict[str, Any]:
    reader = PdfReader(str(input_path))
    selected = normalize_pages(parse_pages(pages_spec), len(reader.pages))
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    stem = input_path.stem
    for page_number in selected:
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number - 1])
        target = output_dir / f"{stem}_page_{page_number}.pdf"
        write_pdf(writer, target)
        outputs.append(str(target))
    return {
        "status": "success",
        "operation": "split",
        "input": str(input_path),
        "output_dir": str(output_dir),
        "pages": selected,
        "outputs": outputs,
    }


def rotate_pdf(input_path: Path, output: Path, pages_spec: str | None, angle: int) -> dict[str, Any]:
    reader = PdfReader(str(input_path))
    selected = set(normalize_pages(parse_pages(pages_spec), len(reader.pages)))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages, start=1):
        if index in selected:
            page.rotate(angle)
        writer.add_page(page)
    write_pdf(writer, output)
    return {
        "status": "success",
        "operation": "rotate",
        "input": str(input_path),
        "output": str(output),
        "pages": sorted(selected),
        "angle": angle,
    }


def crop_pdf(input_path: Path, output: Path, pages_spec: str | None, crop_box: str | None) -> dict[str, Any]:
    if not crop_box:
        raise ValueError("--crop is required as left,bottom,right,top.")
    left, bottom, right, top = parse_crop(crop_box)
    reader = PdfReader(str(input_path))
    selected = set(normalize_pages(parse_pages(pages_spec), len(reader.pages)))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages, start=1):
        if index in selected:
            page.mediabox.left = left
            page.mediabox.bottom = bottom
            page.mediabox.right = right
            page.mediabox.top = top
        writer.add_page(page)
    write_pdf(writer, output)
    return {
        "status": "success",
        "operation": "crop",
        "input": str(input_path),
        "output": str(output),
        "pages": sorted(selected),
        "crop": [left, bottom, right, top],
    }


def encrypt_pdf(input_path: Path, output: Path, password: str | None, owner_password: str | None) -> dict[str, Any]:
    if not password:
        raise ValueError("--password is required for encrypt.")
    reader = PdfReader(str(input_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password, owner_password or password)
    write_pdf(writer, output)
    return {"status": "success", "operation": "encrypt", "input": str(input_path), "output": str(output)}


def decrypt_pdf(input_path: Path, output: Path, password: str | None) -> dict[str, Any]:
    reader = PdfReader(str(input_path))
    if reader.is_encrypted:
        if not password:
            raise ValueError("--password is required for encrypted PDFs.")
        result = reader.decrypt(password)
        if result == 0:
            raise ValueError("Failed to decrypt PDF with provided password.")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    write_pdf(writer, output)
    return {"status": "success", "operation": "decrypt", "input": str(input_path), "output": str(output)}


def required_pdf(value: str | None) -> Path:
    if not value:
        raise ValueError("--input is required.")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Not a PDF file: {path}")
    return path


def required_output(value: str | None) -> Path:
    if not value:
        raise ValueError("--output is required.")
    path = Path(value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def required_dir(value: str | None) -> Path:
    if not value:
        raise ValueError("--output-dir is required.")
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_pdf(writer: PdfWriter, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as handle:
        writer.write(handle)


def parse_pages(value: str | None) -> set[int] | None:
    if not value or value.strip().lower() == "all":
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


def parse_crop(value: str) -> tuple[float, float, float, float]:
    parts = [float(item.strip()) for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--crop must contain four numbers: left,bottom,right,top.")
    return parts[0], parts[1], parts[2], parts[3]


if __name__ == "__main__":
    raise SystemExit(main())
