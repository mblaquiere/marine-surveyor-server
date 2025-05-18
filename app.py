import json
from flask import Flask, request, send_file
from docxtpl import DocxTemplate
import os
from io import BytesIO

app = Flask(__name__)

@app.route('/generate_report', methods=['POST'])
def generate_report():
    # Get JSON data from the request
    data = request.json

    # Load the template
    doc = DocxTemplate('survey_template_01a.docx')

    # Render the data into the template
    doc.render(data)

    # Save the generated file in memory
    byte_io = BytesIO()
    doc.save(byte_io)
    byte_io.seek(0)

    # Return the generated DOCX file
    return send_file(byte_io, as_attachment=True, download_name="SurveyReport.docx", mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)


