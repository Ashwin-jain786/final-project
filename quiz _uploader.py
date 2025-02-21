from flask import Flask, request, jsonify, send_file
import os

app = Flask(__name__)

# Replace with the actual path to your PDF directory
PDF_DIRECTORY = 'path/to/your/pdfs'  #<----- CRITICAL: programmer provided directory

# Programmer provides this mapping (example) - crucial for the backend
QUIZ_MAPPING = {
    "Class 1": {
        "Math": "class1_math_quiz.pdf",
        "Science": "class1_science_quiz.pdf"
    },
    "Class 2": {
        "Math": "class2_math_quiz.pdf",
        "Science": "class2_science_quiz.pdf"
    }
}

@app.route('/get_quiz_pdf', methods=['POST'])
def get_quiz_pdf():
    data = request.get_json()
    selected_class = data.get('class')
    selected_subject = data.get('subject')

    # Validation (Important!)
    if not selected_class or not selected_subject:
        return jsonify({"error": "Missing class or subject"}), 400  # Bad Request

    #Check if the combo exists in the mapping
    if selected_class not in QUIZ_MAPPING or selected_subject not in QUIZ_MAPPING[selected_class]:
        return jsonify({"error": "Quiz not found for the selected class and subject."}), 404


    filename = QUIZ_MAPPING[selected_class][selected_subject]

    pdf_path = os.path.join(PDF_DIRECTORY, filename)

    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")  # Log this for debugging
        return jsonify({"error": "Quiz file not found on the server."}), 500 #Server Error

    try:
        return send_file(pdf_path, as_attachment=True, download_name=filename) #Added download name
    except Exception as e:
        print(f"Error sending file: {e}") # Log this for debugging
        return jsonify({"error": "Error sending the file."}), 500

if __name__ == '__main__':
    app.run(debug=True)