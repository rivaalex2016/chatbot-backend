import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

# Crear la app de Flask
app = Flask(__name__)

# Cargar variables del entorno desde el archivo .env
load_dotenv()

# Permitir solicitudes CORS desde cualquier origen
# También puedes restringir a dominios específicos si deseas
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Registrar el blueprint del chatbot en /api/chat
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Ruta opcional para subir archivos desde frontend
@app.route('/api/upload', methods=['POST'])
def upload_file():
    archivo = request.files.get("file")
    if archivo:
        ruta = os.path.join("documents", archivo.filename)
        os.makedirs("documents", exist_ok=True)
        archivo.save(ruta)
        return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200
    return jsonify({"error": "No se recibió ningún archivo"}), 400

# Mostrar todas las rutas activas (útil para depurar)
print("🔍 Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"📍 {rule.endpoint} --> {rule}")

# Iniciar servidor localmente o en Render (usa PORT del entorno)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

    
