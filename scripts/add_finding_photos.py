"""
Let each finding in the owner template carry a photograph.

Run this on survey_template_owner.docx after every export from Pages, along
with add_date_column.py. Pages knows nothing about either change and drops both
each time it writes the file.

What it does. Each severity block in the template is three paragraphs:

    {% for line in aa_findings_list %}
    {{ line }}
    {% endfor %}

A string cannot carry a picture, so the loop moves to a list of objects and
gains a paragraph for the photograph:

    {%p for f in aa_findings_items %}
    {{ f.text }}
    {%p if f.photo %}
    {{ f.photo }}
    {%p endif %}
    {%p endfor %}

The if is what keeps the report readable. Most findings have no photograph --
on SV Liquid, most are "monitor" notes typed at the chart table -- and without
the guard each one would print a blank line.

The {%p prefix tells docxtpl to delete the whole paragraph holding the tag
rather than leave an empty one behind. The existing for and endfor are left
plain so the block spaces itself on the page exactly as it does today.

app.py builds both aa_findings_list and aa_findings_items. The older
professional template still loops over the strings.

Usage:
    python3 scripts/add_finding_photos.py survey_template_owner.docx
"""

import re
import shutil
import sys
import zipfile

SEVERITIES = ("aa", "a", "b", "c", "monitor", "ftr")

DOC = "word/document.xml"


def paragraph(inner_runs, extra_ppr=""):
    """A paragraph matching the ones already in the findings blocks."""
    return (
        "<w:p><w:pPr><w:pStyle w:val=\"Default\"/>"
        "<w:spacing w:before=\"0\" w:line=\"240\" w:lineRule=\"auto\"/>"
        f"{extra_ppr}"
        "<w:rPr><w:rFonts w:ascii=\"Arial\" w:cs=\"Arial\" w:hAnsi=\"Arial\" "
        "w:eastAsia=\"Arial\"/></w:rPr></w:pPr>"
        f"{inner_runs}</w:p>"
    )


def run(text):
    return (
        "<w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/>"
        "<w:rtl w:val=\"0\"/><w:lang w:val=\"en-US\"/></w:rPr>"
        f"<w:t xml:space=\"preserve\">{text}</w:t></w:r>"
    )


def rewrite(xml):
    if "_findings_items" in xml:
        print("Already done -- nothing to change.")
        return xml, 0

    changed = 0

    for sev in SEVERITIES:
        loop = f"{{% for line in {sev}_findings_list %}}"
        if loop not in xml:
            print(f"  {sev}: no loop found, skipped")
            continue

        # The whole three-paragraph block, from the paragraph holding the for
        # to the paragraph holding the endfor. Non-greedy, so it stops at the
        # first endfor after this loop.
        pattern = re.compile(
            r"<w:p\b(?:(?!</w:p>).)*?"
            + re.escape(loop)
            + r".*?<w:p\b(?:(?!</w:p>).)*?\{% endfor %\}.*?</w:p>",
            re.S,
        )
        match = pattern.search(xml)
        if not match:
            print(f"  {sev}: loop found but block did not match, skipped")
            continue

        block = match.group(0)
        if block.count("<w:p ") + block.count("<w:p>") != 3:
            print(f"  {sev}: expected three paragraphs, found something else, skipped")
            continue

        centred = "<w:jc w:val=\"center\"/>"

        new_block = (
            paragraph(run(f"{{%p for f in {sev}_findings_items %}}"))
            + paragraph(run("{{ f.text }}"))
            + paragraph(run("{%p if f.photo %}"))
            + paragraph(run("{{ f.photo }}"), extra_ppr=centred)
            + paragraph(run("{%p endif %}"))
            + paragraph(run("{%p endfor %}"))
        )

        xml = xml[: match.start()] + new_block + xml[match.end() :]
        changed += 1
        print(f"  {sev}: rewritten")

    return xml, changed


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    backup = path + ".bak"
    shutil.copy2(path, backup)

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        parts = {n: zf.read(n) for n in names}

    xml = parts[DOC].decode("utf-8")
    xml, changed = rewrite(xml)
    parts[DOC] = xml.encode("utf-8")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, parts[name])

    print(f"\n{changed} of {len(SEVERITIES)} blocks rewritten. Backup at {backup}")


if __name__ == "__main__":
    main()
