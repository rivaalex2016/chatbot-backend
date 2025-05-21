import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

# Inicializar la app
app = Flask(__name__)

# Cargar variables del entorno
load_dotenv()

# Configurar CORS (origen: tu frontend en Netlify)
CORS(app, resources={r"/api/*": {"origins": "https://cozy-moonbeam-d256ea.netlify.app"}})

# Registrar el blueprint del chatbot
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Ruta para subir archivos
@app.route('/api/upload', methods=['POST'])
def upload_file():
    file = request.files.get("file")
    user_id = request.form.get("user_id", "default_user")

    if not file:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    try:
        filename = f"{user_id}.pdf"
        save_path = os.path.join("api", "contextos", filename)

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)

        return jsonify({"response": f"Archivo {file.filename} recibido correctamente"}), 200

    except Exception as e:
        return jsonify({"error": f"Error al guardar el archivo: {str(e)}"}), 500

# Verificar rutas cargadas (opcional para debug)
print("🔍 Rutas activas:")
for rule in app.url_map.iter_rules():
    print(f"📌 {rule.endpoint} --> {rule}")

# Iniciar la app (local o Render)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
