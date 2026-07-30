#!/usr/bin/env python3
"""Give the template a third column for the date each item was last looked at.

Run this after every export from Pages.

    python3 scripts/add_date_column.py survey_template_owner.docx

Replaces set_tab_stops.py, which tried to do this with a right tab stop inside
the value cell. That failed twice: the position has to be computed, and where
Word actually puts a stop inside an indented table cell did not match the
arithmetic, so the dates sat on the table line. A column needs no arithmetic —
the cell is right-aligned and has its own padding, which is what was wanted.

For every row whose value cell holds {{item}}, this adds a cell holding
{{item_date}} and takes the width out of the value column. The mapper fills
both. You never touch Pages: the placeholders are derived from the ones already
there.
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

# Wide enough for "05/2026" at 11pt with room either side.
DATE_WIDTH = 1000  # twips, 0.69"

# The page is 8.5" with 1" margins, so the text column is 6.5". Every item table
# is squared to this and un-indented.
#
# They did not start that way. As exported from Pages they were 5.96" to 6.50"
# wide and indented anywhere from 0.23" to 0.75", so most of them ran off the
# right of the page -- one by three quarters of an inch -- and none of them
# lined up with each other. That is why the date looked like it sat on the table
# line: the line was past the margin.
TEXT_WIDTH = 9360  # twips, 6.5"

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# Keys that describe the report or the vessel, not an item on the boat. A table
# made only of these is the cover sheet and gets no date column -- the first
# version gave it {{survey_date_date}}, which is nothing.
NOT_ITEMS = {
    "survey_number", "survey_date", "survey_type", "survey_conditions",
    "survey_overview", "location_of_survey", "present_at_survey", "weather",
    "client_name", "client_address", "client_email",
    "surveyor_name", "surveyor_email", "surveyor_phone", "surveyor_website",
}


def blocks(xml: str, tag: str):
    """Yields (start, end) for each top-level <tag>…</tag>, nesting aware."""
    open_re = re.compile(r"<" + tag + r"(?:\s[^>]*)?>")
    close = f"</{tag}>"
    i, depth, start = 0, 0, None
    while i < len(xml):
        m = open_re.match(xml, i)
        if m:
            if depth == 0:
                start = m.start()
            depth += 1
            i = m.end()
            continue
        if xml.startswith(close, i):
            depth -= 1
            i += len(close)
            if depth == 0:
                yield start, i
            continue
        i += 1


def date_cell(value_cell: str, key: str | None) -> str:
    """A cell of the same shape as the value cell, right-aligned, holding the
    date placeholder.

    Built by copying the value cell rather than written from scratch, so it
    inherits the borders, shading and vertical alignment the rest of the table
    uses. Only the width, the paragraph alignment and the text change.
    """
    cell = value_cell

    # Its own width.
    cell = re.sub(
        r'<w:tcW[^>]*/>',
        f'<w:tcW w:type="dxa" w:w="{DATE_WIDTH}"/>',
        cell,
        count=1,
    )

    # Keep the first paragraph, drop any others: a value cell may hold several
    # and the date needs exactly one.
    paragraphs = list(blocks(cell, "w:p"))
    if paragraphs:
        first_start, first_end = paragraphs[0]
        last_end = paragraphs[-1][1]
        cell = cell[:first_start] + cell[first_start:first_end] + cell[last_end:]

    # One run, right-aligned, holding the placeholder or nothing.
    text = f"{{{{{key}_date}}}}" if key else ""
    ppr = re.search(r"<w:pPr>.*?</w:pPr>", cell, re.S)
    if ppr:
        body = re.sub(r"<w:jc[^>]*/>", "", ppr.group(0))
        body = body.replace("<w:pPr>", '<w:pPr><w:jc w:val="right"/>', 1)
        # A tab stop from an earlier attempt would do nothing here, but leaving
        # one in is a puzzle for whoever reads this next.
        body = re.sub(r"<w:tabs>.*?</w:tabs>", "", body, flags=re.S)
        cell = cell.replace(ppr.group(0), body, 1)

    runs = list(blocks(cell, "w:r"))
    if runs:
        first = cell[runs[0][0]:runs[0][1]]
        rpr = re.search(r"<w:rPr>.*?</w:rPr>", first, re.S)
        new_run = f"<w:r>{rpr.group(0) if rpr else ''}<w:t>{text}</w:t></w:r>"
        cell = cell[:runs[0][0]] + new_run + cell[runs[-1][1]:]

    return cell


def process(xml: str) -> tuple[str, int, int]:
    out, last, dated, widened = [], 0, 0, 0

    for tstart, tend in blocks(xml, "w:tbl"):
        table = xml[tstart:tend]
        grid = re.search(r"<w:tblGrid>.*?</w:tblGrid>", table, re.S)
        cols = (
            [int(c) for c in re.findall(r'<w:gridCol w:w="(\d+)"', grid.group(0))]
            if grid
            else []
        )
        if len(cols) != 2:
            continue

        # Leave the cover sheet alone.
        found = {m.group(1) for m in PLACEHOLDER.finditer(re.sub(r"<[^>]+>", "", table))}
        if found and found <= NOT_ITEMS:
            continue

        # Square the table to the text column and un-indent it. The label column
        # keeps its share of what is left after the date column.
        label = round((TEXT_WIDTH - DATE_WIDTH) * cols[0] / sum(cols))
        value_width = TEXT_WIDTH - DATE_WIDTH - label

        new_grid = (
            "<w:tblGrid>"
            + f'<w:gridCol w:w="{label}"/>'
            + f'<w:gridCol w:w="{value_width}"/>'
            + f'<w:gridCol w:w="{DATE_WIDTH}"/>'
            + "</w:tblGrid>"
        )
        table = table.replace(grid.group(0), new_grid, 1)

        table = re.sub(
            r'<w:tblW w:w="\d+" w:type="dxa"/>',
            f'<w:tblW w:w="{TEXT_WIDTH}" w:type="dxa"/>',
            table,
            count=1,
        )
        table = re.sub(
            r'<w:tblInd w:w="\d+"([^>]*)/>',
            r'<w:tblInd w:w="0"\1/>',
            table,
            count=1,
        )
        widened += 1

        rows = list(blocks(table, "w:tr"))
        pieces, at = [], 0
        for rstart, rend in rows:
            row = table[rstart:rend]
            cells = list(blocks(row, "w:tc"))
            pieces.append(table[at:rstart])
            at = rend

            if len(cells) == 1:
                # A heading spanning the table. Widen the span rather than add a
                # cell, or the row stops lining up with the ones around it.
                if "<w:gridSpan" in row:
                    row = re.sub(
                        r'<w:gridSpan w:val="(\d+)"/>',
                        lambda m: f'<w:gridSpan w:val="{int(m.group(1)) + 1}"/>',
                        row,
                        count=1,
                    )
                else:
                    row = row.replace(
                        "<w:tcPr>", '<w:tcPr><w:gridSpan w:val="3"/>', 1
                    )
                row = re.sub(
                    r'<w:tcW[^>]*/>',
                    f'<w:tcW w:type="dxa" w:w="{TEXT_WIDTH}"/>',
                    row,
                    count=1,
                )
                pieces.append(row)
                continue

            if len(cells) != 2:
                pieces.append(row)
                continue

            lstart, lend = cells[0]
            cstart, cend = cells[-1]

            # Every cell takes the grid's width. Leaving the old ones in place
            # is what let the tables disagree with their own grid and run off
            # the page.
            def resize(cell: str, w: int) -> str:
                return re.sub(
                    r'<w:tcW[^>]*/>',
                    f'<w:tcW w:type="dxa" w:w="{w}"/>',
                    cell,
                    count=1,
                )

            label_cell = resize(row[lstart:lend], label)
            value = row[cstart:cend]

            found = PLACEHOLDER.search(re.sub(r"<[^>]+>", "", value))
            key = found.group(1) if found and found.group(1) not in NOT_ITEMS else None
            if key:
                dated += 1

            pieces.append(
                row[:lstart]
                + label_cell
                + row[lend:cstart]
                + resize(value, value_width)
                + date_cell(value, key)
                + row[cend:]
            )

        pieces.append(table[at:])
        table = "".join(pieces)

        out.append(xml[last:tstart])
        out.append(table)
        last = tend

    out.append(xml[last:])
    return "".join(out), widened, dated


def main(path: Path) -> int:
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    source = zipfile.ZipFile(path)
    document = source.read("word/document.xml").decode("utf8")

    # Look for this script's own column, not for any key ending in _date --
    # {{survey_date}} is on the cover sheet and has nothing to do with this.
    if f'<w:gridCol w:w="{DATE_WIDTH}"/>' in document:
        print("This file already has a date column. Export again from Pages first.")
        source.close()
        return 1

    backup = path.with_suffix(path.suffix + ".before-dates")
    shutil.copy2(path, backup)

    document, tables, dated = process(document)

    out = path.with_suffix(".tmp")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/document.xml":
                data = document.encode("utf8")
            target.writestr(item, data)
    source.close()
    out.replace(path)

    print(f"{tables} tables widened, {dated} date placeholders added")
    print(f'Date column {DATE_WIDTH / 1440:.2f}", taken out of the value column')
    print(f"Previous file kept as {backup.name}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "survey_template_owner.docx")
    raise SystemExit(main(target))
