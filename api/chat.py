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
        query = """
        INSERT INTO pdf_data (
            identity, first_name, last_name, faculty, career, phone, email, semester,
            area, product_description, problem_identification, innovation_solution,
            customers, value_proposition, channels, resources, estimated_cost, updated_at
        )
        VALUES (%(identity)s, %(first_name)s, %(last_name)s, %(faculty)s, %(career)s, %(phone)s, %(email)s, %(semester)s,
                %(area)s, %(product_description)s, %(problem_identification)s, %(innovation_solution)s,
                %(customers)s, %(value_proposition)s, %(channels)s, %(resources)s, %(estimated_cost)s, NOW())
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
            updated_at = NOW();
        """
        cur.execute(query, data)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error al guardar datos del PDF: {e}")

def extract_fields_from_pdf(text, fallback_identity):
    fields = {
        "identity": fallback_identity,
        "first_name": "", "last_name": "", "faculty": "", "career": "",
        "phone": "", "email": "", "semester": "", "area": "", "product_description": "",
        "problem_identification": "", "innovation_solution": "", "customers": "",
        "value_proposition": "", "channels": "", "resources": "", "estimated_cost": ""
    }

    def get_value(label):
        pattern = rf"{label}:\s*(.*)"
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    fields["first_name"] = get_value("Nombres")
    fields["last_name"] = get_value("Apellidos")
    fields["faculty"] = get_value("Facultad")
    fields["career"] = get_value("Carrera")
    fields["phone"] = get_value("Número de Teléfono")
    fields["email"] = get_value("Correo Electrónico")
    fields["semester"] = get_value("Semestre que Cursa")
    fields["area"] = get_value("Área")
    fields["product_description"] = get_value("Descripción del producto/servicio")
    fields["problem_identification"] = get_value("Identificación del problema que resuelve")
    fields["innovation_solution"] = get_value("Solución o cambios que genera la innovación")
    fields["customers"] = get_value("Clientes / Usuarios")
    fields["value_proposition"] = get_value("Propuesta de Valor")
    fields["channels"] = get_value("Canales")
    fields["resources"] = get_value("Recursos")
    fields["estimated_cost"] = get_value("Egresos / Costo unitario estimado")

    # Si hay una cédula, extraerla, si no usar el fallback
    cedula_match = re.search(r"\b\d{10}\b", text)
    if cedula_match:
        fields["identity"] = cedula_match.group(0)

    return fields

def extract_text_from_pdf(file) -> str:
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text.strip()

chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route("/chat", methods=["POST"])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        pdf_file = request.files.get("pdf")

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                pdf_text = extract_text_from_pdf(pdf_file)
                datos_extraidos = extract_fields_from_pdf(pdf_text, identity)

                if not datos_extraidos["identity"]:
                    return jsonify({"response": "No se encontró una cédula válida en el PDF."})

                guardar_pdf_data(datos_extraidos)
                return jsonify({"response": "Información del PDF almacenada correctamente."})

            except Exception as e:
                return jsonify({"response": f"Error procesando el PDF: {str(e)}"})

        return jsonify({"response": "No se envió un archivo PDF válido."})

    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
