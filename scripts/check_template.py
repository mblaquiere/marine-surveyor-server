"""
Check the owner template still has everything the report needs.

Run this after every export from Pages, once the other three scripts have run.
It reads the file and refuses it if anything they add is missing.

Why it exists. On 10 August the template was exported from Pages with real new
wording in it -- the disclaimer, the signature block -- and that export dropped
241 date placeholders, every finding's photograph, and the whole Monitor
Findings section. Roughly three quarters of what a walk turns up stopped
reaching the report. Nothing complained. The app's own test passed, because it
compares the mapper against lib/Data/owner_template_keys.dart, and that file had
been generated from the template before the export.

A README that says "run these scripts" is a thing to forget. This is a thing to
run.

Usage:
    python3 scripts/check_template.py survey_template_owner.docx
    python3 scripts/check_template.py survey_template_owner.docx \
        ../../marine_surveyor_app/lib/Data/owner_template_keys.dart

With the second argument it also compares the app's generated key list against
the template and prints what has drifted, either way.

Exits 0 when everything is there, 1 when it is not.
"""

import re
import sys
import zipfile

SEVERITIES = ("aa", "a", "b", "c", "monitor", "ftr")

# Below this many, the date column has plainly not been added. The real number
# is about 240; the floor is loose on purpose, because adding or removing
# inventory lines moves it and only a collapse means something is wrong.
LEAST_DATE_KEYS = 200

MONITOR_LEGEND = "MONITOR FINDINGS:"


def read(path):
    with zipfile.ZipFile(path) as zf:
        xml = b"".join(
            zf.read(n) for n in zf.namelist() if n.endswith(".xml")
        ).decode("utf-8", "ignore")
    return re.sub(r"<[^>]+>", "", xml)


def keys(plain):
    return set(re.findall(r"\{\{\s*([A-Za-z0-9_\.]+)", plain))


def problems(plain):
    found = keys(plain)
    out = []

    for sev in SEVERITIES:
        if f"{sev}_findings_items" not in plain:
            out.append(
                f"the {sev} findings block is missing, or still loops over "
                f"{sev}_findings_list -- run add_finding_photos.py"
            )

    if "f.photo" not in found:
        out.append(
            "no finding can carry a photograph -- run add_finding_photos.py"
        )

    dates = len([k for k in found if k.endswith("_date")])
    if dates < LEAST_DATE_KEYS:
        out.append(
            f"only {dates} date placeholders, expected at least "
            f"{LEAST_DATE_KEYS} -- run add_date_column.py"
        )

    if MONITOR_LEGEND not in plain:
        out.append(
            "the Monitor definition is missing from Findings Definitions -- "
            "run add_monitor_block.py"
        )

    return out, found, dates


def compare_app_keys(found, dart_path):
    """What the app thinks the template has, against what it has."""
    with open(dart_path, encoding="utf-8") as handle:
        text = handle.read()

    # Doc comments first. The comment at the top of that file carries the
    # command that regenerates it, and scraping quoted words out of that picked
    # up PY, utf8 and ignore as though they were placeholders.
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("///")
    )
    listed = set(re.findall(r"'([A-Za-z0-9_]+)'", code))
    template = {k for k in found if "." not in k} - {"line", "f"}

    missing = sorted(listed - template)
    extra = sorted(template - listed)

    if not missing and not extra:
        print("\nThe app's key list matches the template.")
        return True

    print(f"\nThe app's key list is out by {len(missing) + len(extra)} keys.")
    if missing:
        print(f"  {len(missing)} the app lists and the template does not have:")
        for k in missing[:12]:
            print(f"    {k}")
        if len(missing) > 12:
            print(f"    ... and {len(missing) - 12} more")
    if extra:
        print(f"  {len(extra)} the template has and the app does not list:")
        for k in extra[:12]:
            print(f"    {k}")
        if len(extra) > 12:
            print(f"    ... and {len(extra) - 12} more")
    print("\n  Regenerate lib/Data/owner_template_keys.dart -- the command is")
    print("  in the comment at the top of that file, and in the README.")
    return False


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        sys.exit(1)

    plain = read(sys.argv[1])
    found, keys_found, dates = problems(plain)

    if found:
        print(f"{sys.argv[1]} is not ready:\n")
        for problem in found:
            print(f"  - {problem}")
        print(
            "\nOrder: add_date_column.py, add_monitor_block.py, "
            "add_finding_photos.py."
        )
        sys.exit(1)

    print(f"{sys.argv[1]}: six findings blocks, photographs, {dates} dates.")

    if len(sys.argv) == 3 and not compare_app_keys(keys_found, sys.argv[2]):
        sys.exit(1)


if __name__ == "__main__":
    main()
