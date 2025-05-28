import json
import os
import base64
import tempfile
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
    # Get JSON data from the request
    data = request.json

    # 🔍 Diagnostic check for local photo path existence
    for key, path in data.items():
        if key.endswith('_photo_path'):
            print(f"[📸] {key} → {path} → Exists: {os.path.exists(path)}", flush=True)

    # Load the DOCX template
    doc = DocxTemplate('survey_template_01a.docx')

    # Start the template context with regular text fields only
    context = {k: v for k, v in data.items() if not k.endswith('_photo_path') and not k.endswith('_base64')}

    # Add photo fields from local paths like "engine_photo_path"
    for key, path in data.items():
        if key.endswith('_photo_path') and isinstance(path, str) and os.path.exists(path):
            field_name = key.replace('_photo_path', '')
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

                field_name = key.replace('_base64', '')
                context[field_name] = InlineImage(doc, temp_path, width=Inches(4.5))
                print(f"[🖼️] Decoded and inserted {key} → {temp_path}", flush=True)
            except Exception as e:
                print(f"[⚠️] Error decoding image {key}: {e}", flush=True)

    # Render the template with both text and images
    doc.render(context)

    # Save the generated file in memory
    byte_io = BytesIO()
    doc.save(byte_io)
    byte_io.seek(0)

    # Return the generated DOCX file
    return send_file(
        byte_io,
        as_attachment=True,
        download_name="SurveyReport.docx",
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
