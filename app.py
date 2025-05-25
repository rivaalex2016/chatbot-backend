import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

# Crear la app de Flask
app = Flask(__name__, static_folder='static')

# Cargar variables del entorno desde el archivo .env
load_dotenv()

# CORS: permitir solicitudes desde dominios específicos (WordPress y localhost para pruebas)
CORS(app, resources={r"/api/*": {
    "origins": [
        "https://innovug.ug.edu.ec",  # WordPress oficial
        "http://127.0.0.1:5500",      # localhost pruebas
        "http://localhost:5500"
    ]
}})

# Registrar el blueprint del chatbot
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Ruta para recibir archivos desde el frontend
@app.route('/api/upload', methods=['POST'])
def upload_file():
    archivo = request.files.get("file")
    if archivo:
        ruta = os.path.join("documents", archivo.filename)
        os.makedirs("documents", exist_ok=True)
        archivo.save(ruta)
        return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200
    return jsonify({"error": "No se recibió ningún archivo"}), 400

# Ruta para servir el index.html desde la carpeta static/
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# Mostrar rutas registradas para depuración
print("🔍 Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"📍 {rule.endpoint} --> {rule}")

# Ejecutar la aplicación localmente o en Render
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Render inyecta el puerto en PORT
    app.run(host='0.0.0.0', port=port, debug=True)



