import json
import os
import base64
import tempfile
import subprocess
from flask import Flask, request, send_file
from docxtpl import DocxTemplate, InlineImage
from jinja2 import Environment
from docx.shared import Inches
from PIL import Image

app = Flask(__name__)
# ---- Custom filters ----
def nl2br(value):
    """Convert newlines into Word line breaks for docxtpl."""
    if not value:
        return ""
    return value.replace("\n", "<w:br/>")
# ------------------------


def resize_image_if_needed(path, max_width=1200):
    try:
        with Image.open(path) as img:
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                resized = img.resize((max_width, new_height), Image.LANCZOS)

                temp_path = path + "_resized.jpg"
                resized.save(temp_path, format='JPEG', quality=85)
                return temp_path
    except Exception as e:
        print(f"[⚠️] Image resize failed for {path}: {e}", flush=True)
    return path


@app.route('/generate_report', methods=['POST'])
def generate_report():
    form = request.form.to_dict()
    files = request.files
    for name, file in files.items():
        print(f"[📥] Received uploaded file: {name}, filenam...={file.filename}, content_type={file.content_type}", flush=True)

    requested_format = form.get("format", "docx").lower()
    doc = DocxTemplate('survey_template_01a.docx')

    context = {
        k: v for k, v in form.items()
        if not k.endswith('_photo') and not k.endswith('_photo_path') and not k.endswith('_base64')
    }

    image_keys = set()
    for key in list(form.keys()) + list(files.keys()):
        if key.endswith('_photo') or key.endswith('_photo_path') or key.endswith('_base64'):
            image_keys.add(key.replace('_photo', '').replace('_photo_path', '').replace('_base64', ''))

    print(f"[🔎] Found image_keys: {image_keys}", flush=True)

    for base in image_keys:
        field_name = base + '_photo'
        print(f"[🔄] Evaluating field: {field_name}", flush=True)

        if field_name in files:
            print(f"[🖼️] Using uploaded file for {field_name}", flush=True)
            file = files[field_name]
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                file.save(tmp.name)
                temp_path = tmp.name

            temp_path = resize_image_if_needed(temp_path)
            context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))

        elif base + '_photo_path' in form:
            path = form[base + '_photo_path']
            print(f"[📄] Using on-disk path for {field_name}: {path}", flush=True)
            if os.path.exists(path):
                path = resize_image_if_needed(path)
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
                temp_path = resize_image_if_needed(temp_path)
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
            except Exception as e:
                print(f"[⚠️] Failed to decode base64 for {field_name}: {e}", flush=True)

    # Attach Jinja environment with our custom nl2br filter
    env = Environment(autoescape=True)
    env.filters["nl2br"] = nl2br
    doc.render(context, jinja_env=env)

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

                print(f"[✅] PDF generated: {pdf_path}", flush=True)
                return send_file(pdf_path, as_attachment=True, download_name="report.pdf")
            except Exception as e:
                print(f"[❌] PDF generation failed: {e}. Falling back to DOCX.", flush=True)
                return send_file(docx_path, as_attachment=True, download_name="report.docx")

        return send_file(docx_path, as_attachment=True, download_name="report.docx")


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
