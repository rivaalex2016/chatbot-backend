import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

app = Flask(__name__)

# Cargar variables de entorno desde .env
load_dotenv()

# CORS: permitir peticiones desde tu frontend en Netlify
CORS(app, resources={r"/api/*": {
    "origins": "https://cozy-moonbeam-d256ea.netlify.app"
}})

# Registrar el blueprint del chatbot
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Endpoint opcional para subir archivos (si se usa desde frontend)
@app.route('/api/upload', methods=['POST'])
def upload_file():
    archivo = request.files.get("file")
    if archivo:
        ruta = os.path.join("documents", archivo.filename)
        archivo.save(ruta)
        return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200
    return jsonify({"error": "No se recibió ningún archivo"}), 400

# Mostrar las rutas registradas (útil para depuración)
print("🔍 Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"📍 {rule.endpoint} --> {rule}")

# Iniciar la app en Render o local
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Render usa este puerto dinámico
    app.run(host='0.0.0.0', port=port, debug=True)
