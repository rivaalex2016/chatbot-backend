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

# Cargar variables de entorno
load_dotenv()
MODEL = os.getenv('MODEL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Configurar logs
logging.basicConfig(level=logging.INFO)

# Configuramos IA
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

# 📌 PDF
REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')
#Extraemos el archivo
def extract_text_from_pdf(file) -> str:
    try:
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text.strip().lower()
    except Exception as e:
        raise RuntimeError(f"Error al procesar el PDF: {e}")
#Comparamos para tener su similitud
def compare_pdfs(reference_text: str, uploaded_pdf: str) -> bool:
    similarity = SequenceMatcher(None, reference_text, uploaded_pdf).ratio()
    similarity_percentage = similarity * 100
    print(similarity_percentage)
    
    if similarity_percentage <= 5:
        return False
    elif similarity_percentage >= 90:
        return False
    else:
        return True

REFERENCE_TEXT = extract_text_from_pdf(REFERENCE_PDF_PATH)
REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')
REFERENCE_DF = pd.read_excel(REFERENCE_FILE_PATH)

# 📌 XLSX
def compare_files(reference_df, uploaded_df):
    if "Unnamed: 0" in reference_df.columns:
        reference_df = reference_df.drop(columns=["Unnamed: 0"])
    #comparamos las primeras columnas tenga similitud
    if uploaded_df.shape[1] > 0 and uploaded_df.iloc[:, 0].isna().all():
        uploaded_df = uploaded_df.iloc[:, 1:]
    if uploaded_df.dropna().empty:
        return False
    if not reference_df.columns.equals(uploaded_df.columns):
        return False  
    return True

# 📌 CSV
def transform_and_compare(file):
    # Lee el CSV con diferentes codificaciones y delimitadores
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
    
    # Convierte en un archivo XLSX
    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
    except Exception as e:
        raise Exception(f"Error al convertir a XLSX: {e}")
    output.seek(0)
    
    # Lee el XLSX de referencia
    try:
        ref_df = pd.read_excel(REFERENCE_FILE_PATH)
    except Exception as e:
        raise Exception(f"Error leyendo el archivo de referencia: {e}")
    
    # Lee el XLSX generado a partir del CSV
    try:
        gen_df = pd.read_excel(output)
    except Exception as e:
        raise Exception(f"Error leyendo el XLSX generado: {e}")
    
    # Convierte ambos DataFrames a texto para comparar
    ref_text = ref_df.to_string(index=False)
    gen_text = gen_df.to_string(index=False)
    
    # Calcular la similitud
    similarity = SequenceMatcher(None, ref_text, gen_text).ratio() * 100
    
    # Clasificar la similitud
    if similarity < 5:
        similarity_status = False
    elif similarity < 80:
        similarity_status = True
    else:
        similarity_status = False

    print(similarity)
    return similarity_status

# 📌 TITLE
def load_bad_words():
    #Llamamos las palabras prohibidas
    bad_words_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'rules', 'rule_title.txt'))
    if not os.path.exists(bad_words_file):
        raise FileNotFoundError(f"El archivo {bad_words_file} no fue encontrado.")
    with open(bad_words_file, 'r') as f:
        return [line.strip() for line in f.readlines()]

# 📌 API
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    data = request.form
    user_id = data.get('user_id')
    user_message = data.get('message')
    pdf_file = request.files.get('pdf')
    xlsx_file = request.files.get('xlsx')
    csv_file = request.files.get('csv')
    title = data.get('title')

    if not user_id or not user_message:
        return jsonify({"error": "Usuario y mensaje son requeridos"}), 400
    if pdf_file and xlsx_file and csv_file and title:
        return jsonify({"error": "Solo se puede enviar un evento a la vez: PDF, CSV, XLSX o TITULO."}), 400

    reglas_contenido = ""
    es_pdf = None
    es_xlsx = None
    es_csv = None
    es_title = None

    # 🔎 Cargar reglas del chat
    if user_id not in user_contexts:
        ruta_archivo = os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt')
        try:
            with open(ruta_archivo, 'r', encoding='utf-8') as rules_file:
                reglas_contenido = rules_file.read().strip()
            if not reglas_contenido:
                return jsonify({"error": "Reglas vacías"}), 204
        except FileNotFoundError:
            return jsonify({"error": "El archivo de reglas del CHAT no fue encontrado."}), 404

    ruta_rule_xslx_csv = os.path.join(os.path.dirname(__file__), '../rules/rule_xlsx.txt')
    
    # 🔎 Procesar XLSX
    if xlsx_file:
        # Verificar si es XLSX
        if xlsx_file.filename.endswith('.xlsx'):
            uploaded_df = pd.read_excel(xlsx_file)
        else:
            return jsonify({"error": "El archivo no es ni un XLSX"}), 400
        
        # Comparamos los datos y validamos
        xlsx_result = compare_files(REFERENCE_DF, uploaded_df)
        es_xlsx = {"state": xlsx_result, "user": user_id}
        if not xlsx_result:
            try:
                with open(ruta_rule_xslx_csv, 'r', encoding='utf-8') as rules_file:
                    reglas_xlsx = rules_file.read().strip()
                if not reglas_xlsx:
                    return jsonify({"error": "El archivo de reglas está vacío."}), 400
            except FileNotFoundError:
                    return jsonify({"error": "Archivo de reglas para CSV no encontrado."}), 404
            except PermissionError:
                    return jsonify({"error": "No se pudo acceder al archivo de reglas."}), 500
            return jsonify({"error": reglas_xlsx}), 400
    
    # 🔎 Procesar CSV
    if csv_file:
        # Verificar si es csv
        if csv_file.filename.endswith('.csv'):
            try:
                # Comparamos los datos y validamos
                csv_result = transform_and_compare(csv_file)
                es_csv = {"state": csv_result, "user": user_id}
                if not csv_result:
                    try:
                        with open(ruta_rule_xslx_csv, 'r', encoding='utf-8') as rules_file:
                            reglas_csv = rules_file.read().strip()
                        if not reglas_csv:
                            return jsonify({"error": "El archivo de reglas está vacío."}), 400
                    except FileNotFoundError:
                        return jsonify({"error": "Archivo de reglas para CSV no encontrado."}), 404
                    except PermissionError:
                        return jsonify({"error": "No se pudo acceder al archivo de reglas."}), 500
                    return jsonify({"error": reglas_csv}), 400
            except Exception as e:
                return jsonify({'error': f"Error al procesar el archivo: {e}"}), 500
        else:
            return jsonify({"error": "El archivo no es ni un CSV"}), 400


    # 🔎 Procesar Título
    if title:
        bad_words = load_bad_words()
        # Comparamos los datos y validamos
        if any(re.search(r'\b' + re.escape(word) + r'\b', title, re.IGNORECASE) for word in bad_words):
            return jsonify({'message': 'Ese título no es permitido'}), 400
        es_title = {"state": True, "user": user_id}

    # 🔎 Procesar PDF
    if pdf_file:
        if not pdf_file.filename.lower().endswith('.pdf'):
            return jsonify({"error": "El archivo no es un PDF"}), 400
        # Verificar tamaño (250 KB)
        pdf_file.seek(0, os.SEEK_END)
        file_size = pdf_file.tell()
        pdf_file.seek(0)  # Resetear puntero

        if file_size > 250 * 1024:
            return jsonify({"error": "El archivo PDF es demasiado grande (máx. 250KB)"}), 400
        try:
            uploaded_pdf_text = extract_text_from_pdf(pdf_file)
            is_pdf_valid = compare_pdfs(REFERENCE_TEXT, uploaded_pdf_text)
        except Exception as e:
            return jsonify({"error": f"Error al procesar el PDF: {str(e)}"}), 500
        logging.info(f"PDF valid: {is_pdf_valid}, User ID: {user_id}")
        if not is_pdf_valid:
            ruta_rule_pdf = os.path.join(os.path.dirname(__file__), '../rules/rule_pdf.txt')
            try:
                with open(ruta_rule_pdf, 'r', encoding='utf-8') as rules_file:
                    reglas_pdf = rules_file.read().strip()

                if not reglas_pdf:
                    return jsonify({"error": "El archivo de reglas está vacío."}), 400
            except FileNotFoundError:
                return jsonify({"error": "Archivo de reglas para PDF no encontrado."}), 404
            except PermissionError:
                return jsonify({"error": "No se pudo acceder al archivo de reglas."}), 500

            return jsonify({"error": reglas_pdf}), 400
        
        es_pdf = {"state": is_pdf_valid, "user": user_id}
        user_contexts[user_id].append({'role': 'user', 'content': f"PDF:\n{uploaded_pdf_text}"})

    # 🔎 IA de OpenAI
    if reglas_contenido:
        user_contexts[user_id] = [{'role': 'system', 'content': reglas_contenido}]
    if xlsx_file:
        xlsx_text = uploaded_df.to_csv(index=False)
        user_contexts[user_id].append({'role': 'user', 'content': f"XLSX:\n{xlsx_text}"})
    if csv_file:
        user_contexts[user_id].append({'role': 'user', 'content': f"CSV:\n{csv_file}"})
    if title:
        user_contexts[user_id].append({'role': 'user', 'content': f"Título:\n{title}"})

    user_contexts[user_id].append({'role': 'user', 'content': user_message})
    user_contexts[user_id] = user_contexts[user_id][-MAX_CONTEXT_LENGTH:]
    ai_response = openai_IA(user_contexts[user_id])

    return jsonify({
        "result": ai_response,
        "pdf": es_pdf,
        "xlsx": es_xlsx,
        "csv": es_csv,
        "title": es_title,
    })
