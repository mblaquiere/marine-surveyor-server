import json
import os
import io
import base64
import re
import tempfile
import subprocess
from flask import Flask, request, send_file
from docxtpl import DocxTemplate, InlineImage
from jinja2 import Environment
from docx.shared import Inches
from PIL import Image, ImageOps

app = Flask(__name__)

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

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                upright.save(tmp, format='JPEG', quality=85)
                return tmp.name
    except Exception as e:
        print(f"[⚠️] Image prepare failed for {path}: {e}", flush=True)
    return path


@app.route('/generate_report', methods=['POST'])
def generate_report():
    form = request.form.to_dict()
    files = request.files

    for name, file in files.items():
        print(f"[📥] Received uploaded file: {name}, filename={file.filename}, content_type={file.content_type}", flush=True)

    requested_format = form.get("format", "docx").lower()
    template_name = form.get("template", "survey_template_01a.docx")

    doc = DocxTemplate(template_name)

    # Base context: all non-file, non-photo-path fields
    context = {
        k: v for k, v in form.items()
        if not k.endswith('_photo') and not k.endswith('_photo_path') and not k.endswith('_base64') and k != 'template' and k != 'format'
    }

    # A finding's photograph, which the severity loops further down place
    # beside its text. Named <severity>_finding_<n>_photo.
    FINDING_PHOTO = re.compile(r"^(aa|a|b|c|monitor|ftr)_finding_\d+_photo")

    # Resolve image keys from any of *_photo, *_photo_path, *_base64
    image_keys = set()
    for key in list(form.keys()) + list(files.keys()):
        # Findings photographs are handled with their findings, not as
        # standalone placeholders. Without this they would be decoded and
        # resized twice, and land in the context under a name no template has.
        if FINDING_PHOTO.match(key):
            continue
        if key.endswith('_photo') or key.endswith('_photo_path') or key.endswith('_base64'):
            base = key.replace('_photo', '').replace('_photo_path', '').replace('_base64', '')
            image_keys.add(base)

    print(f"[🔎] Found image_keys: {image_keys}", flush=True)

    # Attach images into context
    for base in image_keys:
        field_name = base + '_photo'
        print(f"[🔄] Evaluating field: {field_name}", flush=True)

        if field_name in files:
            print(f"[🖼️] Using uploaded file for {field_name}", flush=True)
            file = files[field_name]
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                file.save(tmp.name)
                temp_path = tmp.name

            temp_path = prepare_image(temp_path)
            context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))

        elif base + '_photo_path' in form:
            path = form[base + '_photo_path']
            print(f"[📄] Using on-disk path for {field_name}: {path}", flush=True)
            if os.path.exists(path):
                path = prepare_image(path)
                context[field_name] = InlineImage(doc, path, width=Inches(4.5))
            else:
                print(f"[⚠️] Provided path does not exist: {path}", flush=True)

        elif base + '_base64' in form:
            print(f"[🧬] Decoding base64 for {field_name}", flush=True)
            try:
                data = base64.b64decode(form[base + '_base64'])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(data)
                    temp_path = tmp.name
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
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=os.path.splitext(uploaded.filename)[1] or ".jpg",
                ) as tmp:
                    uploaded.save(tmp.name)
                    ready = prepare_image(tmp.name)
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
                    text=True
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


@app.route('/check_tectonic')
def check_tectonic():
    try:
        result = subprocess.run(["tectonic", "--version"], capture_output=True, text=True)
        return {"output": result.stdout.strip()}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
