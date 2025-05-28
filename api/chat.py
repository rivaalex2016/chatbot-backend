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

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def guardar_mensaje(identity, role, content):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO chat_history (identity, role, content, timestamp)
            VALUES (%s, %s, %s, %s)
        """, (identity, role, content, datetime.now()))
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

def openai_IA(mensajes, model=MODEL, temperature=0.7):
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=mensajes,
            temperature=temperature,
        )
        return response.choices[0].message["content"]
    except RateLimitError:
        logging.error("Token de OpenAI insuficiente.")
        return "Error: Token de OpenAI insuficiente."
    except Exception as e:
        logging.error(f"Error en OpenAI: {e}")
        return "Error procesando la solicitud de la IA."

def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text.strip()

def parse_pdf_fields(text):
    fields = {
        'first_name': r"Nombres?:\s*(.*)",
        'last_name': r"Apellidos?:\s*(.*)",
        'faculty': r"Facultad:\s*(.*)",
        'career': r"Carrera:\s*(.*)",
        'phone': r"Tel[eé]fono:\s*(.*)",
        'email': r"Correo:\s*(.*)",
        'semester': r"Semestre:\s*(\d+)",
        'area': r"[\n\r]?[ Á]rea:?\s*(.*)",
        'product_description': r"Descripci[oó]n del producto/servicio:?\s*(.*)",
        'problem_identification': r"Identificaci[oó]n del problema que resuelve:?\s*(.*)",
        'innovation_solution': r"Soluci[oó]n o cambios que genera la innovaci[oó]n:?\s*(.*)",
        'customers': r"Clientes / Usuarios:?\s*(.*)",
        'value_proposition': r"Propuesta de Valor:?\s*(.*)",
        'channels': r"Canales:?\s*(.*)",
        'resources': r"Recursos:?\s*(.*)",
        'estimated_cost': r"Egresos / Costo unitario estimado:?\s*(.*)"
    }
    data = {}
    for key, pattern in fields.items():
        match = re.search(pattern, text, re.IGNORECASE)
        data[key] = match.group(1).strip() if match else None
    return data

def upsert_pdf_data(identity, data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
        INSERT INTO pdf_data (identity, first_name, last_name, faculty, career, phone, email, semester,
        area, product_description, problem_identification, innovation_solution, customers,
        value_proposition, channels, resources, estimated_cost, updated_at)
        VALUES (%(identity)s, %(first_name)s, %(last_name)s, %(faculty)s, %(career)s, %(phone)s, %(email)s, %(semester)s,
        %(area)s, %(product_description)s, %(problem_identification)s, %(innovation_solution)s, %(customers)s,
        %(value_proposition)s, %(channels)s, %(resources)s, %(estimated_cost)s, now())
        ON CONFLICT (identity) DO UPDATE SET
        first_name = EXCLUDED.first_name,
        last_name = EXCLUDED.last_name,
        faculty = EXCLUDED.faculty,
        career = EXCLUDED.career,
        phone = EXCLUDED.phone,
        email = EXCLUDED.email,
        semester = EXCLUDED.semester,
        area = EXCLUDED.area,
        product_description = EXCLUDED.product_description,
        problem_identification = EXCLUDED.problem_identification,
        innovation_solution = EXCLUDED.innovation_solution,
        customers = EXCLUDED.customers,
        value_proposition = EXCLUDED.value_proposition,
        channels = EXCLUDED.channels,
        resources = EXCLUDED.resources,
        estimated_cost = EXCLUDED.estimated_cost,
        updated_at = now();
        """
        data['identity'] = identity
        cur.execute(query, data)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error al insertar o actualizar PDF_DATA: {e}")

chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")

        if identity not in user_contexts:
            user_contexts[identity] = cargar_historial_por_identity(identity)
            with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                reglas = f.read().strip()
                user_contexts[identity].insert(0, {'role': 'system', 'content': reglas})

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            texto_pdf = extract_text_from_pdf(pdf_file)
            campos_extraidos = parse_pdf_fields(texto_pdf)
            upsert_pdf_data(identity, campos_extraidos)
            user_contexts[identity].append({'role': 'user', 'content': f"PDF:
{texto_pdf}"})
            guardar_mensaje(identity, 'user', texto_pdf)

        if user_message:
            user_contexts[identity].append({'role': 'user', 'content': user_message})
            guardar_mensaje(identity, 'user', user_message)

        respuesta = openai_IA(user_contexts[identity])
        user_contexts[identity].append({'role': 'assistant', 'content': respuesta})
        guardar_mensaje(identity, 'assistant', respuesta)

        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
