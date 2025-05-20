import pdfplumber
import logging
import openai
import os
import json
import re
import traceback

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

openai.api_key = OPENAI_API_KEY

# Rutas para guardar contextos y archivos subidos por usuario
CONTEXTOS_DIR = os.path.join(os.path.dirname(__file__), 'contextos')
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), '../uploads')

os.makedirs(CONTEXTOS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

MAX_CONTEXT_LENGTH = 20

def cargar_contexto(user_id):
    path = os.path.join(CONTEXTOS_DIR, f'{user_id}.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        return []

def guardar_contexto(user_id, contexto):
    path = os.path.join(CONTEXTOS_DIR, f'{user_id}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(contexto, f, ensure_ascii=False, indent=2)

def guardar_pdf_usuario(user_id, filename, file):
    save_path = os.path.join(UPLOADS_DIR, f'{user_id}.pdf')
    file.save(save_path)
    return save_path

def obtener_ultimo_pdf(user_id):
    path = os.path.join(UPLOADS_DIR, f'{user_id}.pdf')
    return path if os.path.exists(path) else None

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

# Comparación de archivos
REFERENCE_PDF_PATH = os.path.join(os.path.dirname(__file__), '../documents/doc_003.pdf')
REFERENCE_TEXT = ""
try:
    with pdfplumber.open(REFERENCE_PDF_PATH) as ref_pdf:
        for page in ref_pdf.pages:
            REFERENCE_TEXT += page.extract_text() or ""
    REFERENCE_TEXT = REFERENCE_TEXT.strip().lower()
except Exception as e:
    logging.error(f"No se pudo cargar el PDF de referencia: {e}")

REFERENCE_FILE_PATH = os.path.join(os.path.dirname(__file__), '../documents/Criterios de evaluación de STARTUPS.xlsx')

# Blueprint de la API
chat_blueprint = Blueprint('chat', __name__)

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_id = data.get('user_id', 'default_user')
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({"error": "Mensaje requerido"}), 400

    contexto = cargar_contexto(user_id)

    if not contexto:
        # Cargar reglas del sistema si es el primer mensaje
        try:
            with open(os.path.join(os.path.dirname(__file__), '../rules/rule_chat.txt'), 'r', encoding='utf-8') as f:
                reglas = f.read().strip()
                contexto.append({'role': 'system', 'content': reglas})
        except:
            contexto.append({'role': 'system', 'content': 'Eres un asistente experto en emprendimientos.'})

    # Agregar mensaje del usuario
    contexto.append({'role': 'user', 'content': user_message})
    contexto = contexto[-MAX_CONTEXT_LENGTH:]

    # Si el usuario dice algo como "analiza mi propuesta"
    if re.search(r'\banaliza\b.*\bpropuesta\b', user_message.lower()):
        pdf_path = obtener_ultimo_pdf(user_id)
        if pdf_path:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    contenido = ""
                    for page in pdf.pages:
                        contenido += page.extract_text() or ""
                    contenido = contenido.strip().lower()

                similaridad = SequenceMatcher(None, REFERENCE_TEXT, contenido).ratio() * 100

                if similaridad < 5 or similaridad > 90:
                    respuesta = "Tu documento es muy diferente o demasiado parecido al de referencia. No es válido para evaluar."
                else:
                    respuesta = "Documento recibido y válido. Procederé a evaluarlo. ¿Tienes algo más que quieras incluir?"
            except Exception as e:
                respuesta = f"Hubo un problema al analizar tu archivo: {str(e)}"
        else:
            respuesta = "Por favor, sube primero un archivo PDF para poder analizarlo."
    else:
        # Procesamiento normal con IA
        respuesta = openai_IA(contexto)

    # Agregar respuesta al contexto y guardarlo
    contexto.append({'role': 'assistant', 'content': respuesta})
    guardar_contexto(user_id, contexto)

    return jsonify({"response": respuesta})

@chat_blueprint.route('/upload', methods=['POST'])
def upload():
    user_id = request.form.get('user_id', 'default_user')
    if 'file' not in request.files:
        return jsonify({"error": "No se envió ningún archivo"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    try:
        guardar_pdf_usuario(user_id, file.filename, file)
        return jsonify({"message": f"Archivo {file.filename} recibido correctamente"})
    except Exception as e:
        return jsonify({"error": f"No se pudo guardar el archivo: {str(e)}"}), 500
