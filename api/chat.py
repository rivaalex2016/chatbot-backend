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

def extraer_datos_pdf(texto):
    datos = {}
    patrones = {
        'first_name': r'Nombres\s*[:\-]?\s*(.*)',
        'last_name': r'Apellidos\s*[:\-]?\s*(.*)',
        'faculty': r'Facultad\s*[:\-]?\s*(.*)',
        'career': r'Carrera\s*[:\-]?\s*(.*)',
        'phone': r'Tel[eé]fono\s*[:\-]?\s*(.*)',
        'email': r'Correo\s*[:\-]?\s*(.*)',
        'semester': r'Semestre\s*[:\-]?\s*(\d+)',
        'area': r'Área\s*[:\-]?\s*(.*)',
        'product_description': r'Descripci[oó]n del producto/servicio\s*[:\-]?\s*(.*)',
        'problem_identification': r'Identificaci[oó]n del problema que resuelve\s*[:\-]?\s*(.*)',
        'innovation_solution': r'Soluci[oó]n o cambios que genera la innovaci[oó]n\s*[:\-]?\s*(.*)',
        'customers': r'Clientes / Usuarios\s*[:\-]?\s*(.*)',
        'value_proposition': r'Propuesta de Valor\s*[:\-]?\s*(.*)',
        'channels': r'Canales\s*[:\-]?\s*(.*)',
        'resources': r'Recursos\s*[:\-]?\s*(.*)',
        'estimated_cost': r'Egresos / Costo unitario estimado\s*[:\-]?\s*(.*)'
    }
    for campo, patron in patrones.items():
        match = re.search(patron, texto, re.IGNORECASE)
        datos[campo] = match.group(1).strip() if match else None
    return datos

def upsert_pdf_data(identity, datos):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        columnas = ', '.join(datos.keys())
        valores = ', '.join(['%s'] * len(datos))
        actualiza = ', '.join([f"{k} = EXCLUDED.{k}" for k in datos.keys()])
        sql = f"""
            INSERT INTO pdf_data (identity, {columnas})
            VALUES (%s, {valores})
            ON CONFLICT (identity)
            DO UPDATE SET {actualiza}, updated_at = CURRENT_TIMESTAMP;
        """
        cur.execute(sql, (identity, *datos.values()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error en UPSERT pdf_data: {e}")

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

def extract_text_from_pdf(file) -> str:
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text.strip().lower()

def compare_pdfs(reference_text: str, uploaded_text: str) -> bool:
    similarity = SequenceMatcher(None, reference_text, uploaded_text).ratio() * 100
    return 5 < similarity < 90

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
            try:
                uploaded_text = extract_text_from_pdf(pdf_file)

                # Verificar si el PDF es válido comparándolo con la referencia
                if not compare_pdfs(REFERENCE_TEXT, uploaded_text):
                    return jsonify({
                        "response": (
                            "📄 El archivo enviado no parece una propuesta de emprendimiento válida. "
                            "Por favor, descarga y completa el formato oficial desde este enlace: "
                            "<a href='https://tusitio.com/formato_propuesta.pdf' target='_blank'>Formato Propuesta PDF</a>"
                        )
                    })

                # Extraer datos clave del PDF y guardarlos
                datos_extraidos = extraer_datos_pdf(uploaded_text)
                upsert_pdf_data(identity, datos_extraidos)

                # Agregar el contenido del PDF al historial
                user_contexts[identity].append({
                    'role': 'user',
                    'content': f"DATOS EXTRAÍDOS DEL PDF:\n{uploaded_text}"
                })
                guardar_mensaje(identity, 'user', uploaded_text)

                # ✅ Instrucción clara a la IA para que actúe sobre el contenido
                user_contexts[identity].append({
                        'role': 'user',
                        'content': (
                            "Evalúa esta propuesta de emprendimiento usando los siguientes criterios:\n\n"
                            "1. **Problema / Solución**: ¿Qué problema resuelve y cómo?\n"
                            "2. **Mercado**: ¿Está definido el mercado y su potencial?\n"
                            "3. **Competencia**: ¿Se identifica la competencia y se define una ventaja?\n"
                            "4. **Modelo de negocio**: ¿Está claro cómo generará ingresos?\n"
                            "5. **Escalabilidad**: ¿Puede crecer con eficiencia?\n"
                            "6. **Equipo**: ¿Quién lidera y ejecuta la propuesta?\n\n"
                            "Para cada criterio, asigna una puntuación:\n"
                            "- Inicial (2 puntos)\n"
                            "- En desarrollo (5 puntos)\n"
                            "- Desarrollado (8 puntos)\n"
                            "- Excelencia (10 puntos)\n\n"
                            "Justifica cada calificación brevemente. Finaliza con el promedio total y recomendaciones para mejorar. "
                            "Responde como un evaluador experto de INNOVUG."
                        )
                })

            except Exception as e:
                return jsonify({"response": f"Error procesando PDF: {str(e)}"})


        if user_message:
            user_contexts[identity].append({'role': 'user', 'content': user_message})
            guardar_mensaje(identity, 'user', user_message)

        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]
        respuesta = openai_IA(user_contexts[identity])
        user_contexts[identity].append({'role': 'assistant', 'content': respuesta})
        guardar_mensaje(identity, 'assistant', respuesta)
        # ✅ Este bloque evita error si no hay mensaje_calificacion
        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500