import json
import os
import io
import base64
import hmac
import re
import tempfile
import subprocess
from flask import Flask, g, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from docxtpl import DocxTemplate, InlineImage
from jinja2 import Environment
from docx.shared import Inches
from PIL import Image, ImageOps

app = Flask(__name__)

# A report carries every photograph from the walk. The app shrinks each one
# before sending, so a full survey runs to ten or fifteen megabytes, but nothing
# stopped a far bigger one arriving and being read whole into the memory of a
# 512MB instance. Over this it now fails as a plain 413, which the app can put
# into words, rather than as an instance that runs out of memory and answers
# 502, which it cannot.
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def _report_too_large(_error):
    print("[📦] Refused a report over the size limit", flush=True)
    return {"error": "That report is too large to build."}, 413


def _temp_file(suffix):
    """A temporary file this request will clean up.

    Every photograph used to make one or two of these with delete=False and
    nothing ever removed them. Render recycles containers often enough that it
    never showed, which is exactly why it would have shown first on a container
    that stayed up.
    """
    handle, path = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    paths = getattr(g, '_temp_paths', None)
    if paths is None:
        paths = []
        g._temp_paths = paths
    paths.append(path)
    return path


@app.teardown_request
def _remove_temp_files(_error):
    for path in getattr(g, '_temp_paths', []):
        try:
            os.remove(path)
        except OSError as e:
            print(f"[⚠️] Could not remove {path}: {e}", flush=True)

# Shared secret with the app, sent as the X-Report-Key header on every
# /generate_report call. Set on Render's dashboard, not committed here -- see
# render.yaml. A report carries a name, an address, a boat's registration
# numbers and every photo taken of it, and until this existed the endpoint
# handed all of it to anyone who asked, with nothing to check who was asking.
REPORT_API_KEY = os.environ.get('REPORT_API_KEY')

# The only two templates this server has. `template` arrives on the form, and
# without this it went straight into DocxTemplate with nothing checked -- an
# unvalidated path, behind a key that ships inside every copy of the app. The
# key is a shared secret at best; this is the part that does not depend on it.
TEMPLATES = (
    'survey_template_01a.docx',
    'survey_template_owner.docx',
)


def _report_key_is_valid(provided):
    """True only if the server has a key configured and it matches.

    No key configured is not "open" -- it means every request gets refused
    until one is set. A check that quietly does nothing when misconfigured
    is worse than the check not existing, because it looks like protection.
    """
    if not REPORT_API_KEY or not provided:
        return False
    return hmac.compare_digest(provided, REPORT_API_KEY)

# ---- Custom filters ----
def nl2br(value):
    """Convert newlines into Word line breaks for docxtpl (kept for optional use)."""
    if value is None:
        return ""
    from docxtpl import RichText  # local import to avoid issues on some envs
    text = str(value)
    parts = text.split('\n')
    rt = RichText()
    for i, part in enumerate(parts):
        rt.add(part)
        if i < len(parts) - 1:
            rt.add('\n')  # real Word line break
    return rt
# --------------------------

def _split_to_lines(value):
    """
    Split a newline-separated string into a clean list of non-empty lines.
    Falls back to ['None Observed'] if there are no lines.
    """
    text = "" if value is None else str(value)
    raw_lines = text.split('\n')
    lines = [ln.strip() for ln in raw_lines if ln.strip()]
    return lines if lines else ["None Observed"]



def prepare_image(path, max_width=1200):
    """
    Turn a photo the right way up, and shrink it if it is wider than the page
    can use. Returns a path to use in the document -- the original if nothing
    needed doing, otherwise a new temporary file.

    Phones almost never rotate the pixels when you turn the camera. They write
    the pixels the way the sensor saw them and add an EXIF orientation tag
    saying which way is up. Word ignores that tag, so a photo taken in portrait
    lands on the page on its side. exif_transpose rotates the pixels for real
    and drops the tag.
    """
    try:
        with Image.open(path) as img:
            # Tag 274 is Orientation. 1 means "already upright"; missing means
            # the same. Ask before transposing, because exif_transpose hands
            # back a new object either way and cannot be used as the answer.
            orientation = (img.getexif() or {}).get(274, 1)
            rotated = orientation not in (1, None)
            upright = ImageOps.exif_transpose(img) if rotated else img

            if upright.width > max_width:
                ratio = max_width / upright.width
                new_height = int(upright.height * ratio)
                upright = upright.resize((max_width, new_height), Image.LANCZOS)
            elif not rotated:
                return path

            if upright.mode not in ("RGB", "L"):
                upright = upright.convert("RGB")

            prepared = _temp_file(".jpg")
            upright.save(prepared, format='JPEG', quality=85)
            return prepared
    except Exception as e:
        print(f"[⚠️] Image prepare failed for {path}: {e}", flush=True)
    return path


@app.route('/generate_report', methods=['POST'])
def generate_report():
    if not _report_key_is_valid(request.headers.get('X-Report-Key')):
        if not REPORT_API_KEY:
            print(
                "[🔒] REPORT_API_KEY is not set on this server -- refusing "
                "every request until it is. Set it on Render's dashboard.",
                flush=True,
            )
            return {"error": "Server is not configured to accept report requests."}, 500
        print("[🔒] Rejected /generate_report: missing or wrong X-Report-Key", flush=True)
        return {"error": "Missing or invalid X-Report-Key."}, 401

    form = request.form.to_dict()
    files = request.files

    for name, file in files.items():
        print(f"[📥] Received uploaded file: {name}, filename={file.filename}, content_type={file.content_type}", flush=True)

    requested_format = form.get("format", "docx").lower()
    template_name = form.get("template", "survey_template_01a.docx")
    if template_name not in TEMPLATES:
        print(f"[🚫] Refused unknown template: {template_name!r}", flush=True)
        return {"error": "Unknown template."}, 400

    doc = DocxTemplate(template_name)

    # Base context: all non-file, non-photo-path fields
    context = {
        k: v for k, v in form.items()
        if not k.endswith('_photo') and not k.endswith('_photo_path') and not k.endswith('_base64') and k != 'template' and k != 'format'
    }

    # A finding's photograph, which the severity loops further down place
    # beside its text. Named <severity>_finding_<n>_photo.
    FINDING_PHOTO = re.compile(r"^(aa|a|b|c|monitor|ftr)_finding_\d+_photo")

    # Resolve image keys from either of *_photo, *_base64
    image_keys = set()
    for key in list(form.keys()) + list(files.keys()):
        # Findings photographs are handled with their findings, not as
        # standalone placeholders. Without this they would be decoded and
        # resized twice, and land in the context under a name no template has.
        if FINDING_PHOTO.match(key):
            continue
        # No _photo_path here any more. It named a file for the server to read
        # off its own disk, and the app never sends one -- it strips those and
        # re-sends each as an uploaded file. So the only caller it could ever
        # have served was one poking at the endpoint.
        if key.endswith('_photo') or key.endswith('_base64'):
            base = key.replace('_photo', '').replace('_base64', '')
            image_keys.add(base)

    print(f"[🔎] Found image_keys: {image_keys}", flush=True)

    # Attach images into context
    for base in image_keys:
        field_name = base + '_photo'
        print(f"[🔄] Evaluating field: {field_name}", flush=True)

        if field_name in files:
            print(f"[🖼️] Using uploaded file for {field_name}", flush=True)
            file = files[field_name]
            temp_path = _temp_file(os.path.splitext(file.filename)[1])
            file.save(temp_path)

            temp_path = prepare_image(temp_path)
            context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))

        elif base + '_base64' in form:
            print(f"[🧬] Decoding base64 for {field_name}", flush=True)
            try:
                data = base64.b64decode(form[base + '_base64'])
                temp_path = _temp_file(".jpg")
                with open(temp_path, 'wb') as handle:
                    handle.write(data)
                temp_path = prepare_image(temp_path)
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
            except Exception as e:
                print(f"[⚠️] Failed to decode base64 for {field_name}: {e}", flush=True)

    # Build arrays for severity loops in the template.
    #
    # "monitor" is not a professional survey grade. It means watch this, which
    # is what an owner writes down most of the time -- 43 of the 56 findings on
    # SV Liquid are monitor. Without it the report omits three quarters of what
    # a walk turned up. Harmless on the older template, which has no block to
    # loop over it; the owner template has one.
    for sev in ("aa", "a", "b", "c", "monitor", "ftr"):
        key = f"{sev}_findings"
        lines = _split_to_lines(context.get(key))
        context[f"{sev}_findings_list"] = lines

        # The same findings, each able to carry a photograph.
        #
        # Two shapes rather than one because the older professional template
        # loops over plain strings and still has to work. The owner template
        # loops over these instead.
        #
        # A finding without a photograph is an assertion; with one it is
        # evidence. That is the whole reason for this.
        items = []
        for n, text in enumerate(lines, start=1):
            photo = ""
            field = f"{sev}_finding_{n}_photo"
            if field in files:
                uploaded = files[field]
                saved = _temp_file(
                    os.path.splitext(uploaded.filename)[1] or ".jpg"
                )
                uploaded.save(saved)
                ready = prepare_image(saved)
                # Narrower than the walk-round photographs at 4.5". A finding
                # photograph is a detail shot sitting under one line of text,
                # not a plate.
                photo = InlineImage(doc, ready, width=Inches(3.0))
                print(f"[📸] {field} attached", flush=True)
            items.append({"text": text, "photo": photo})
        context[f"{sev}_findings_items"] = items

    # Debug: verify counts incl. FTR
    print("[lists] aa:", len(context.get("aa_findings_list", [])),
          "a:", len(context.get("a_findings_list", [])),
          "monitor:", len(context.get("monitor_findings_list", [])),
          "b:", len(context.get("b_findings_list", [])),
          "c:", len(context.get("c_findings_list", [])),
          "ftr:", len(context.get("ftr_findings_list", [])),
          flush=True)


    # Jinja environment (nl2br available for other fields if you want)
    env = Environment(autoescape=True)
    env.filters["nl2br"] = nl2br

    # Render with context and custom env
    doc.render(context, jinja_env=env)

    # Save and optionally convert to PDF
    with tempfile.TemporaryDirectory() as temp_dir:
        docx_path = os.path.join(temp_dir, "report.docx")
        doc.save(docx_path)
        print(f"[💾] DOCX saved to: {docx_path}", flush=True)

        if requested_format == "pdf":
            pdf_path = os.path.join(temp_dir, "report.pdf")
            try:
                result = subprocess.run(
                    [
                        "libreoffice",
                        "--headless",
                        "--convert-to", "pdf",
                        "--outdir", temp_dir,
                        docx_path
                    ],
                    capture_output=True,
                    text=True,
                    # Without this a LibreOffice that hangs holds the worker
                    # until Render kills the whole instance. Two minutes is
                    # well past any real conversion.
                    timeout=120,
                )

                print("[📄] LibreOffice stdout:\n", result.stdout, flush=True)
                print("[⚠️] LibreOffice stderr:\n", result.stderr, flush=True)

                if result.returncode != 0:
                    raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

                if not os.path.exists(pdf_path):
                    raise FileNotFoundError(f"Expected PDF not found at {pdf_path}")

                # 🔐 Read into memory BEFORE leaving the temp_dir context
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                print(f"[✅] PDF generated: {pdf_path}", flush=True)
                return send_file(
                    io.BytesIO(pdf_bytes),
                    as_attachment=True,
                    download_name="report.pdf",
                    mimetype="application/pdf",
                )
            except Exception as e:
                print(f"[❌] PDF generation failed: {e}. Falling back to DOCX.", flush=True)
                # fall through to DOCX return below

        # Default/Docx return path (or PDF fallback)
        with open(docx_path, "rb") as f:
            docx_bytes = f.read()

        return send_file(
            io.BytesIO(docx_bytes),
            as_attachment=True,
            download_name="report.docx",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


@app.route('/health')
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    # Off unless asked for. Flask's debug mode opens the Werkzeug debugger --
    # a console that runs arbitrary Python -- to anyone who can trigger an
    # unhandled exception. Fine on a laptop, not fine on the internet. Set
    # FLASK_DEBUG=1 locally if you want it back.
    debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
