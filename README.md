# marine-surveyor-server

Renders survey reports. The app posts a bag of form fields and photographs to
`/generate_report`; this fills a Word template and sends the document back.

Two templates:

- `survey_template_01a.docx` — the professional one, with a surveyor's details.
- `survey_template_owner.docx` — an owner surveying their own boat. The app
  names this one, so an owner's report never lands on a surveyor's letterhead.

## Editing the owner template

The template is edited in Pages and exported to .docx. Pages does not know about
three things the template needs, and drops all three every time it writes the
file. So after every export, run the scripts in this order, then the check:

```
python3 scripts/add_date_column.py survey_template_owner.docx
python3 scripts/add_monitor_block.py survey_template_owner.docx
python3 scripts/add_finding_photos.py survey_template_owner.docx
python3 scripts/check_template.py survey_template_owner.docx
```

`add_date_column.py` gives each inventory table a third column for the date the
item was last looked at, and makes every table the same width.

`add_monitor_block.py` puts the Monitor Findings section back -- the heading,
the loop, and the line in Findings Definitions. Monitor is what an owner writes
down most of the time; 43 of the 56 findings on SV Liquid are monitor, so a
report without that section leaves out three quarters of the walk.

`add_finding_photos.py` lets each finding carry a photograph. Run it last: it
converts loops that are already there, so the monitor block has to exist first.

`check_template.py` reads the finished file and refuses it if any of that is
missing. Give it the app's key list as a second argument and it also says
whether the two have drifted:

```
python3 scripts/check_template.py survey_template_owner.docx \
    ../../marine_surveyor_app/lib/Data/owner_template_keys.dart
```

The three scripts each say what they changed and leave a `.bak` beside the file.
Each refuses to run twice on the same file, so running them again after a small
edit is safe.

**This is not advice, it is the thing that has already gone wrong.** The export
on 10 August brought in real new wording and silently took out 241 date
placeholders, every finding's photograph, and the whole Monitor section. Nothing
noticed for a week: the app's test compares the mapper against
`owner_template_keys.dart`, and that file had been generated before the export,
so it was testing the app against a template that no longer existed. Run the
check.

Then regenerate the app's key fixture — the app has a test that every field it
sends has somewhere to land, and it reads the list from the template:

```
python3 - <<'PY'
import zipfile, re
z = zipfile.ZipFile('survey_template_owner.docx')
xml = b''.join(z.read(n) for n in z.namelist() if n.endswith('.xml')).decode('utf8', 'ignore')
print(sorted(set(re.findall(r'\{\{\s*([A-Za-z0-9_]+)', re.sub(r'<[^>]+>', '', xml))) - {'line', 'f'}))
PY
```

Paste the result into `lib/data/owner_template_keys.dart` in the app. It moved
out of `test/` when the app itself started needing it — renaming an inventory
item warns you when the old name fills a report line, and that has to know which
placeholders the template really has.

## Photographs

Any field named `<name>_photo_path` is stripped by the app and re-sent as an
uploaded file called `<name>_photo`. Every photograph is turned the right way up
before it goes in — phones write the pixels sideways and add a tag saying which
way is up, and Word ignores the tag.

Walk-round photographs are 4.5" wide. A finding's photograph is 3.0", because it
sits under one line of text rather than on a page of its own.

## Findings

The app sends `aa_findings`, `b_findings` and so on as numbered lines in one
string. The server splits each into two shapes:

- `<sev>_findings_list` — plain strings, which the professional template loops
  over.
- `<sev>_findings_items` — the same lines as objects with a `text` and a
  `photo`, which the owner template loops over.

A photograph is matched to a line by number: `b_finding_2_photo` belongs to line
2 of `b_findings`. The app sorts the lines before numbering them, so the order
it sends the pictures in is the order they come out.

## Running it

```
pip install -r requirements.txt
python3 app.py
```

Note the pinned versions. docxtpl is held at 0.10.5, which leaves a tab
character alone rather than turning it into a Word tab — the template works
around that with columns rather than tab stops.
