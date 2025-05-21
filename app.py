import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from api.chat import chat_blueprint, extract_text_from_pdf
from dotenv import load_dotenv

# Crear aplicación Flask
app = Flask(__name__)

# Cargar variables de entorno desde .env
load_dotenv()

# Configurar CORS para permitir peticiones desde Netlify
CORS(app, resources={r"/api/*": {
    "origins": "https://cozy-moonbeam-d256ea.netlify.app"
}})

# Registrar blueprint del chatbot
app.register_blueprint(chat_blueprint, url_prefix='/api')

# 📌 Endpoint para subir archivos PDF y guardar su contenido
@app.route('/api/upload', methods=['POST'])
def upload_file():
    archivo = request.files.get("file")
    user_id = request.form.get("user_id", "default_user")

    if archivo:
        # Guardar archivo PDF en carpeta /documents
        ruta_pdf = os.path.join("documents", archivo.filename)
        archivo.save(ruta_pdf)

        # Extraer texto del PDF y guardar en /api/contextos/{user_id}.txt
        try:
            texto_extraido = extract_text_from_pdf(ruta_pdf)
            ruta_contexto = os.path.join("api", "contextos", f"{user_id}.txt")
            with open(ruta_contexto, "w", encoding="utf-8") as f:
                f.write(texto_extraido)

            return jsonify({"response": f"Archivo {archivo.filename} recibido correctamente"}), 200
        except Exception as e:
            return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500

    return jsonify({"error": "No se recibió ningún archivo"}), 400

# ✅ Imprimir rutas registradas (opcional para debug)
print("🔍 Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"📍 {rule.endpoint} --> {rule}")

# 🔁 Ejecutar app
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Usado por Render
    app.run(host='0.0.0.0', port=port, debug=True)
