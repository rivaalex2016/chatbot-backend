# chat.py actualizado
import os
import logging
import openai
import traceback
import pdfplumber
import pandas as pd
from io import BytesIO
from dotenv import load_dotenv
from difflib import SequenceMatcher
from openai.error import RateLimitError
from flask import Blueprint, request, jsonify

load_dotenv()
MODEL = os.getenv('MODEL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

logging.basicConfig(level=logging.INFO)
openai.api_key = OPENAI_API_KEY
user_contexts = {}
MAX_CONTEXT_LENGTH = 20

REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')
REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')
REFERENCE_TEXT = ""
REFERENCE_DF = pd.read_excel(REFERENCE_FILE_PATH)

try:
    with pdfplumber.open(REFERENCE_PDF_PATH) as pdf:
        for page in pdf.pages:
            REFERENCE_TEXT += page.extract_text() or ""
    REFERENCE_TEXT = REFERENCE_TEXT.strip().lower()
except Exception as e:
    print(f"Error cargando PDF de referencia: {e}")

def extract_text_from_pdf(file) -> str:
    try:
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text.strip().lower()
    except Exception as e:
        raise RuntimeError(f"Error al procesar el PDF: {e}")

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
        except Exception:
            file.seek(0)
            df = pd.read_csv(file, delimiter=';', encoding='ISO-8859-1', on_bad_lines='skip')

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    output.seek(0)
    gen_df = pd.read_excel(output)

    ref_text = REFERENCE_DF.to_string(index=False)
    gen_text = gen_df.to_string(index=False)
    similarity = SequenceMatcher(None, ref_text, gen_text).ratio() * 100
    return 5 < similarity < 80

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

chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_id = data.get('user_id', 'default_user')
    user_message = data.get('message')

    if not user_message:
        return jsonify({"error": "Mensaje requerido"}), 400

    if user_id not in user_contexts:
        user_contexts[user_id] = []
        try:
            with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                reglas = f.read().strip()
                user_contexts[user_id].append({'role': 'system', 'content': reglas})
        except Exception:
            return jsonify({"error": "No se pudieron cargar las reglas"}), 500

    lower_msg = user_message.lower()
    if "analiza" in lower_msg and ("pdf" in lower_msg or "propuesta" in lower_msg):
        ruta_contexto = os.path.join(os.path.dirname(__file__), 'contextos', f"{user_id}.txt")
        if os.path.exists(ruta_contexto):
            try:
                with open(ruta_contexto, "r", encoding="utf-8") as f:
                    texto = f.read()
                    user_contexts[user_id].append({"role": "user", "content": f"Este es el contenido del PDF del usuario para analizar: {texto}"})
            except Exception as e:
                return jsonify({"error": f"Error al leer el PDF guardado: {str(e)}"}), 500
        else:
            user_contexts[user_id].append({"role": "user", "content": "El usuario pidió analizar un PDF, pero no hay uno guardado."})

    user_contexts[user_id].append({'role': 'user', 'content': user_message})
    user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]

    respuesta = openai_IA(user_contexts[user_id])
    return jsonify({"response": respuesta})

