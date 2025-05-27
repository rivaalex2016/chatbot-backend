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

# --- CONEXIÓN A LA BASE DE DATOS ---
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

# --- FUNCIONES DEL CHATBOT ---
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

def compare_files(reference_df, uploaded_df):
    if "Unnamed: 0" in reference_df.columns:
        reference_df = reference_df.drop(columns=["Unnamed: 0"])
    if uploaded_df.shape[1] > 0 and uploaded_df.iloc[:, 0].isna().all():
        uploaded_df = uploaded_df.iloc[:, 1:]
    if uploaded_df.dropna().empty:
        return False
    return reference_df.columns.equals(uploaded_df.columns)

def transform_and_compare(file):
    try:
        df = pd.read_csv(file, encoding='utf-8', on_bad_lines='skip')
    except UnicodeDecodeError:
        file.seek(0)
        try:
            df = pd.read_csv(file, encoding='ISO-8859-1', on_bad_lines='skip')
        except:
            file.seek(0)
            df = pd.read_csv(file, delimiter=';', encoding='ISO-8859-1', on_bad_lines='skip')

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    output.seek(0)

    ref_df = pd.read_excel(REFERENCE_FILE_PATH)
    gen_df = pd.read_excel(output)

    ref_text = ref_df.to_string(index=False)
    gen_text = gen_df.to_string(index=False)
    similarity = SequenceMatcher(None, ref_text, gen_text).ratio() * 100
    return 5 < similarity < 80

def load_bad_words():
    path = os.path.join(os.path.dirname(__file__), '..', 'rules', 'rule_title.txt')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f.readlines()]

chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        identity = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")
        xlsx_file = request.files.get("xlsx")
        csv_file = request.files.get("csv")
        title = request.form.get("title")

        if not user_message and not (pdf_file or xlsx_file or csv_file):
            return jsonify({"error": "Se requiere un mensaje o archivo válido"}), 400

        if not user_message and (pdf_file or xlsx_file or csv_file):
            user_message = "Analiza este archivo, por favor."

        if identity not in user_contexts:
            historial_prev = cargar_historial_por_identity(identity)
            user_contexts[identity] = historial_prev
            try:
                with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                    reglas = f.read().strip()
                    user_contexts[identity].insert(0, {'role': 'system', 'content': reglas})
            except Exception:
                return jsonify({"error": "No se pudieron cargar las reglas"}), 500

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                uploaded_text = extract_text_from_pdf(pdf_file)
                if compare_pdfs(REFERENCE_TEXT, uploaded_text):
                    user_contexts[identity].append({'role': 'user', 'content': f"PDF:\n{uploaded_text}"})
                    guardar_mensaje(identity, 'user', uploaded_text)
                else:
                    return jsonify({"response": "El PDF no cumple con los criterios esperados."})
            except Exception as e:
                return jsonify({"response": f"Error procesando PDF: {str(e)}"})

        if xlsx_file and xlsx_file.filename.endswith(".xlsx"):
            df = pd.read_excel(xlsx_file)
            if compare_files(REFERENCE_DF, df):
                content = df.to_string(index=False)
                user_contexts[identity].append({'role': 'user', 'content': f"XLSX:\n{content}"})
                guardar_mensaje(identity, 'user', content)
            else:
                return jsonify({"response": "El archivo XLSX no coincide con la estructura esperada."})

        if csv_file and csv_file.filename.endswith(".csv"):
            try:
                if transform_and_compare(csv_file):
                    user_contexts[identity].append({'role': 'user', 'content': "CSV: Archivo compatible cargado."})
                    guardar_mensaje(identity, 'user', "Archivo CSV compatible")
                else:
                    return jsonify({"response": "El archivo CSV no es válido o no tiene el formato correcto."})
            except Exception as e:
                return jsonify({"response": f"Error procesando CSV: {str(e)}"})

        if title:
            bad_words = load_bad_words()
            if any(re.search(rf'\b{re.escape(word)}\b', title, re.IGNORECASE) for word in bad_words):
                return jsonify({"response": "Ese título contiene palabras no permitidas."})
            user_contexts[identity].append({'role': 'user', 'content': f"Título:\n{title}"})
            guardar_mensaje(identity, 'user', title)

        user_contexts[identity].append({'role': 'user', 'content': user_message})
        guardar_mensaje(identity, 'user', user_message)

        user_contexts[identity] = user_contexts[identity][-MAX_CONTEXT_LENGTH:]
        respuesta = openai_IA(user_contexts[identity])

        user_contexts[identity].append({'role': 'assistant', 'content': respuesta})
        guardar_mensaje(identity, 'assistant', respuesta)

        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
