# chat.py actualizado para aceptar PDF, CSV, XLSX y título desde /api/chat
import pdfplumber
import logging
import openai
import os
import re

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
        user_id = request.form.get("user_id", "default_user")
        user_message = request.form.get("message", "")
        pdf_file = request.files.get("pdf")
        xlsx_file = request.files.get("xlsx")
        csv_file = request.files.get("csv")
        title = request.form.get("title")

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

        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                uploaded_text = extract_text_from_pdf(pdf_file)
                if compare_pdfs(REFERENCE_TEXT, uploaded_text):
                    user_contexts[user_id].append({'role': 'user', 'content': f"PDF:\n{uploaded_text}"})
                else:
                    return jsonify({"response": "El PDF no cumple con los criterios esperados."})
            except Exception as e:
                return jsonify({"response": f"Error procesando PDF: {str(e)}"})

        if xlsx_file and xlsx_file.filename.endswith(".xlsx"):
            df = pd.read_excel(xlsx_file)
            if compare_files(REFERENCE_DF, df):
                user_contexts[user_id].append({'role': 'user', 'content': f"XLSX:\n{df.to_string(index=False)}"})
            else:
                return jsonify({"response": "El archivo XLSX no coincide con la estructura esperada."})

        if csv_file and csv_file.filename.endswith(".csv"):
            try:
                if transform_and_compare(csv_file):
                    user_contexts[user_id].append({'role': 'user', 'content': f"CSV: Archivo compatible cargado."})
                else:
                    return jsonify({"response": "El archivo CSV no es válido o no tiene el formato correcto."})
            except Exception as e:
                return jsonify({"response": f"Error procesando CSV: {str(e)}"})

        if title:
            bad_words = load_bad_words()
            if any(re.search(rf'\b{re.escape(word)}\b', title, re.IGNORECASE) for word in bad_words):
                return jsonify({"response": "Ese título contiene palabras no permitidas."})
            user_contexts[user_id].append({'role': 'user', 'content': f"Título:\n{title}"})

        user_contexts[user_id].append({'role': 'user', 'content': user_message})
        user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]

        respuesta = openai_IA(user_contexts[user_id])
        user_contexts[user_id].append({'role': 'assistant', 'content': respuesta})        # Imprimir historial del usuario en consola
        print(f"\n--- Historial de {user_id} ---")
        for mensaje in user_contexts[user_id]:
            print(f"[{mensaje['role'].upper()}] {mensaje['content'][:100]}...")
        print("--- Fin del historial ---\n")
        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
