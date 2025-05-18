import pdfplumber
import logging
import openai
import os
import re
import traceback

import pandas as pd
from io import BytesIO
from dotenv import load_dotenv
from difflib import SequenceMatcher
from openai.error import RateLimitError
from flask import Blueprint, request, jsonify

# Configuración inicial
load_dotenv()
MODEL = os.getenv('MODEL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

user_contexts = {}
MAX_CONTEXT_LENGTH = 20
logging.basicConfig(level=logging.INFO)

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
        return f"Error IA: {str(e)}"

# PDF
REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')

def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text.strip().lower()

def compare_pdfs(ref_text, uploaded_text):
    similarity = SequenceMatcher(None, ref_text, uploaded_text).ratio() * 100
    return 5 < similarity < 90

REFERENCE_TEXT = extract_text_from_pdf(REFERENCE_PDF_PATH)

# XLSX
REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')
REFERENCE_DF = pd.read_excel(REFERENCE_FILE_PATH)

def compare_xlsx(reference_df, uploaded_df):
    if "Unnamed: 0" in reference_df.columns:
        reference_df = reference_df.drop(columns=["Unnamed: 0"])
    if uploaded_df.shape[1] > 0 and uploaded_df.iloc[:, 0].isna().all():
        uploaded_df = uploaded_df.iloc[:, 1:]
    if uploaded_df.dropna().empty:
        return False
    return reference_df.columns.equals(uploaded_df.columns)

# CSV
def transform_and_compare(file):
    try:
        try:
            df = pd.read_csv(file, encoding='utf-8', on_bad_lines='skip')
        except:
            file.seek(0)
            df = pd.read_csv(file, encoding='ISO-8859-1', on_bad_lines='skip')
    except Exception as e:
        raise Exception(f"Error leyendo CSV: {e}")

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    gen_df = pd.read_excel(output)
    similarity = SequenceMatcher(None, REFERENCE_DF.to_string(), gen_df.to_string()).ratio() * 100
    return 5 < similarity < 90

# Cargar palabras prohibidas
def load_bad_words():
    ruta = os.path.join(os.path.dirname(__file__), '../rules/rule_title.txt')
    with open(ruta, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f.readlines()]

# Flask Blueprint
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    data = request.form
    user_id = data.get('user_id', 'default_user')
    user_message = data.get('message')
    title = data.get('title')

    pdf_file = request.files.get('pdf')
    xlsx_file = request.files.get('xlsx')
    csv_file = request.files.get('csv')

    if not user_message:
        return jsonify({"error": "Mensaje requerido"}), 400

    # Iniciar contexto si no existe
    if user_id not in user_contexts:
        user_contexts[user_id] = []
        try:
            with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                reglas = f.read().strip()
            user_contexts[user_id].append({'role': 'system', 'content': reglas})
        except Exception:
            return jsonify({"error": "No se pudieron cargar las reglas"}), 500

    # Procesar PDF
    if pdf_file:
        if not pdf_file.filename.endswith('.pdf'):
            return jsonify({"error": "Formato PDF no válido"}), 400
        if pdf_file.mimetype != 'application/pdf':
            return jsonify({"error": "El archivo no parece ser un PDF"}), 400
        text = extract_text_from_pdf(pdf_file)
        if not compare_pdfs(REFERENCE_TEXT, text):
            return jsonify({"error": "El PDF no cumple los criterios"}), 400
        user_contexts[user_id].append({'role': 'user', 'content': f"PDF:\n{text}"})

    # Procesar XLSX
    if xlsx_file:
        if not xlsx_file.filename.endswith('.xlsx'):
            return jsonify({"error": "Formato XLSX no válido"}), 400
        df = pd.read_excel(xlsx_file)
        if not compare_xlsx(REFERENCE_DF, df):
            return jsonify({"error": "El XLSX no cumple los criterios"}), 400
        user_contexts[user_id].append({'role': 'user', 'content': f"XLSX:\n{df.to_string(index=False)}"})

    # Procesar CSV
    if csv_file:
        if not csv_file.filename.endswith('.csv'):
            return jsonify({"error": "Formato CSV no válido"}), 400
        if not transform_and_compare(csv_file):
            return jsonify({"error": "El CSV no cumple los criterios"}), 400
        user_contexts[user_id].append({'role': 'user', 'content': "Archivo CSV cargado correctamente."})

    # Validar título
    if title:
        bad_words = load_bad_words()
        if any(re.search(rf"\b{re.escape(word)}\b", title, re.IGNORECASE) for word in bad_words):
            return jsonify({"error": "El título contiene palabras no permitidas"}), 400
        user_contexts[user_id].append({'role': 'user', 'content': f"Título:\n{title}"})

    # Añadir mensaje
    user_contexts[user_id].append({'role': 'user', 'content': user_message})
    user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]

    respuesta = openai_IA(user_contexts[user_id])

    return jsonify({ "response": respuesta })
