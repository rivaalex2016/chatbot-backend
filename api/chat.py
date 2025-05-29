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
        logging.error(f"Error guardando mensaje en DB: {e}")

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
        logging.error(f"Error cargando historial desde DB: {e}")
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

def extract_pdf_fields(text):
    fields = {
        "first_name": re.search(r"Nombres:\s*(.*)", text),
        "last_name": re.search(r"Apellidos:\s*(.*)", text),
        "faculty": re.search(r"Facultad:\s*(.*)", text),
        "career": re.search(r"Carrera:\s*(.*)", text),
        "phone": re.search(r"Número de Teléfono:\s*(.*)", text),
        "email": re.search(r"Correo Electrónico:\s*(.*)", text),
        "semester": re.search(r"Semestre que Cursa:\s*(.*)", text),
        "area": re.search(r"\n\s*\u00c1rea\s*\n(.*?)\n", text, re.DOTALL),
        "product_description": re.search(r"Descripción del producto/servicio\s*(.*?)\n", text),
        "problem_identification": re.search(r"Identificación del problema que resuelve\s*(.*?)\n", text),
        "innovation_solution": re.search(r"Solución o cambios que genera la innovación\s*(.*?)\n", text),
        "customers": re.search(r"Clientes / Usuarios\s*(.*?)\n", text),
        "value_proposition": re.search(r"Propuesta de Valor\s*(.*?)\n", text),
        "channels": re.search(r"Canales\s*(.*?)\n", text),
        "resources": re.search(r"Recursos\s*(.*?)\n", text),
        "estimated_cost": re.search(r"Egresos / Costo unitario estimado\s*(.*?)\n", text)
    }
    return {k: (v.group(1).strip() if v else None) for k, v in fields.items()}

def guardar_datos_pdf(data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pdf_data (
                identity, first_name, last_name, faculty, career, phone, email, semester,
                area, product_description, problem_identification, innovation_solution,
                customers, value_proposition, channels, resources, estimated_cost, updated_at)
            VALUES (
                %(identity)s, %(first_name)s, %(last_name)s, %(faculty)s, %(career)s, %(phone)s, %(email)s, %(semester)s,
                %(area)s, %(product_description)s, %(problem_identification)s, %(innovation_solution)s,
                %(customers)s, %(value_proposition)s, %(channels)s, %(resources)s, %(estimated_cost)s, now())
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
                updated_at=now()
        """, data)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error guardando datos PDF: {e}")

chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id")
        message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")

        if not identity:
            return jsonify({"response": "Debes ingresar tu número de cédula."}), 400

        if identity not in user_contexts:
            historial = cargar_historial_por_identity(identity)
            user_contexts[identity] = historial

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            with pdfplumber.open(pdf_file) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            campos = extract_pdf_fields(text)
            campos["identity"] = identity
            guardar_datos_pdf(campos)
            user_contexts[identity].append({"role": "user", "content": f"PDF:
{text}"})
            guardar_mensaje(identity, "user", text)

        if message:
            user_contexts[identity].append({"role": "user", "content": message})
            guardar_mensaje(identity, "user", message)

        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]
        respuesta = openai_IA(user_contexts[identity])
        user_contexts[identity].append({"role": "assistant", "content": respuesta})
        guardar_mensaje(identity, "assistant", respuesta)

        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"Error general en /chat: {e}")
        return jsonify({"response": "Error interno del servidor"}), 500
