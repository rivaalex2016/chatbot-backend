# api/chat.py
import os
import json
import logging
import pdfplumber
import openai
import pandas as pd
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv
from difflib import SequenceMatcher

load_dotenv()
MODEL = os.getenv("MODEL", "gpt-3.5-turbo")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY
chat_blueprint = Blueprint("chat", __name__)

CONTEXT_DIR = os.path.join(os.path.dirname(__file__), "contextos")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
REFERENCE_PATH = os.path.join(os.path.dirname(__file__), "..", "documents", "doc_003.pdf")

os.makedirs(CONTEXT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def load_context(user_id):
    path = os.path.join(CONTEXT_DIR, f"{user_id}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_context(user_id, context):
    path = os.path.join(CONTEXT_DIR, f"{user_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

def get_last_uploaded_pdf(user_id):
    files = sorted(
        [f for f in os.listdir(UPLOAD_DIR) if f.startswith(user_id) and f.endswith(".pdf")],
        reverse=True
    )
    return os.path.join(UPLOAD_DIR, files[0]) if files else None

def extract_text_from_pdf(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join([p.extract_text() for p in pdf.pages if p.extract_text()])

def ask_openai(messages):
    response = openai.ChatCompletion.create(
        model=MODEL,
        messages=messages,
        temperature=0.7
    )
    return response.choices[0].message.content

@chat_blueprint.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_id = data.get("user_id")
    message = data.get("message", "").strip()

    if not user_id or not message:
        return jsonify({"response": "ID y mensaje requeridos"}), 400

    context = load_context(user_id)

    # Análisis automático
    if "analiza mi propuesta" in message.lower():
        pdf_path = get_last_uploaded_pdf(user_id)
        if not pdf_path:
            return jsonify({"response": "No encuentro tu archivo PDF. Sube uno primero."}), 400
        try:
            extracted = extract_text_from_pdf(pdf_path)
            message += f"\n\nEste es el contenido del PDF: \n{extracted[:2000]}"
        except Exception as e:
            return jsonify({"response": f"Error procesando el PDF: {e}"}), 500

    context.append({"role": "user", "content": message})
    context = context[-20:]

    try:
        reply = ask_openai(context)
    except Exception:
        reply = "Hubo un error al consultar la IA."

    context.append({"role": "assistant", "content": reply})
    save_context(user_id, context)

    return jsonify({"response": reply})
