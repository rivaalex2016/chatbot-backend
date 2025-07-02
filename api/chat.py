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
MAX_CONTEXT_LENGTH = 25

REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')
REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')
RULE_CHAT_PATH = os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt')
SYSTEM_PROMPT = ""

try:
    with open(RULE_CHAT_PATH, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read().strip()
except Exception as e:
    logging.error(f"❌ No se pudo cargar rule_chat.txt: {e}")

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
        manual_input = request.form.get("manual_input", "true").lower() == "true"


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
                            "<a href='https://www.dropbox.com/scl/fi/g9gtfg48htc6qcci3lofh/03.-FICHA-DE-EMPRENDORES_TELECOMUNICACIONES-IMPORTACIONES.docx?rlkey=k1rxpksx72ttdqjoc4i6pqk93&st=2lkozq0m&dl=1' target='_blank'>Formato Propuesta WORD</a>"
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

                if not manual_input:
                    user_contexts[identity].append({
                        'role': 'user',
                        'content': (
                            "Evalúa esta propuesta de emprendimiento con base en los siguientes criterios:\n\n"
                            "1. Problema / Solución\n"
                            "2. Mercado\n"
                            "3. Competencia\n"
                            "4. Modelo de negocio\n"
                            "5. Escalabilidad\n"
                            "6. Equipo\n\n"
                            "Para cada criterio, asigna una calificación entre:\n"
                            "- Inicial (2 puntos)\n"
                            "- En desarrollo (5 puntos)\n"
                            "- Desarrollado (8 puntos)\n"
                            "- Excelencia (10 puntos)\n\n"
                            "📋 Muestra los resultados en una **tabla** con tres columnas: **Criterio**, **Calificación**, y **Justificación breve**.\n\n"
                            "📊 Calcula el **promedio total de calificación sobre 10** (sumando las puntuaciones y dividiendo entre 6).\n\n"
                            "🔔 Según la calificación final:\n"
                            "- Si es **exactamente 10**, responde únicamente:\n"
                            "**🏆 La propuesta ha alcanzado la calificación perfecta de 10/10. No se requieren recomendaciones.**\n"
                            "- Si la calificación está entre 8 y 9.9, agrega el emoji **👍** al promedio final y proporciona 5 recomendaciones breves para llevarla a la excelencia.\n"
                            "- Si la calificación está entre 5 y 7.9, usa el emoji **⚠️** y proporciona 5 recomendaciones claras para fortalecerla.\n"
                            "- Si la calificación es menor a 5, usa el emoji **❗** y brinda 5 sugerencias urgentes para replantear la propuesta.\n\n"
                            "🎯 Las recomendaciones deben ser concretas, útiles y accionables. Usa viñetas o emojis para destacarlas.\n\n"
                            "Responde como un evaluador experto del Centro de Emprendimiento INNOVUG."
                        )
                    })



            except Exception as e:
                return jsonify({"response": f"Error procesando PDF: {str(e)}"})


        if user_message:
            user_contexts[identity].append({'role': 'user', 'content': user_message})
            if user_message and not (pdf_file and not request.form.get("manual_input")):
                guardar_mensaje(identity, 'user', user_message)


        # Insertar mensaje del sistema solo si aún no está
        if SYSTEM_PROMPT and not any(m['role'] == 'system' for m in user_contexts[identity]):
            user_contexts[identity].insert(0, {'role': 'system', 'content': SYSTEM_PROMPT})

        # Recortar contexto a máximo N mensajes
        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]

        # Generar respuesta con OpenAI
        respuesta = openai_IA(user_contexts[identity])
        user_contexts[identity].append({'role': 'assistant', 'content': respuesta})
        guardar_mensaje(identity, 'assistant', respuesta)
        # ✅ Este bloque evita error si no hay mensaje_calificacion
        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500