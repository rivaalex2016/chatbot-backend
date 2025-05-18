import pdfplumber
import logging
import openai
import os
import json
import pandas as pd
from io import BytesIO
from dotenv import load_dotenv
from difflib import SequenceMatcher
from openai.error import RateLimitError
from flask import Blueprint, request, jsonify

# Cargar variables de entorno
load_dotenv()
MODEL = os.getenv('MODEL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Configurar logs
logging.basicConfig(level=logging.INFO)

# Configurar API de OpenAI
openai.api_key = OPENAI_API_KEY
user_contexts = {}
MAX_CONTEXT_LENGTH = 20

def openai_IA(mensajes, model=MODEL, temperature=0.7):
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=mensajes,
            temperature=temperature,
        )
        return response.choices[0].message["content"]
    except RateLimitError:
        logging.error("Saldo insuficiente en el token de OpenAI.")
        return "Error: Saldo insuficiente en el token de OpenAI."
    except Exception as e:
        logging.error(f"Error en OpenAI: {e}")
        return "Error en la IA al procesar la solicitud."

# 📌 Rutas referencia
REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')
REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')
REFERENCE_DF = pd.read_excel(REFERENCE_FILE_PATH)

# 📌 PDF
def extract_text_from_pdf(file) -> str:
    try:
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text.strip().lower()
    except Exception as e:
        raise RuntimeError(f"Error al procesar el PDF: {e}")

def compare_pdfs(reference_text: str, uploaded_pdf: str) -> bool:
    similarity = SequenceMatcher(None, reference_text, uploaded_pdf).ratio() * 100
    return 5 < similarity < 90

REFERENCE_TEXT = extract_text_from_pdf(REFERENCE_PDF_PATH)

# 📌 XLSX
def compare_files(reference_df, uploaded_df):
    if "Unnamed: 0" in reference_df.columns:
        reference_df = reference_df.drop(columns=["Unnamed: 0"])
    if uploaded_df.shape[1] > 0 and uploaded_df.iloc[:, 0].isna().all():
        uploaded_df = uploaded_df.iloc[:, 1:]
    if uploaded_df.dropna().empty:
        return False
    return reference_df.columns.equals(uploaded_df.columns)

# 📌 CSV
def transform_and_compare(file):
    try:
        try:
            df = pd.read_csv(file, encoding='utf-8', on_bad_lines='skip')
        except UnicodeDecodeError:
            file.seek(0)
            try:
                df = pd.read_csv(file, encoding='ISO-8859-1', on_bad_lines='skip')
            except Exception:
                file.seek(0)
                df = pd.read_csv(file, delimiter=';', encoding='ISO-8859-1', on_bad_lines='skip')
    except Exception as e:
        raise Exception(f"Error leyendo el CSV: {e}")

    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
    except Exception as e:
        raise Exception(f"Error al convertir a XLSX: {e}")
    output.seek(0)

    try:
        ref_df = pd.read_excel(REFERENCE_FILE_PATH)
        gen_df = pd.read_excel(output)
    except Exception as e:
        raise Exception(f"Error leyendo archivo XLSX: {e}")

    similarity = SequenceMatcher(None, ref_df.to_string(index=False), gen_df.to_string(index=False)).ratio() * 100
    return 5 < similarity < 80

# 📌 TÍTULOS
def load_bad_words():
    path = os.path.join(os.path.dirname(__file__), '..', 'rules', 'rule_title.txt')
    if not os.path.exists(path):
        raise FileNotFoundError(f"El archivo {path} no fue encontrado.")
    with open(path, 'r') as f:
        return [line.strip() for line in f.readlines()]

# 📌 Persistencia de contexto
def cargar_contexto(user_id):
    path = os.path.join("contextos", f"{user_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def guardar_contexto(user_id, contexto):
    os.makedirs("contextos", exist_ok=True)
    path = os.path.join("contextos", f"{user_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(contexto, f, ensure_ascii=False, indent=2)

# 📌 API
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_id = data.get('user_id', 'default_user')
    user_message = data.get('message')

    if not user_message:
        return jsonify({"error": "Mensaje requerido"}), 400

    # Cargar contexto del usuario (de archivo si no está en memoria)
    if user_id not in user_contexts:
        contexto = cargar_contexto(user_id)
        if not contexto:
            try:
                with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                    reglas = f.read().strip()
                    contexto.append({'role': 'system', 'content': reglas})
            except Exception:
                return jsonify({"error": "No se pudieron cargar las reglas"}), 500
        user_contexts[user_id] = contexto

    # Agregar mensaje y recortar si es necesario
    user_contexts[user_id].append({'role': 'user', 'content': user_message})
    user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]

    # Obtener respuesta IA
    respuesta = openai_IA(user_contexts[user_id])

    # Agregar respuesta al contexto
    user_contexts[user_id].append({'role': 'assistant', 'content': respuesta})
    user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]

    # Guardar contexto en archivo
    guardar_contexto(user_id, user_contexts[user_id])

    return jsonify({"response": respuesta})
