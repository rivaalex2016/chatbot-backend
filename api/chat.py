# chat.py
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

def guardar_pdf_data(data):
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
                %(customers)s, %(value_proposition)s, %(channels)s, %(resources)s, %(estimated_cost)s, now()
            )
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
                updated_at = now()
        """, data)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando PDF en DB: {e}")

def extraer_datos_pdf(file):
    with pdfplumber.open(file) as pdf:
        text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())

    data = {
        "identity": re.search(r"Cédula.*?:\s*(\d+)", text, re.IGNORECASE),
        "first_name": re.search(r"Nombres.*?:\s*(.+)", text, re.IGNORECASE),
        "last_name": re.search(r"Apellidos.*?:\s*(.+)", text, re.IGNORECASE),
        "faculty": re.search(r"Facultad.*?:\s*(.+)", text, re.IGNORECASE),
        "career": re.search(r"Carrera.*?:\s*(.+)", text, re.IGNORECASE),
        "phone": re.search(r"Teléfono.*?:\s*(.+)", text, re.IGNORECASE),
        "email": re.search(r"Correo.*?:\s*(.+)", text, re.IGNORECASE),
        "semester": re.search(r"Semestre.*?:\s*(.+)", text, re.IGNORECASE),
        "area": re.search(r"Área.*?:\s*(.+)", text, re.IGNORECASE),
        "product_description": re.search(r"Descripción.*?:\s*(.+)", text, re.IGNORECASE),
        "problem_identification": re.search(r"Identificación del problema.*?:\s*(.+)", text, re.IGNORECASE),
        "innovation_solution": re.search(r"Solución.*?:\s*(.+)", text, re.IGNORECASE),
        "customers": re.search(r"Clientes.*?:\s*(.+)", text, re.IGNORECASE),
        "value_proposition": re.search(r"Propuesta de Valor.*?:\s*(.+)", text, re.IGNORECASE),
        "channels": re.search(r"Canales.*?:\s*(.+)", text, re.IGNORECASE),
        "resources": re.search(r"Recursos.*?:\s*(.+)", text, re.IGNORECASE),
        "estimated_cost": re.search(r"Egresos.*?:\s*(.+)", text, re.IGNORECASE)
    }

    # Extraer el texto limpio
    for k, v in data.items():
        data[k] = v.group(1).strip() if v else None

    return data

# Blueprint Flask
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                pdf_data = extraer_datos_pdf(pdf_file)
                if pdf_data.get("identity"):
                    guardar_pdf_data(pdf_data)
                else:
                    return jsonify({"response": "No se encontró una cédula válida en el PDF."})
            except Exception as e:
                return jsonify({"response": f"Error al analizar el PDF: {e}"})

        if not user_message:
            return jsonify({"response": "Envíame un mensaje o un archivo para analizar."})

        if identity not in user_contexts:
            user_contexts[identity] = []

        user_contexts[identity].append({'role': 'user', 'content': user_message})
        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]

        respuesta = openai.ChatCompletion.create(
            model=MODEL,
            messages=user_contexts[identity],
            temperature=0.7
        ).choices[0].message["content"]

        user_contexts[identity].append({'role': 'assistant', 'content': respuesta})
        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"❌ Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
