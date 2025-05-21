# ✅ app.py actualizado
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

app.register_blueprint(chat_blueprint, url_prefix='/api')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    archivo = request.files.get("file")
    user_id = request.form.get("user_id", "default_user")

    if archivo:
        nombre_archivo = f"{user_id}_{archivo.filename}"
        ruta = os.path.join("uploads", nombre_archivo)
        archivo.save(ruta)

        contexto_path = f"api/contextos/{user_id}.txt"
        with open(contexto_path, 'w') as f:
            f.write(nombre_archivo)

        return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200
    return jsonify({"error": "No se recibió ningún archivo"}), 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)