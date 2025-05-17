import os
from flask import Flask
from flask_cors import CORS
from api.chat import chat_blueprint
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()
ORIGINS = os.getenv('ORIGINS')
# Permitir solicitudes solo desde http://127.0.0.1:5500
CORS(app, resources={r"/api/*": {"origins": ORIGINS}})

# Registrar el blueprint del chat
app.register_blueprint(chat_blueprint, url_prefix='/api')

# Verifica las rutas registradas
print("Rutas registradas:")
for rule in app.url_map.iter_rules():
    print(f"Endpoint: {rule.endpoint} - URL: {rule}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # 🔧 cambio importante para Render
    app.run(host='0.0.0.0', port=port, debug=True)
