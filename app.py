import json
import os
import base64
import tempfile
import subprocess
from flask import Flask, request, send_file
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Inches
from PIL import Image

app = Flask(__name__)


def resize_image_if_needed(path, max_width=1200):
    try:
        with Image.open(path) as img:
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                resized = img.resize((max_width, new_height), Image.LANCZOS)

                temp_path = path + "_resized.jpg"
                resized.save(temp_path, format='JPEG', quality=85)
                print(f"[🖼️] Resized {path} → {temp_path} ({max_width}x{new_height})", flush=True)
                return temp_path
    except Exception as e:
        print(f"[⚠️] Error resizing image {path}: {e}", flush=True)
    return path


@app.route('/generate_report', methods=['POST'])
def generate_report():
    form = request.form.to_dict()
    files = request.files
    for name, file in files.items():
        print(f"[📥] Received uploaded file: {name}, filename={file.filename}, content_type={file.content_type}", flush=True)

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
            print(f"[📁] Found file in request.files: {field_name}", flush=True)
            try:
                image = files[field_name]
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
                    image.save(temp_file)
                    temp_path = resize_image_if_needed(temp_file.name)
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
                print(f"[📎] Uploaded file used for {field_name} → {temp_path}", flush=True)
                continue
            except Exception as e:
                print(f"[⚠️] Error using uploaded file {field_name}: {e}", flush=True)

        if f'{base}_base64' in form:
            try:
                image_bytes = base64.b64decode(form[f'{base}_base64'])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
                    temp_file.write(image_bytes)
                    temp_path = resize_image_if_needed(temp_file.name)
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
                print(f"[🖼️] {base}_base64 → inserted → {temp_path}", flush=True)
                continue
            except Exception as e:
                print(f"[⚠️] Error decoding base64 {base}: {e}", flush=True)

        if f'{base}_photo_path' in form:
            path = form[f'{base}_photo_path']
            if os.path.exists(path):
                temp_path = resize_image_if_needed(path)
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
                print(f"[📷] {base}_photo_path used → {temp_path}", flush=True)

    doc.render(context)

    with tempfile.TemporaryDirectory() as temp_dir:
        docx_path = os.path.join(temp_dir, "report.docx")
        doc.save(docx_path)

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

                if result.returncode != 0 or not os.path.exists(pdf_path):
                    raise Exception("LibreOffice failed to produce PDF")

                return send_file(
                    pdf_path,
                    as_attachment=True,
                    download_name="SurveyReport.pdf",
                    mimetype="application/pdf"
                )

            except Exception as e:
                return {
                    "error": "PDF conversion failed",
                    "message": str(e)
                }, 500

        return send_file(
            docx_path,
            as_attachment=True,
            download_name="SurveyReport.docx",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )


@app.route('/check_pandoc')
def check_pandoc():
    try:
        result = subprocess.run(["pandoc", "--version"], capture_output=True, text=True)
        return {"output": result.stdout.strip()}
    except Exception as e:
        return {"error": str(e)}


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
