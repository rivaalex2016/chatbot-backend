# app.py
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()

CORS(app, resources={r"/api/*": {
    "origins": "https://cozy-moonbeam-d256ea.netlify.app"
}})

app.register_blueprint(chat_blueprint, url_prefix="/api")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/api/upload", methods=["POST"])
def upload_file():
    archivo = request.files.get("file")
    user_id = request.form.get("user_id")

    if not archivo or not user_id:
        return jsonify({"error": "Archivo o user_id faltante"}), 400

    ext = os.path.splitext(archivo.filename)[-1]
    nombre = f"{user_id}_{archivo.filename}"
    path = os.path.join(UPLOAD_DIR, nombre)
    archivo.save(path)

    return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

