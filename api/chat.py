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

REFERENCE_TEXT = ""
REFERENCE_DF = pd.DataFrame()

try:
    with pdfplumber.open(REFERENCE_PDF_PATH) as pdf:
        REFERENCE_TEXT = "\n".join(page.extract_text() or "" for page in pdf.pages).strip().lower()
except:
    pass

try:
    REFERENCE_DF = pd.read_excel(REFERENCE_FILE_PATH)
except:
    pass

# Conexión a la base de datos

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

# Guardar historial

def guardar_mensaje(identity, role, content):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO chat_history (identity, role, content, timestamp) VALUES (%s, %s, %s, %s)",
                    (identity, role, content, datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando mensaje en DB: {e}")

# Cargar historial

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

# Extraer datos del PDF para llenar la tabla pdf_data

def extraer_datos_pdf(uploaded_text):
    campos = {
        'first_name': re.search(r"Nombre:\s*(.+)", uploaded_text),
        'last_name': re.search(r"Apellido:\s*(.+)", uploaded_text),
        'faculty': re.search(r"Facultad:\s*(.+)", uploaded_text),
        'career': re.search(r"Carrera:\s*(.+)", uploaded_text),
        'phone': re.search(r"Tel[eé]fono:\s*(\d+)", uploaded_text),
        'email': re.search(r"Correo electr[oó]nico:\s*([\w\.\-@]+)", uploaded_text),
        'semester': re.search(r"Semestre:\s*(\d+)", uploaded_text),
        'area': re.search(r"Area de enfoque:\s*(.+)", uploaded_text),
        'product_description': re.search(r"Descripci[oó]n del producto:\s*(.+)", uploaded_text),
        'problem_identification': re.search(r"Problema identificado:\s*(.+)", uploaded_text),
        'innovation_solution': re.search(r"Soluci[oó]n innovadora:\s*(.+)", uploaded_text),
        'customers': re.search(r"Clientes usuarios:\s*(.+)", uploaded_text),
        'value_proposition': re.search(r"Propuesta de valor:\s*(.+)", uploaded_text),
        'channels': re.search(r"Canales:\s*(.+)", uploaded_text),
        'resources': re.search(r"Recursos necesarios:\s*(.+)", uploaded_text),
        'estimated_cost': re.search(r"Costo estimado:\s*(.+)", uploaded_text),
    }
    return {k: (v.group(1).strip() if v else None) for k, v in campos.items()}

# Insertar o actualizar datos

def guardar_datos_pdf(identity, datos):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pdf_data (
                identity, first_name, last_name, faculty, career, phone, email, semester,
                area, product_description, problem_identification, innovation_solution,
                customers, value_proposition, channels, resources, estimated_cost, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (identity) DO UPDATE SET
                first_name=EXCLUDED.first_name,
                last_name=EXCLUDED.last_name,
                faculty=EXCLUDED.faculty,
                career=EXCLUDED.career,
                phone=EXCLUDED.phone,
                email=EXCLUDED.email,
                semester=EXCLUDED.semester,
                area=EXCLUDED.area,
                product_description=EXCLUDED.product_description,
                problem_identification=EXCLUDED.problem_identification,
                innovation_solution=EXCLUDED.innovation_solution,
                customers=EXCLUDED.customers,
                value_proposition=EXCLUDED.value_proposition,
                channels=EXCLUDED.channels,
                resources=EXCLUDED.resources,
                estimated_cost=EXCLUDED.estimated_cost,
                updated_at=NOW();
        """, [identity] + list(datos.values()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando datos del PDF en DB: {e}")

# Funciones IA

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
        return f"Error IA: {e}"

# PDF text

def extract_text_from_pdf(file) -> str:
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text.strip().lower()

# Blueprint
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")

        if identity not in user_contexts:
            historial_prev = cargar_historial_por_identity(identity)
            user_contexts[identity] = historial_prev

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            uploaded_text = extract_text_from_pdf(pdf_file)
            datos = extraer_datos_pdf(uploaded_text)
            guardar_datos_pdf(identity, datos)
            user_contexts[identity].append({"role": "user", "content": uploaded_text})
            guardar_mensaje(identity, "user", uploaded_text)

        if user_message:
            user_contexts[identity].append({"role": "user", "content": user_message})
            guardar_mensaje(identity, "user", user_message)

        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]
        respuesta = openai_IA(user_contexts[identity])
        user_contexts[identity].append({"role": "assistant", "content": respuesta})
        guardar_mensaje(identity, "assistant", respuesta)

        return jsonify({"response": respuesta})
    
    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
