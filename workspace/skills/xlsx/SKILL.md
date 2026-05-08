---
name: xlsx
description: "Use this skill any time a spreadsheet file is the primary input or output. This means any task where the user wants to: open, read, edit, or fix an existing .xlsx, .xlsm, .csv, or .tsv file (e.g., adding columns, computing formulas, formatting, charting, cleaning messy data); create a new spreadsheet from scratch or from other data sources; or convert between tabular file formats. Trigger especially when the user references a spreadsheet file by name or path — even casually (like \"the xlsx in my downloads\") — and wants something done to it or produced from it. Also trigger for cleaning or restructuring messy tabular data files (malformed rows, misplaced headers, junk data) into proper spreadsheets. The deliverable must be a spreadsheet file. Do NOT trigger when the primary deliverable is a Word document, HTML report, standalone Python script, database pipeline, or Google Sheets API integration, even if tabular data is involved."
triggers:
- .xlsx
- .xlsm
- .csv
- .tsv
- xlsx
- Excel
- excel
- 表格
- 电子表格
- 工作簿
- 工作表
- 新增列
- 新增行
- 公式
- 重算
- 汇总
- 数据清洗
license: Proprietary. LICENSE.txt has complete terms
---

# Requirements for Outputs

## MiniAgent Project Workflow

当前项目优先使用 `openpyxl`、`pandas` 和 LibreOffice 重算脚本。修改类任务必须形成“读取 -> 修改 -> 保存 outbox -> 重算/验证 -> 回复”的闭环。

### Supported Now

- 读取和摘要：优先使用 `read_uploaded_file` 获取工作簿摘要；需要精确计算时用 `pandas` / `openpyxl` 读取源文件。
- 新建表格：使用 `openpyxl` 创建 `.xlsx`，写入标题、单元格、公式和样式。
- 修改表格：优先使用 `run_skill_script(skill_name="xlsx", script_path="scripts/edit_workbook.py", arguments=[...], timeout_seconds=60)` 完成常见增删改查；复杂任务再用 `openpyxl` 编写专用逻辑。
- 条件筛选：优先使用 `run_skill_script(skill_name="xlsx", script_path="scripts/filter_workbook.py", arguments=[...], timeout_seconds=60)` 按列和关键词筛选行，并输出新的 `.xlsx`。
- 公式重算：如果文件包含公式，必须使用 `run_skill_script(skill_name="xlsx", script_path="scripts/recalc.py", arguments=["<output_xlsx_path>"], timeout_seconds=60)`。
- 公式错误检查：依据 `recalc.py` 返回的 JSON 判断 `status`、`total_errors`、`error_summary`。

### Required Flow

1. 使用 `list_uploaded_files` / `read_uploaded_file` 定位输入文件。
2. 明确要改哪些 sheet、列、行、公式或格式。
3. 对常见表格增删改查，优先调用 `scripts/edit_workbook.py`，生成结果文件到当前会话 outbox，不覆盖 inbox 原始文件。
4. 对按关键词筛选并输出新表的任务，优先调用 `scripts/filter_workbook.py`，不要编造不存在的专用筛选脚本。
5. 如果含公式，调用 `run_skill_script` 执行 `scripts/recalc.py`；若发现 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 等错误，必须修复后再交付。
6. 回复时只给处理摘要、输出文件名、关键校验结果。

### edit_workbook.py Common Operations

统一调用方式：

```text
run_skill_script(skill_name="xlsx", script_path="scripts/edit_workbook.py", arguments=["<input.xlsx>", "<output.xlsx>", "--operation", "<operation>", ...], timeout_seconds=60)
```

`<input.xlsx>` 和 `<output.xlsx>` 优先使用工具返回的绝对路径；输出路径必须位于当前会话 outbox。

常用操作：

- 查看工作簿：`--operation inspect`
- 读取区域：`--operation read-range --sheet Sheet1 --range A1:E20`
- 设置单元格：`--operation set-cell --sheet Sheet1 --cell B2 --value 123`
- 追加行：`--operation append-row --sheet Sheet1 --values Jan 100 70`
- 插入行：`--operation insert-row --sheet Sheet1 --row 2 --values Jan 100 70`
- 删除行：`--operation delete-row --sheet Sheet1 --row 2`
- 插入列：`--operation insert-column --sheet Sheet1 --column C --value Total`
- 删除列：`--operation delete-column --sheet Sheet1 --column Total`
- 设置表头：`--operation set-header --sheet Sheet1 --column E --value Margin`
- 新增公式列：`--operation add-formula-column --sheet Sheet1 --column E --value Margin --formula "D{row}/B{row}"`
- 新增汇总行：`--operation add-sum-row --sheet ValidModel --columns Revenue Cost Profit --label-column Month --label Total`
- 重命名工作表：`--operation rename-sheet --sheet Sheet1 --new-name ValidModel`
- 复制工作表：`--operation copy-sheet --sheet Sheet1 --new-name Backup`
- 删除工作表：`--operation delete-sheet --sheet Backup`

### filter_workbook.py Row Filtering

统一调用方式：

```text
run_skill_script(skill_name="xlsx", script_path="scripts/filter_workbook.py", arguments=["<input.xlsx>", "<output.xlsx>", "--sheet", "Sheet1", "--criteria-json", "<json>"], timeout_seconds=60)
```

条件 JSON 结构：

```json
{
  "include": [
    {"columns": ["专业", "需求专业"], "keywords": ["软件工程"]},
    {"columns": ["项目名称", "具体项目需求工作描述", "现有研究基础与应用前景"], "keywords": ["AI", "人工智能", "大模型", "LLM"]}
  ],
  "exclude": []
}
```

规则：

- 每个 `include` 条件组内部默认是关键词 OR。
- 多个 `include` 条件组之间是 AND。
- `exclude` 命中时会排除该行。
- 输出文件保留原始表头、匹配行和基础样式。
- 不要调用不存在的专用脚本；如果需要筛选，优先使用 `scripts/filter_workbook.py`。

### Current Limits

- 复杂模板编辑要优先保留原样式；`pandas` 写回可能破坏样式，需谨慎。

### Fallback Policy

- `edit_workbook.py` 不支持的操作，可用 `openpyxl` 编写一次性脚本，但必须保存到 outbox，不覆盖 inbox 原件。
- `recalc.py` 失败时，明确说明 LibreOffice 或公式重算失败，不要声称公式已校验。
- 如果发现 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 等公式错误，不得说文件完全成功，必须列出错误位置或受影响工作表。
- 如果工具参数格式错误，最多修正并重试一次；再次失败就停止工具调用并说明缺少什么信息。
- 如果脚本执行成功且结果足够完成用户请求，停止继续调用工具，直接总结真实结果。

## All Excel files

### Professional Font
- Use a consistent, professional font (e.g., Arial, Times New Roman) for all deliverables unless otherwise instructed by the user

### Zero Formula Errors
- Every Excel model MUST be delivered with ZERO formula errors (#REF!, #DIV/0!, #VALUE!, #N/A, #NAME?)

### Preserve Existing Templates (when updating templates)
- Study and EXACTLY match existing format, style, and conventions when modifying files
- Never impose standardized formatting on files with established patterns
- Existing template conventions ALWAYS override these guidelines

## Financial models

### Color Coding Standards
Unless otherwise stated by the user or existing template

#### Industry-Standard Color Conventions
- **Blue text (RGB: 0,0,255)**: Hardcoded inputs, and numbers users will change for scenarios
- **Black text (RGB: 0,0,0)**: ALL formulas and calculations
- **Green text (RGB: 0,128,0)**: Links pulling from other worksheets within same workbook
- **Red text (RGB: 255,0,0)**: External links to other files
- **Yellow background (RGB: 255,255,0)**: Key assumptions needing attention or cells that need to be updated

### Number Formatting Standards

#### Required Format Rules
- **Years**: Format as text strings (e.g., "2024" not "2,024")
- **Currency**: Use $#,##0 format; ALWAYS specify units in headers ("Revenue ($mm)")
- **Zeros**: Use number formatting to make all zeros "-", including percentages (e.g., "$#,##0;($#,##0);-")
- **Percentages**: Default to 0.0% format (one decimal)
- **Multiples**: Format as 0.0x for valuation multiples (EV/EBITDA, P/E)
- **Negative numbers**: Use parentheses (123) not minus -123

### Formula Construction Rules

#### Assumptions Placement
- Place ALL assumptions (growth rates, margins, multiples, etc.) in separate assumption cells
- Use cell references instead of hardcoded values in formulas
- Example: Use =B5*(1+$B$6) instead of =B5*1.05

#### Formula Error Prevention
- Verify all cell references are correct
- Check for off-by-one errors in ranges
- Ensure consistent formulas across all projection periods
- Test with edge cases (zero values, negative numbers)
- Verify no unintended circular references

#### Documentation Requirements for Hardcodes
- Comment or in cells beside (if end of table). Format: "Source: [System/Document], [Date], [Specific Reference], [URL if applicable]"
- Examples:
  - "Source: Company 10-K, FY2024, Page 45, Revenue Note, [SEC EDGAR URL]"
  - "Source: Company 10-Q, Q2 2025, Exhibit 99.1, [SEC EDGAR URL]"
  - "Source: Bloomberg Terminal, 8/15/2025, AAPL US Equity"
  - "Source: FactSet, 8/20/2025, Consensus Estimates Screen"

# XLSX creation, editing, and analysis

## Overview

A user may ask you to create, edit, or analyze the contents of an .xlsx file. You have different tools and workflows available for different tasks.

## Important Requirements

**LibreOffice Required for Formula Recalculation**: You can assume LibreOffice is installed for recalculating formula values using the `scripts/recalc.py` script. The script automatically configures LibreOffice on first run, including in sandboxed environments where Unix sockets are restricted (handled by `scripts/office/soffice.py`)

## Reading and analyzing data

### Data analysis with pandas
For data analysis, visualization, and basic operations, use **pandas** which provides powerful data manipulation capabilities:

```python
import pandas as pd

# Read Excel
df = pd.read_excel('file.xlsx')  # Default: first sheet
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # All sheets as dict

# Analyze
df.head()      # Preview data
df.info()      # Column info
df.describe()  # Statistics

# Write Excel
df.to_excel('output.xlsx', index=False)
```

## Excel File Workflows

## CRITICAL: Use Formulas, Not Hardcoded Values

**Always use Excel formulas instead of calculating values in Python and hardcoding them.** This ensures the spreadsheet remains dynamic and updateable.

### ❌ WRONG - Hardcoding Calculated Values
```python
# Bad: Calculating in Python and hardcoding result
total = df['Sales'].sum()
sheet['B10'] = total  # Hardcodes 5000

# Bad: Computing growth rate in Python
growth = (df.iloc[-1]['Revenue'] - df.iloc[0]['Revenue']) / df.iloc[0]['Revenue']
sheet['C5'] = growth  # Hardcodes 0.15

# Bad: Python calculation for average
avg = sum(values) / len(values)
sheet['D20'] = avg  # Hardcodes 42.5
```

### ✅ CORRECT - Using Excel Formulas
```python
# Good: Let Excel calculate the sum
sheet['B10'] = '=SUM(B2:B9)'

# Good: Growth rate as Excel formula
sheet['C5'] = '=(C4-C2)/C2'

# Good: Average using Excel function
sheet['D20'] = '=AVERAGE(D2:D19)'
```

This applies to ALL calculations - totals, percentages, ratios, differences, etc. The spreadsheet should be able to recalculate when source data changes.

## Common Workflow
1. **Choose tool**: pandas for data, openpyxl for formulas/formatting
2. **Create/Load**: Create new workbook or load existing file
3. **Modify**: Add/edit data, formulas, and formatting
4. **Save**: Write to file
5. **Recalculate formulas (MANDATORY IF USING FORMULAS)**: Use `run_skill_script(skill_name="xlsx", script_path="scripts/recalc.py", arguments=["output.xlsx"], timeout_seconds=60)`.
6. **Verify and fix any errors**: 
   - The script returns JSON with error details
   - If `status` is `errors_found`, check `error_summary` for specific error types and locations
   - Fix the identified errors and recalculate again
   - Common errors to fix:
     - `#REF!`: Invalid cell references
     - `#DIV/0!`: Division by zero
     - `#VALUE!`: Wrong data type in formula
     - `#NAME?`: Unrecognized formula name

### Creating new Excel files

```python
# Using openpyxl for formulas and formatting
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

# Add data
sheet['A1'] = 'Hello'
sheet['B1'] = 'World'
sheet.append(['Row', 'of', 'data'])

# Add formula
sheet['B2'] = '=SUM(A1:A10)'

# Formatting
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')

# Column width
sheet.column_dimensions['A'].width = 20

wb.save('output.xlsx')
```

### Editing existing Excel files

```python
# Using openpyxl to preserve formulas and formatting
from openpyxl import load_workbook

# Load existing file
wb = load_workbook('existing.xlsx')
sheet = wb.active  # or wb['SheetName'] for specific sheet

# Working with multiple sheets
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    print(f"Sheet: {sheet_name}")

# Modify cells
sheet['A1'] = 'New Value'
sheet.insert_rows(2)  # Insert row at position 2
sheet.delete_cols(3)  # Delete column 3

# Add new sheet
new_sheet = wb.create_sheet('NewSheet')
new_sheet['A1'] = 'Data'

wb.save('modified.xlsx')
```

## Recalculating formulas

Excel files created or modified by openpyxl contain formulas as strings but not calculated values. Use the provided `scripts/recalc.py` script through `run_skill_script` to recalculate formulas:

Example:
```text
run_skill_script(skill_name="xlsx", script_path="scripts/recalc.py", arguments=["output.xlsx", "30"], timeout_seconds=60)
```

The script:
- Automatically sets up LibreOffice macro on first run
- Recalculates all formulas in all sheets
- Scans ALL cells for Excel errors (#REF!, #DIV/0!, etc.)
- Returns JSON with detailed error locations and counts
- Works on both Linux and macOS

## Formula Verification Checklist

Quick checks to ensure formulas work correctly:

### Essential Verification
- [ ] **Test 2-3 sample references**: Verify they pull correct values before building full model
- [ ] **Column mapping**: Confirm Excel columns match (e.g., column 64 = BL, not BK)
- [ ] **Row offset**: Remember Excel rows are 1-indexed (DataFrame row 5 = Excel row 6)

### Common Pitfalls
- [ ] **NaN handling**: Check for null values with `pd.notna()`
- [ ] **Far-right columns**: FY data often in columns 50+ 
- [ ] **Multiple matches**: Search all occurrences, not just first
- [ ] **Division by zero**: Check denominators before using `/` in formulas (#DIV/0!)
- [ ] **Wrong references**: Verify all cell references point to intended cells (#REF!)
- [ ] **Cross-sheet references**: Use correct format (Sheet1!A1) for linking sheets

### Formula Testing Strategy
- [ ] **Start small**: Test formulas on 2-3 cells before applying broadly
- [ ] **Verify dependencies**: Check all cells referenced in formulas exist
- [ ] **Test edge cases**: Include zero, negative, and very large values

### Interpreting scripts/recalc.py Output
The script returns JSON with error details:
```json
{
  "status": "success",           // or "errors_found"
  "total_errors": 0,              // Total error count
  "total_formulas": 42,           // Number of formulas in file
  "error_summary": {              // Only present if errors found
    "#REF!": {
      "count": 2,
      "locations": ["Sheet1!B5", "Sheet1!C10"]
    }
  }
}
```

## Best Practices

### Library Selection
- **pandas**: Best for data analysis, bulk operations, and simple data export
- **openpyxl**: Best for complex formatting, formulas, and Excel-specific features

### Working with openpyxl
- Cell indices are 1-based (row=1, column=1 refers to cell A1)
- Use `data_only=True` to read calculated values: `load_workbook('file.xlsx', data_only=True)`
- **Warning**: If opened with `data_only=True` and saved, formulas are replaced with values and permanently lost
- For large files: Use `read_only=True` for reading or `write_only=True` for writing
- Formulas are preserved but not evaluated - use scripts/recalc.py to update values

### Working with pandas
- Specify data types to avoid inference issues: `pd.read_excel('file.xlsx', dtype={'id': str})`
- For large files, read specific columns: `pd.read_excel('file.xlsx', usecols=['A', 'C', 'E'])`
- Handle dates properly: `pd.read_excel('file.xlsx', parse_dates=['date_column'])`

## Code Style Guidelines
**IMPORTANT**: When generating Python code for Excel operations:
- Write minimal, concise Python code without unnecessary comments
- Avoid verbose variable names and redundant operations
- Avoid unnecessary print statements

**For Excel files themselves**:
- Add comments to cells with complex formulas or important assumptions
- Document data sources for hardcoded values
- Include notes for key calculations and model sections
