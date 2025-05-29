import os
import re
import logging
import pdfplumber
import openai
import psycopg2
import pandas as pd
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
from difflib import SequenceMatcher
from flask import Blueprint, request, jsonify
from openai.error import RateLimitError

load_dotenv()
MODEL = os.getenv("MODEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

user_contexts = {}
MAX_CONTEXT_LENGTH = 20

REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')
REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

# ========== CHAT HISTORY ==========
def guardar_mensaje(identity, role, content):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_history (identity, role, content, timestamp) VALUES (%s, %s, %s, %s)",
            (identity, role, content, datetime.now())
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando mensaje en DB: {e}")

def cargar_historial_por_identity(identity):
    historial = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT role, content FROM chat_history WHERE identity = %s ORDER BY timestamp ASC", (identity,))
        for row in cur.fetchall():
            historial.append({"role": row[0], "content": row[1]})
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error cargando historial desde DB: {e}")
    return historial

# ========== OPENAI ==========
def openai_IA(mensajes, model=MODEL, temperature=0.7):
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=mensajes,
            temperature=temperature,
        )
        return response.choices[0].message["content"]
    except RateLimitError:
        return "Error: Token de OpenAI insuficiente."
    except Exception as e:
        logging.error(f"OpenAI Error: {e}")
        return "Error procesando la solicitud."

# ========== PDF PROCESSING ==========
def extract_text_from_pdf(file) -> str:
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def extraer_datos_pdf(texto):
    campos = {
        'first_name': r'Nombres:\s*(.+)',
        'last_name': r'Apellidos:\s*(.+)',
        'faculty': r'Facultad:\s*(.+)',
        'career': r'Carrera:\s*(.+)',
        'phone': r'Teléfono:\s*(.+)',
        'email': r'Correo Electrónico:\s*(.+)',
        'semester': r'Semestre que Cursa:\s*(.+)',
        'area': r'Área\s*(.+?)\n',
        'product_description': r'Descripción del producto/servicio\s*(.+?)\n',
        'problem_identification': r'Identificación del problema que resuelve\s*(.+?)\n',
        'innovation_solution': r'Solución o cambios que genera la innovación\s*(.+?)\n',
        'customers': r'Clientes / Usuarios\s*(.+?)\n',
        'value_proposition': r'Propuesta de Valor\s*(.+?)\n',
        'channels': r'Canales\s*(.+?)\n',
        'resources': r'Recursos\s*(.+?)\n',
        'estimated_cost': r'Egresos / Costo unitario estimado\s*(.+?)\n'
    }

    datos = {}
    for campo, patron in campos.items():
        match = re.search(patron, texto, re.IGNORECASE)
        datos[campo] = match.group(1).strip() if match else None

    datos['identity'] = datos.get('email', 'noidentity')  # Usa correo si no hay cédula explícita
    return datos

def guardar_pdf_data(datos):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        columnas = [
            'identity', 'first_name', 'last_name', 'faculty', 'career', 'phone',
            'email', 'semester', 'area', 'product_description', 'problem_identification',
            'innovation_solution', 'customers', 'value_proposition', 'channels',
            'resources', 'estimated_cost', 'updated_at'
        ]

        values = [datos.get(col) for col in columnas[:-1]] + [datetime.now()]
        update = ', '.join([f"{col}=EXCLUDED.{col}" for col in columnas[1:]])

        cur.execute(
            f"""
            INSERT INTO pdf_data ({', '.join(columnas)})
            VALUES ({', '.join(['%s'] * len(columnas))})
            ON CONFLICT (identity)
            DO UPDATE SET {update}
            """,
            values
        )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando PDF en pdf_data: {e}")

# ========== FLASK ==========
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")

        if not user_message and not pdf_file:
            return jsonify({"error": "Se requiere un mensaje o un archivo"}), 400

        if not user_message and pdf_file:
            user_message = "Analiza este archivo, por favor."

        if identity not in user_contexts:
            historial = cargar_historial_por_identity(identity)
            user_contexts[identity] = historial
            try:
                with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                    reglas = f.read().strip()
                    user_contexts[identity].insert(0, {'role': 'system', 'content': reglas})
            except:
                return jsonify({"error": "No se pudo cargar reglas"}), 500

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                texto_pdf = extract_text_from_pdf(pdf_file)
                datos = extraer_datos_pdf(texto_pdf)
                guardar_pdf_data(datos)
                user_contexts[identity].append({'role': 'user', 'content': f"PDF:\n{texto_pdf}"})
                guardar_mensaje(identity, 'user', texto_pdf)
            except Exception as e:
                return jsonify({"response": f"Error procesando PDF: {e}"}), 500

        user_contexts[identity].append({'role': 'user', 'content': user_message})
        guardar_mensaje(identity, 'user', user_message)

        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]
        respuesta = openai_IA(user_contexts[identity])

        user_contexts[identity].append({'role': 'assistant', 'content': respuesta})
        guardar_mensaje(identity, 'assistant', respuesta)

        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"❌ Error general: {e}")
        return jsonify({"response": "Error interno del servidor"}), 500
