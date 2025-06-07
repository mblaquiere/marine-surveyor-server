import json
import os
import base64
import tempfile
import subprocess
from flask import Flask, request, send_file
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Inches
from io import BytesIO
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
    data = request.json
    requested_format = data.get("format", "docx").lower()

    # 🔍 Diagnostic check for local photo path existence
    for key, path in data.items():
        if key.endswith('_photo_path'):
            print(f"[📸] {key} → {path} → Exists: {os.path.exists(path)}", flush=True)

    # Load the DOCX template
    doc = DocxTemplate('survey_template_01a.docx')

    # Start the template context with regular text fields only
    context = {
        k: v for k, v in data.items()
        if not k.endswith('_photo_path') and not k.endswith('_base64')
    }

    # Add photo fields from local paths like "engine_photo_path"
    for key, path in data.items():
        if key.endswith('_photo_path') and isinstance(path, str) and os.path.exists(path):
            field_name = key.replace('_photo_path', '_photo')  # ✅ updated
            resized_path = resize_image_if_needed(path)
            context[field_name] = InlineImage(doc, resized_path, width=Inches(4.5))

    # Add photo fields from Base64-encoded strings
    for key, b64string in data.items():
        if key.endswith('_base64') and isinstance(b64string, str):
            try:
                image_bytes = base64.b64decode(b64string)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
                    temp_file.write(image_bytes)
                    temp_path = temp_file.name

                field_name = key.replace('_base64', '_photo')  # ✅ updated
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
                print(f"[🖼️] Decoded and inserted {key} → {temp_path}", flush=True)
            except Exception as e:
                print(f"[⚠️] Error decoding image {key}: {e}", flush=True)

    # Render the template with both text and images
    doc.render(context)

    with tempfile.TemporaryDirectory() as temp_dir:
        docx_path = os.path.join(temp_dir, "report.docx")
        doc.save(docx_path)

        if requested_format == "pdf":
            pdf_path = os.path.join(temp_dir, "report.pdf")
            try:
subprocess.run(
    ["pandoc", docx_path, "-o", pdf_path],
    check=True
)

                return send_file(
                    pdf_path,
                    as_attachment=True,
                    download_name="SurveyReport.pdf",
                    mimetype="application/pdf"
                )
            except subprocess.CalledProcessError as e:
                return {"error": "Pandoc conversion failed", "details": str(e)}, 500
        else:
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
