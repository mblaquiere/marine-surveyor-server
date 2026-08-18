"""
Put the Monitor Findings section back into the owner template.

Run this on survey_template_owner.docx after every export from Pages, between
add_date_column.py and add_finding_photos.py. Pages drops this section along
with the other two, and unlike them it cannot be rebuilt from what is left:
add_finding_photos.py converts a loop that is already there, and after an
export there is no monitor loop to convert.

Why it matters. "Monitor" is not a professional survey grade. It means watch
this, which is what an owner writes down most of the time -- 43 of the 56
findings on SV Liquid are monitor. Without the section the report leaves out
three quarters of what a walk turned up, and says nothing about having done so.

What it does. Two insertions, both copied from paragraphs already in the file
so they carry that export's own styling rather than styling guessed here:

  - the legend line, after "C FINDINGS: ..." in Findings Definitions
  - the heading "Monitor Findings" and a three-paragraph loop, before the
    "Further Testing Required" heading

The loop goes in as the plain-string shape:

    {% for line in monitor_findings_list %}
    {{ line }}
    {% endfor %}

which is what the other five blocks look like straight out of Pages, so
add_finding_photos.py then converts all six the same way. Inserting the
photograph shape here instead would make that script think the file was already
done and skip the other five.

Refuses to run twice, so running it again after a small edit is safe.

Usage:
    python3 scripts/add_monitor_block.py survey_template_owner.docx
"""

import re
import shutil
import sys
import zipfile

DOC = "word/document.xml"

LEGEND = (
    "MONITOR FINDINGS: Sound but worth watching. Noted so the next survey "
    "can say whether it moved."
)
HEADING = "Monitor Findings"

# Where each one goes. The legend follows the C line; the block comes before the
# Further Testing heading, which is the order the definitions list uses.
AFTER_LEGEND = "C FINDINGS:"
BEFORE_HEADING = "Further Testing Required"


def paragraphs(xml):
    """Every paragraph as (start, end, visible text).

    Word splits one sentence across several runs whenever it feels like it, so
    matching on the raw XML finds nothing. This joins the runs first.
    """
    out = []
    for match in re.finditer(r"<w:p\b.*?</w:p>", xml, re.S):
        block = match.group(0)
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block, re.S))
        out.append((match.start(), match.end(), text))
    return out


def find(paras, needle, exact=False):
    """The first paragraph whose text matches. None when there is none."""
    for start, end, text in paras:
        stripped = text.strip()
        if (stripped == needle) if exact else (needle in text):
            return (start, end, text)
    return None


def retext(block, new_text):
    """The same paragraph carrying different words.

    Keeps the paragraph and its first run exactly as they are -- style, font,
    spacing, all of it -- and empties every run after the first, so the text
    cannot come out split across the old boundaries.
    """
    first = [True]

    def swap(match):
        if first[0]:
            first[0] = False
            return f'<w:t xml:space="preserve">{new_text}</w:t>'
        return '<w:t xml:space="preserve"></w:t>'

    return re.sub(r"<w:t[^>]*>.*?</w:t>", swap, block, flags=re.S)


def rewrite(xml):
    if "monitor_findings" in xml:
        print("Already done -- nothing to change.")
        return xml, 0

    paras = paragraphs(xml)

    legend_para = find(paras, AFTER_LEGEND)
    heading_para = find(paras, BEFORE_HEADING, exact=True)
    if legend_para is None:
        print(f'Could not find a paragraph containing "{AFTER_LEGEND}".')
        return xml, 0
    if heading_para is None:
        print(f'Could not find a heading reading "{BEFORE_HEADING}".')
        return xml, 0

    # The three paragraphs of the C block, used as the pattern for this one.
    c_for = find(paras, "{% for line in c_findings_list %}")
    if c_for is None:
        print("Could not find the C findings loop to copy.")
        return xml, 0
    c_index = [p[0] for p in paras].index(c_for[0])
    c_block = paras[c_index : c_index + 3]
    if len(c_block) != 3 or "endfor" not in c_block[2][2]:
        print("The C findings block is not the three paragraphs expected.")
        return xml, 0

    def source(para):
        return xml[para[0] : para[1]]

    new_block = (
        retext(source(heading_para), HEADING)
        + retext(source(c_block[0]), "{% for line in monitor_findings_list %}")
        + retext(source(c_block[1]), "{{ line }}")
        + retext(source(c_block[2]), "{% endfor %}")
    )
    new_legend = retext(source(legend_para), LEGEND)

    # Later position first, so inserting does not move the earlier one.
    at_heading = heading_para[0]
    at_legend = legend_para[1]
    if at_heading < at_legend:
        print("The definitions list and the blocks are not in the order expected.")
        return xml, 0

    xml = xml[:at_heading] + new_block + xml[at_heading:]
    xml = xml[:at_legend] + new_legend + xml[at_legend:]

    print("  legend line inserted after the C definition")
    print("  Monitor Findings heading and loop inserted before Further Testing")
    return xml, 2


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

    print(f"\n{changed} insertion(s) made. Backup at {backup}")


if __name__ == "__main__":
    main()
