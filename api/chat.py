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
        cur.execute("INSERT INTO chat_history (identity, role, content, timestamp) VALUES (%s, %s, %s, %s)",
                    (identity, role, content, datetime.now()))
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
        return "Error: Token de OpenAI insuficiente."
    except Exception as e:
        logging.error(f"Error en OpenAI: {e}")
        return "Error procesando la solicitud."

def extraer_campos_pdf(texto):
    campos = {
        "identity": "",
        "first_name": "",
        "last_name": "",
        "faculty": "",
        "career": "",
        "phone": "",
        "email": "",
        "semester": "",
        "area": "",
        "product_description": "",
        "problem_identification": "",
        "innovation_solution": "",
        "customers": "",
        "value_proposition": "",
        "channels": "",
        "resources": "",
        "estimated_cost": ""
    }

    def buscar(clave):
        patron = re.compile(rf"{clave}:\s*(.*)", re.IGNORECASE)
        resultado = patron.search(texto)
        return resultado.group(1).strip() if resultado else ""

    campos["first_name"] = buscar("Nombres")
    campos["last_name"] = buscar("Apellidos")
    campos["faculty"] = buscar("Facultad")
    campos["career"] = buscar("Carrera")
    campos["phone"] = buscar("Número de Teléfono")
    campos["email"] = buscar("Correo Electrónico")
    campos["semester"] = buscar("Semestre que Cursa")
    campos["area"] = buscar("Área")
    campos["product_description"] = buscar("Descripción del producto/servicio")
    campos["problem_identification"] = buscar("Identificación del problema que resuelve")
    campos["innovation_solution"] = buscar("Solución o cambios que genera la innovación")
    campos["customers"] = buscar("Clientes / Usuarios")
    campos["value_proposition"] = buscar("Propuesta de Valor")
    campos["channels"] = buscar("Canales")
    campos["resources"] = buscar("Recursos")
    campos["estimated_cost"] = buscar("Egresos / Costo unitario estimado")
    campos["identity"] = campos["email"].split("@")[0][-10:]  # Últimos 10 dígitos como cédula ficticia
    return campos

def guardar_pdf_data(campos):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pdf_data (
                identity, first_name, last_name, faculty, career, phone, email, semester,
                area, product_description, problem_identification, innovation_solution,
                customers, value_proposition, channels, resources, estimated_cost, updated_at
            ) VALUES (
                %(identity)s, %(first_name)s, %(last_name)s, %(faculty)s, %(career)s, %(phone)s, %(email)s, %(semester)s,
                %(area)s, %(product_description)s, %(problem_identification)s, %(innovation_solution)s,
                %(customers)s, %(value_proposition)s, %(channels)s, %(resources)s, %(estimated_cost)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (identity)
            DO UPDATE SET
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
                updated_at = CURRENT_TIMESTAMP;
        """, campos)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error al guardar pdf_data: {e}")

chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")

        if identity not in user_contexts:
            historial = cargar_historial_por_identity(identity)
            user_contexts[identity] = historial

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            with pdfplumber.open(pdf_file) as pdf:
                texto_pdf = "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
                campos = extraer_campos_pdf(texto_pdf)
                if campos["identity"]:
                    guardar_pdf_data(campos)
                    user_contexts[identity].append({"role": "user", "content": texto_pdf})
                    guardar_mensaje(identity, "user", texto_pdf)
                else:
                    return jsonify({"response": "No se pudo extraer la cédula del documento."})

        if user_message:
            user_contexts[identity].append({"role": "user", "content": user_message})
            guardar_mensaje(identity, "user", user_message)

        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]
        respuesta = openai_IA(user_contexts[identity])
        user_contexts[identity].append({"role": "assistant", "content": respuesta})
        guardar_mensaje(identity, "assistant", respuesta)
        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"❌ Error general: {e}")
        return jsonify({"response": "Error interno del servidor."}), 500
