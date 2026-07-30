#!/usr/bin/env python3
"""Put a right tab stop in every value cell of the template.

Run this after every export from Pages.

Why it exists: the template is authored in Pages and exported to .docx, and the
conversion does not carry tab positions across. Pages measures a tab stop from
the page; Word measures it from the left edge of the table cell the text sits
in. The exported stops sit at 6.15" inside a 2.06" cell, which is nowhere.

Why it is per cell and not per style: the 27 tables do not share a column width.
They run from 4.12" (Safety Equipment) to 4.44" (Deck and Hull). A single
position set on the Body A/B/C styles fits the wide ones and pushes the date
over the table line on the narrow ones. So each table gets a stop measured from
its own width.

    python3 scripts/set_tab_stops.py survey_template_owner.docx
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

# Word's default cell padding, each side.
CELL_MARGIN = 115  # twips, 0.08"

# Space between the date and the table line. Without it the text sits against
# the border and reads as an error.
GUTTER = 115  # twips, 0.08"

# Styles a previous version of this script wrote a stop into. Those are removed:
# a style-level stop is the wrong shape for this and would fight the per-cell
# ones set below.
STYLES_TO_CLEAN = ("Body A", "Body B", "Body C")


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


def set_tab(paragraph: str, pos: int) -> str:
    """Gives one paragraph a single right tab stop at pos."""
    tabs = f'<w:tabs><w:tab w:val="right" w:pos="{pos}"/></w:tabs>'

    ppr = re.search(r"<w:pPr>.*?</w:pPr>", paragraph, re.S)
    if not ppr:
        # No properties at all. Word is happy with pPr as the first child.
        return paragraph.replace(">", ">" + f"<w:pPr>{tabs}</w:pPr>", 1)

    body = ppr.group(0)
    if "<w:tabs>" in body:
        updated = re.sub(r"<w:tabs>.*?</w:tabs>", tabs, body, count=1, flags=re.S)
    else:
        updated = body.replace("<w:pPr>", "<w:pPr>" + tabs, 1)
    return paragraph.replace(body, updated, 1)


def process_document(xml: str) -> tuple[str, int, list[str]]:
    out = []
    last = 0
    touched = 0
    widths = []

    for tstart, tend in blocks(xml, "w:tbl"):
        table = xml[tstart:tend]
        grid = re.search(r"<w:tblGrid>.*?</w:tblGrid>", table, re.S)
        cols = (
            [int(c) for c in re.findall(r'<w:gridCol w:w="(\d+)"', grid.group(0))]
            if grid
            else []
        )
        if len(cols) < 2:
            continue

        # The value column is the last one. The stop goes just inside it.
        pos = cols[-1] - (2 * CELL_MARGIN) - GUTTER
        widths.append(f"{cols[-1] / 1440:.2f}\" -> {pos / 1440:.2f}\"")

        rebuilt = []
        seen = 0
        for rstart, rend in blocks(table, "w:tr"):
            row = table[rstart:rend]
            cells = list(blocks(row, "w:tc"))
            if not cells:
                continue
            cstart, cend = cells[-1]  # the value cell
            cell = row[cstart:cend]

            new_cell = []
            at = 0
            for pstart, pend in blocks(cell, "w:p"):
                new_cell.append(cell[at:pstart])
                new_cell.append(set_tab(cell[pstart:pend], pos))
                at = pend
                seen += 1
            new_cell.append(cell[at:])

            rebuilt.append((rstart, rend, row[:cstart] + "".join(new_cell) + row[cend:]))

        at = 0
        pieces = []
        for rstart, rend, new_row in rebuilt:
            pieces.append(table[at:rstart])
            pieces.append(new_row)
            at = rend
        pieces.append(table[at:])

        out.append(xml[last:tstart])
        out.append("".join(pieces))
        last = tend
        touched += seen

    out.append(xml[last:])
    return "".join(out), touched, widths


def clean_styles(styles_xml: str) -> str:
    """Takes back the style-level stop an earlier version of this script set."""
    for style_id in STYLES_TO_CLEAN:
        m = re.search(
            r'<w:style [^>]*w:styleId="' + re.escape(style_id) + r'".*?</w:style>',
            styles_xml,
            re.S,
        )
        if not m:
            continue
        cleaned = re.sub(r"<w:tabs>.*?</w:tabs>", "", m.group(0), flags=re.S)
        styles_xml = styles_xml.replace(m.group(0), cleaned, 1)
    return styles_xml


def main(path: Path) -> int:
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    backup = path.with_suffix(path.suffix + ".before-tabs")
    shutil.copy2(path, backup)

    source = zipfile.ZipFile(path)
    document, touched, widths = process_document(
        source.read("word/document.xml").decode("utf8")
    )
    styles = clean_styles(source.read("word/styles.xml").decode("utf8"))

    out = path.with_suffix(".tmp")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/document.xml":
                data = document.encode("utf8")
            elif item.filename == "word/styles.xml":
                data = styles.encode("utf8")
            target.writestr(item, data)
    source.close()
    out.replace(path)

    print(f"{len(widths)} tables, {touched} value cells")
    for w in widths:
        print(f"  {w}")
    print(f"\nPrevious file kept as {backup.name}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "survey_template_owner.docx")
    raise SystemExit(main(target))
