import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

# Cargar variables del entorno
load_dotenv()

# Crear la app Flask
app = Flask(__name__, static_folder='static')

# Configurar CORS para dominios específicos
CORS(app, resources={r"/api/*": {
    "origins": [
        "https://innovug.ug.edu.ec",  # WordPress oficial
        "http://127.0.0.1:5500",      # localhost pruebas
        "http://localhost:5500"     
    ]
}})

# Registrar el blueprint para rutas de /api/chat
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Ruta para subir archivos PDF, CSV, XLSX desde frontend
@app.route('/api/upload', methods=['POST'])
def upload_file():
    archivo = request.files.get("file")
    if archivo:
        ruta = os.path.join("documents", archivo.filename)
        os.makedirs("documents", exist_ok=True)
        archivo.save(ruta)
        return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200
    return jsonify({"error": "No se recibió ningún archivo"}), 400

# Ruta principal: sirve el index.html
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# Mostrar rutas activas para depuración
print("🔍 Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"📍 {rule.endpoint} --> {rule}")

# Iniciar servidor Flask (Render detecta el puerto desde la variable de entorno PORT)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
