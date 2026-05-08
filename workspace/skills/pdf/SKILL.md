---
name: pdf
description: Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, combining or merging multiple PDFs into one, splitting PDFs apart, rotating pages, adding watermarks, creating new PDFs, filling PDF forms, encrypting/decrypting PDFs, extracting images, and OCR on scanned PDFs to make them searchable. If the user mentions a .pdf file or asks to produce one, use this skill.
triggers:
- .pdf
- pdf
- PDF
- PDF文件
- 读取PDF
- 总结PDF
- 提取PDF
- PDF表格
- 合并PDF
- 拆分PDF
- 旋转PDF
- 加水印
- 生成PDF
- 转PDF
license: Proprietary. LICENSE.txt has complete terms
---

# PDF Processing Guide

## MiniAgent Project Workflow

当前项目优先使用 `pypdf`、`pdfplumber` 和 `reportlab`。`pdf2image`、OCR、Poppler 图片转换暂不作为默认能力使用。

### Supported Now

- 读取和摘要：优先使用 `read_uploaded_file` 获取已解析文本；需要更精确文本抽取时使用 `run_skill_script(skill_name="pdf", script_path="scripts/extract_text.py", arguments=["<input_pdf_path>", "--max-chars", "12000"], timeout_seconds=60)`。
- 提取表格：使用 `run_skill_script(skill_name="pdf", script_path="scripts/extract_tables.py", arguments=["<input_pdf_path>", "--output-xlsx", "<outbox_tables.xlsx>"], timeout_seconds=60)`。
- 基础 PDF 操作：使用 `run_skill_script(skill_name="pdf", script_path="scripts/pdf_ops.py", arguments=["--operation", "<inspect|merge|extract-pages|split|rotate|crop|encrypt|decrypt>", ...], timeout_seconds=60)`。
- 生成 PDF：使用 `run_skill_script(skill_name="pdf", script_path="scripts/create_report.py", arguments=["<output_pdf_path>", "--title", "<title>", "--content", "<content>"], timeout_seconds=60)`，或使用 `save_outbox_file` 生成简单 PDF。
- 表单处理：只有用户明确要求处理 PDF 表单时，先读取 `forms.md`，再按需运行 `scripts/check_fillable_fields.py`、`scripts/extract_form_field_info.py` 等脚本。

### Required Flow

1. 明确任务类型：读取摘要、表格提取、结构修改、表单处理或生成 PDF。
2. 普通摘要不要输出全文；默认给 3-6 条要点、关键结论和风险。
3. 需要生成或修改文件时，输出到 outbox，不覆盖 inbox 原件。
4. 对表格/表单等复杂任务，先用基础文件工具按需读取 `reference.md` 或 `forms.md`。
5. 生成后说明输出文件、处理范围和无法保证的内容。

### Script Workflows

- 文本抽取：`scripts/extract_text.py <input.pdf> --max-chars 12000`
- 表格抽取：`scripts/extract_tables.py <input.pdf> --output-xlsx <tables.xlsx>`
- 基础操作：`scripts/pdf_ops.py --operation inspect --input <input.pdf>`
- 抽取页面：`scripts/pdf_ops.py --operation extract-pages --input <input.pdf> --pages 1-3 --output <output.pdf>`
- 合并 PDF：`scripts/pdf_ops.py --operation merge --inputs <a.pdf> <b.pdf> --output <merged.pdf>`
- 旋转页面：`scripts/pdf_ops.py --operation rotate --input <input.pdf> --pages 1 --angle 90 --output <rotated.pdf>`
- 裁剪页面：`scripts/pdf_ops.py --operation crop --input <input.pdf> --crop 50,50,550,750 --output <cropped.pdf>`
- 生成报告：`scripts/create_report.py <output.pdf> --title "Report" --content "Summary..."`

### Current Limits

- 暂不使用 `pdf2image`。
- 暂不做扫描件 OCR，除非后续安装并配置 OCR 工具。
- 不依赖 `pdftoppm`、`qpdf`、`pdftk`，除非用户确认本机可用。

### Fallback Policy

- 文本抽取优先 `scripts/extract_text.py`；失败时可退回 `read_uploaded_file`，并说明抽取质量可能较低。
- 表格抽取优先 `scripts/extract_tables.py`；如果返回 `table_count=0`，明确说明未检测到结构化表格，不要伪造表格。
- 如果脚本不存在或依赖缺失，不要反复搜索超过一次；说明该能力未落地或依赖缺失，并给出可行替代方案。
- 扫描件/OCR、`pdf2image`、Poppler 相关能力当前未启用时，要明确说明当前不支持。
- 如果脚本执行成功且结果足够回答用户，停止继续调用工具，直接总结真实结果。

## Overview

This guide covers essential PDF processing operations using Python libraries and command-line tools. For advanced features, JavaScript libraries, and detailed examples, see REFERENCE.md. If you need to fill out a PDF form, read FORMS.md and follow its instructions.

## Quick Start

```python
from pypdf import PdfReader, PdfWriter

# Read a PDF
reader = PdfReader("document.pdf")
print(f"Pages: {len(reader.pages)}")

# Extract text
text = ""
for page in reader.pages:
    text += page.extract_text()
```

## Python Libraries

### pypdf - Basic Operations

#### Merge PDFs
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf", "doc3.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as output:
    writer.write(output)
```

#### Split PDF
```python
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as output:
        writer.write(output)
```

#### Extract Metadata
```python
reader = PdfReader("document.pdf")
meta = reader.metadata
print(f"Title: {meta.title}")
print(f"Author: {meta.author}")
print(f"Subject: {meta.subject}")
print(f"Creator: {meta.creator}")
```

#### Rotate Pages
```python
reader = PdfReader("input.pdf")
writer = PdfWriter()

page = reader.pages[0]
page.rotate(90)  # Rotate 90 degrees clockwise
writer.add_page(page)

with open("rotated.pdf", "wb") as output:
    writer.write(output)
```

### pdfplumber - Text and Table Extraction

#### Extract Text with Layout
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        print(text)
```

#### Extract Tables
```python
with pdfplumber.open("document.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for j, table in enumerate(tables):
            print(f"Table {j+1} on page {i+1}:")
            for row in table:
                print(row)
```

#### Advanced Table Extraction
```python
import pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if table:  # Check if table is not empty
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)

# Combine all tables
if all_tables:
    combined_df = pd.concat(all_tables, ignore_index=True)
    combined_df.to_excel("extracted_tables.xlsx", index=False)
```

### reportlab - Create PDFs

#### Basic PDF Creation
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("hello.pdf", pagesize=letter)
width, height = letter

# Add text
c.drawString(100, height - 100, "Hello World!")
c.drawString(100, height - 120, "This is a PDF created with reportlab")

# Add a line
c.line(100, height - 140, 400, height - 140)

# Save
c.save()
```

#### Create PDF with Multiple Pages
```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = []

# Add content
title = Paragraph("Report Title", styles['Title'])
story.append(title)
story.append(Spacer(1, 12))

body = Paragraph("This is the body of the report. " * 20, styles['Normal'])
story.append(body)
story.append(PageBreak())

# Page 2
story.append(Paragraph("Page 2", styles['Heading1']))
story.append(Paragraph("Content for page 2", styles['Normal']))

# Build PDF
doc.build(story)
```

#### Subscripts and Superscripts

**IMPORTANT**: Never use Unicode subscript/superscript characters (₀₁₂₃₄₅₆₇₈₉, ⁰¹²³⁴⁵⁶⁷⁸⁹) in ReportLab PDFs. The built-in fonts do not include these glyphs, causing them to render as solid black boxes.

Instead, use ReportLab's XML markup tags in Paragraph objects:
```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet

styles = getSampleStyleSheet()

# Subscripts: use <sub> tag
chemical = Paragraph("H<sub>2</sub>O", styles['Normal'])

# Superscripts: use <super> tag
squared = Paragraph("x<super>2</super> + y<super>2</super>", styles['Normal'])
```

For canvas-drawn text (not Paragraph objects), manually adjust font the size and position rather than using Unicode subscripts/superscripts.

## Command-Line Tools

### pdftotext (poppler-utils)
```bash
# Extract text
pdftotext input.pdf output.txt

# Extract text preserving layout
pdftotext -layout input.pdf output.txt

# Extract specific pages
pdftotext -f 1 -l 5 input.pdf output.txt  # Pages 1-5
```

### qpdf
```bash
# Merge PDFs
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf

# Split pages
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf
qpdf input.pdf --pages . 6-10 -- pages6-10.pdf

# Rotate pages
qpdf input.pdf output.pdf --rotate=+90:1  # Rotate page 1 by 90 degrees

# Remove password
qpdf --password=mypassword --decrypt encrypted.pdf decrypted.pdf
```

### pdftk (if available)
```bash
# Merge
pdftk file1.pdf file2.pdf cat output merged.pdf

# Split
pdftk input.pdf burst

# Rotate
pdftk input.pdf rotate 1east output rotated.pdf
```

## Common Tasks

### Extract Text from Scanned PDFs
```python
# Requires: pip install pytesseract pdf2image
import pytesseract
from pdf2image import convert_from_path

# Convert PDF to images
images = convert_from_path('scanned.pdf')

# OCR each page
text = ""
for i, image in enumerate(images):
    text += f"Page {i+1}:\n"
    text += pytesseract.image_to_string(image)
    text += "\n\n"

print(text)
```

### Add Watermark
```python
from pypdf import PdfReader, PdfWriter

# Create watermark (or load existing)
watermark = PdfReader("watermark.pdf").pages[0]

# Apply to all pages
reader = PdfReader("document.pdf")
writer = PdfWriter()

for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```

### Extract Images
```bash
# Using pdfimages (poppler-utils)
pdfimages -j input.pdf output_prefix

# This extracts all images as output_prefix-000.jpg, output_prefix-001.jpg, etc.
```

### Password Protection
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    writer.add_page(page)

# Add password
writer.encrypt("userpassword", "ownerpassword")

with open("encrypted.pdf", "wb") as output:
    writer.write(output)
```

## Quick Reference

| Task | Best Tool | Command/Code |
|------|-----------|--------------|
| Merge PDFs | pypdf | `writer.add_page(page)` |
| Split PDFs | pypdf | One page per file |
| Extract text | pdfplumber | `page.extract_text()` |
| Extract tables | pdfplumber | `page.extract_tables()` |
| Create PDFs | reportlab | Canvas or Platypus |
| Command line merge | qpdf | `qpdf --empty --pages ...` |
| OCR scanned PDFs | pytesseract | Convert to image first |
| Fill PDF forms | pdf-lib or pypdf (see FORMS.md) | See FORMS.md |

## Next Steps

- For advanced pypdfium2 usage, see REFERENCE.md
- For JavaScript libraries (pdf-lib), see REFERENCE.md
- If you need to fill out a PDF form, follow the instructions in FORMS.md
- For troubleshooting guides, see REFERENCE.md
