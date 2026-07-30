#!/usr/bin/env python3
"""Put a right tab stop on the template's body styles.

Run this after every export from Pages.

Why it exists: the template is authored in Pages and exported to .docx, and the
conversion does not carry tab positions across faithfully. Pages measures a tab
stop from the page; Word measures it from the left edge of the table cell the
text sits in. The existing exported stops sit at 6.15" inside a 2.06" cell,
which is to say nowhere.

So the position is set here instead, in the units Word actually uses, and the
number lives in one place rather than being re-typed into a dialog after every
export.

    python3 scripts/set_tab_stops.py survey_template_owner.docx

The report's item lines are "Sound · Volvo SN A165149<TAB>05/2026". With the
stop in place the dates form a column down the right of the value cell. Without
it they still print, just after a gap.
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

# The value cells are 4.44" wide and Word keeps 0.08" of padding each side, so
# the text area is about 4.28". A hair short of that keeps a long description
# from pushing the date onto its own line.
TAB_INCHES = 4.25
TWIPS = int(TAB_INCHES * 1440)

# The three paragraph styles the value cells use.
STYLES = ("Body A", "Body B", "Body C")

TAB_XML = f'<w:tabs><w:tab w:val="right" w:pos="{TWIPS}"/></w:tabs>'


def add_tab_stop(styles_xml: str, style_id: str) -> tuple[str, str]:
    """Returns the edited xml and a word on what happened."""
    match = re.search(
        r'<w:style [^>]*w:styleId="' + re.escape(style_id) + r'".*?</w:style>',
        styles_xml,
        re.S,
    )
    if not match:
        return styles_xml, "not found"

    block = match.group(0)
    if "<w:tabs>" in block:
        # Replace rather than add. Two sets of tabs in one style is undefined
        # and Word picks one without saying which.
        updated = re.sub(r"<w:tabs>.*?</w:tabs>", TAB_XML, block, count=1, flags=re.S)
        note = "replaced"
    else:
        # Tabs belong inside pPr. A style without one is not something this
        # template produces, but say so rather than write invalid xml.
        if "<w:pPr>" not in block:
            return styles_xml, "no pPr — left alone"
        updated = block.replace("<w:pPr>", "<w:pPr>" + TAB_XML, 1)
        note = "added"

    return styles_xml.replace(block, updated, 1), note


def main(path: Path) -> int:
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    backup = path.with_suffix(path.suffix + ".before-tabs")
    shutil.copy2(path, backup)

    source = zipfile.ZipFile(path)
    styles = source.read("word/styles.xml").decode("utf8")

    for style_id in STYLES:
        styles, note = add_tab_stop(styles, style_id)
        print(f"  {style_id:8} {note}")

    out = path.with_suffix(".tmp")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/styles.xml":
                data = styles.encode("utf8")
            target.writestr(item, data)
    source.close()
    out.replace(path)

    print(f'\nRight tab stop at {TAB_INCHES}" set on {len(STYLES)} styles.')
    print(f"Previous file kept as {backup.name}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "survey_template_owner.docx")
    raise SystemExit(main(target))
