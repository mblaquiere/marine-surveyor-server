import json
from flask import Flask, request, send_file
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Inches
import os
from io import BytesIO

app = Flask(__name__)

@app.route('/generate_report', methods=['POST'])
def generate_report():
    # Get JSON data from the request
    data = request.json

    # Load the DOCX template
    doc = DocxTemplate('survey_template_with_photos.docx')

    # Start the template context with regular text fields only
    context = {k: v for k, v in data.items() if not k.endswith('_photo_path')}

    # Add photo fields from keys like "engine_photo_path"
    for key, path in data.items():
        if key.endswith('_photo_path') and isinstance(path, str) and os.path.exists(path):
            field_name = key.replace('_photo_path', '')
            context[field_name] = InlineImage(doc, path, width=Inches(4.5))

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
