import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
from api.chat import chat_blueprint

app = Flask(__name__)

# Cargar variables de entorno desde .env
load_dotenv()

# CORS: permitir peticiones desde tu frontend en Netlify
CORS(app, resources={r"/api/*": {
    "origins": "https://cozy-moonbeam-d256ea.netlify.app"
}})

# Registrar el blueprint del chatbot (define /api/chat y /api/upload)
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Mostrar rutas registradas (opcional, para depuración)
print("🔍 Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"📍 {rule.endpoint} --> {rule}")

# Iniciar el servidor (Render asigna PORT automáticamente)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Usado en Render o local
    app.run(host='0.0.0.0', port=port, debug=True)

