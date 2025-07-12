import os
import re
import logging
import pdfplumber
import openai
import psycopg2
import pandas as pd
import hashlib
import unicodedata
from datetime import datetime
from dotenv import load_dotenv
from difflib import SequenceMatcher
from flask import Blueprint, request, jsonify
from openai.error import RateLimitError

chat_blueprint = Blueprint('chat', __name__)

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

def guardar_mensaje(user_identity, role, content):
    try:
        # ⛑️ Asegurar que el usuario exista antes de insertar en chat_history
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE identity = %s", (user_identity,))
        exists = cur.fetchone()
        if not exists:
            cur.execute("INSERT INTO users (identity, full_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_identity, None))
            conn.commit()
        # Guardar el mensaje
        cur.execute("""
            INSERT INTO chat_history (user_identity, role, content, timestamp)
            VALUES (%s, %s, %s, %s)
        """, (user_identity, role, content, datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando mensaje en DB: {e}")

def generar_hash_pdf(texto):
    # 1. Quitar acentos y tildes
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")

    # 2. Convertir a minúsculas
    texto = texto.lower()

    # 3. Eliminar signos de puntuación y caracteres no alfanuméricos
    texto = re.sub(r"[^a-z0-9\s]", "", texto)

    # 4. Reemplazar múltiples espacios por uno solo
    texto = re.sub(r"\s+", " ", texto)

    # 5. Strip final
    texto = texto.strip()

    # 6. Generar hash
    return hashlib.md5(texto.encode()).hexdigest()

def cargar_historial_por_identity(user_identity):
    historial = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT role, content
            FROM chat_history
            WHERE user_identity = %s
            ORDER BY timestamp ASC
        """, (user_identity,))
        for row in cur.fetchall():
            historial.append({"role": row[0], "content": row[1]})
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error cargando historial desde DB: {e}")
    return historial

def get_user_name(user_identity):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT full_name FROM users WHERE identity = %s", (user_identity,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logging.error(f"❌ Error buscando nombre del usuario: {e}")
        return None

def set_user_name(user_identity, full_name):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (identity, full_name)
            VALUES (%s, %s)
            ON CONFLICT (identity) DO UPDATE SET full_name = EXCLUDED.full_name
        """, (user_identity, full_name))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Error guardando nombre del usuario: {e}")

def extraer_datos_pdf_con_ia(texto, user_identity):
    try:
        system_prompt = (
            "Eres un asistente que extrae datos estructurados desde un texto escaneado de un formulario de emprendimiento. "
            "Devuelve un objeto JSON válido, usando comillas dobles (\"), sin texto adicional. "
            "Debes incluir todos los campos obligatorios de la base de datos, y además generar una evaluación técnica y objetiva "
            "del emprendimiento basada en el contenido, y calcular un promedio numérico entre 0 y 10. El formato exacto es:\n\n"
            "{\n"
            "  \"nombres\": \"\",\n"
            "  \"apellidos\": \"\",\n"
            "  \"cedula\": \"\",\n"
            "  \"facultad\": \"\",\n"
            "  \"carrera\": \"\",\n"
            "  \"numero_de_telefono\": \"\",\n"
            "  \"correo_electronico\": \"\",\n"
            "  \"semestre_que_cursa\": \"\",\n"
            "  \"equipo_integrantes\": [\n"
            "    { \"nombres\": \"\", \"apellidos\": \"\", \"cedula\": \"\", \"rol\": \"\", \"funcion\": \"\" }\n"
            "  ],\n"
            "  \"nombre_del_negocio\": \"\",\n"
            "  \"problema_y_solucion\": \"\",\n"
            "  \"mercado\": \"\",\n"
            "  \"competencia\": \"\",\n"
            "  \"modelo_de_negocio\": \"\",\n"
            "  \"escalabilidad\": \"\",\n"
            "  \"evaluacion\": \"Tu resumen evaluativo detallado aquí...\",\n"
            "  \"promedio_evaluacion\": 0.0\n"
            "}\n\n"
            "La evaluación debe tener lenguaje técnico, claro y profesional. El promedio es un valor decimal entre 0 y 10, basado en 6 criterios: "
            "problema/solución, mercado, competencia, modelo de negocio, escalabilidad y equipo."
        )

        mensajes = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Texto extraído del PDF del usuario {user_identity}:\n{texto}"}
        ]

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=mensajes,
            temperature=0.3,
        )

        import json
        raw_json = response.choices[0].message['content']
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as e:
            logging.error(f"❌ JSON inválido de OpenAI:\n{raw_json}")
            raise e

    except Exception as e:
        logging.error(f"❌ Error en extraer_datos_pdf_con_ia: {e}")
        return {}

def upsert_pdf_data(user_identity, datos, respuesta_ia, hash_pdf):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Paso 1: Insertar proyecto
        cur.execute("""
            INSERT INTO projects (
                user_identity, nombre_del_negocio, problema_y_solucion,
                mercado, competencia, modelo_de_negocio, escalabilidad
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id_version;
        """, (
            user_identity,
            datos.get("nombre_del_negocio"),
            datos.get("problema_y_solucion"),
            datos.get("mercado"),
            datos.get("competencia"),
            datos.get("modelo_de_negocio"),
            datos.get("escalabilidad")
        ))
        project_id_version = cur.fetchone()[0]

        # Paso 2: Insertar líder del proyecto
        cur.execute("""
            INSERT INTO lider_proyecto (
                project_id_version, nombres, apellidos, cedula, facultad, carrera,
                numero_telefono, correo_electronico, semestre_que_cursa
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            project_id_version,
            datos.get("nombres"),
            datos.get("apellidos"),
            datos.get("cedula"),
            datos.get("facultad"),
            datos.get("carrera"),
            datos.get("numero_de_telefono"),
            datos.get("correo_electronico"),
            datos.get("semestre_que_cursa")
        ))

        # Paso 3: Insertar integrantes del equipo
        for integrante in datos.get("equipo_integrantes", []):
            cur.execute("""
                INSERT INTO integrantes_equipo (
                    project_id_version, nombres, apellidos, cedula, rol, funcion
                ) VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                project_id_version,
                integrante.get("nombres"),
                integrante.get("apellidos"),
                integrante.get("cedula"),
                integrante.get("rol"),
                integrante.get("funcion")
            ))

        # Paso 4: Extraer promedio desde la respuesta IA
        match = re.search(r"promedio\s*final.*?=\s*(\d+(?:[.,]\d+)?)", respuesta_ia.lower())
        if match:
            try:
                promedio = float(match.group(1).replace(",", "."))
                promedio = round(promedio, 2)
                if not 0 <= promedio <= 10:
                    promedio = 0.0
                    logging.warning(f"⚠️ Promedio fuera de rango, se fuerza a 0.0: {match.group(1)}")
            except ValueError:
                promedio = 0.0
                logging.warning("⚠️ Promedio extraído no convertible a float.")
        else:
            promedio = 0.0
            logging.warning("⚠️ No se encontró el promedio en la respuesta IA.")

        logging.info(f"ℹ️ Promedio evaluado para user {user_identity}: {promedio}")

        # Paso 5: Insertar evaluación con hash
        cur.execute("""
            INSERT INTO evaluaciones (
                project_id_version, detalle, proposal_status, promedio_evaluacion, hash_pdf
            ) VALUES (%s, %s, %s, %s, %s);
        """, (
            project_id_version,
            respuesta_ia,
            "pendiente_aprobacion_chatbot",
            promedio,
            hash_pdf
        ))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        logging.error(f"❌ Error en upsert_pdf_data: {e}")

def compare_pdfs(reference_text, uploaded_text):
    similarity = SequenceMatcher(None, reference_text, uploaded_text).ratio() * 100
    return 5 < similarity < 90

def extract_text_from_pdf(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            texto = "\n".join(page.extract_text() or "" for page in pdf.pages).strip().lower()
            return texto
    except Exception as e:
        logging.error(f"❌ Error extrayendo texto del PDF: {e}")
        return ""

def openai_IA(contexto):
    try:
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=contexto,
            temperature=0.4
        )
        return response.choices[0].message['content']
    except RateLimitError:
        return "⚠️ Se alcanzó el límite de velocidad de OpenAI. Intenta nuevamente en unos segundos."
    except Exception as e:
        logging.error(f"❌ Error en openai_IA: {e}")
        return "❌ Hubo un problema al procesar tu mensaje con la IA."

@chat_blueprint.route('/chat', methods=['POST'])
def chat():
    try:
        user_identity = request.form.get("user_id") or request.form.get("identity") or "default_user"
        user_message = request.form.get("message", "").strip()
        etapa = request.form.get("etapa", "").strip().lower()
        pdf_file = request.files.get("pdf")

        user_name = get_user_name(user_identity)

        if user_message == "__ping__":
            saludo = f"👋 ¡Hola de nuevo, {user_name}! ¿En qué puedo ayudarte hoy?" if user_name else "👋 ¡Hola! Antes de continuar, por favor ingresa tu nombre completo:"
            user_contexts.setdefault(user_identity, []).append({"role": "assistant", "content": saludo})
            guardar_mensaje(user_identity, "assistant", saludo)
            return jsonify({"response": saludo, "nombre": user_name} if user_name else {"response": saludo})

        if etapa == "nombre" and user_message:
            set_user_name(user_identity, user_message.title())
            saludo = f"¡Gracias {user_message.title()}! Ahora puedes escribir tu mensaje o subir tu archivo PDF 📄"
            user_contexts.setdefault(user_identity, []).append({"role": "assistant", "content": saludo})
            guardar_mensaje(user_identity, "assistant", saludo)
            return jsonify({"response": saludo})

        if user_identity not in user_contexts:
            user_contexts[user_identity] = cargar_historial_por_identity(user_identity)

        # Inyectar resumen del último proyecto si existe
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT p.nombre_del_negocio, p.problema_y_solucion, p.mercado, p.competencia,
                       p.modelo_de_negocio, p.escalabilidad,
                       l.nombres, l.apellidos, l.cedula, l.facultad, l.carrera,
                       l.numero_telefono, l.correo_electronico, l.semestre_que_cursa
                FROM projects p
                JOIN lider_proyecto l ON p.id_version = l.project_id_version
                WHERE p.user_identity = %s
                ORDER BY p.created_at DESC
                LIMIT 1
            """, (user_identity,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                campos = [
                    "Nombre del negocio", "Problema y solución", "Mercado", "Competencia",
                    "Modelo de negocio", "Escalabilidad",
                    "Nombres", "Apellidos", "Cédula", "Facultad", "Carrera",
                    "Número de teléfono", "Correo electrónico", "Semestre que cursa"
                ]
                resumen_usuario = "\n".join(f"{campo}: {valor}" for campo, valor in zip(campos, row) if valor)
                user_contexts[user_identity].insert(1, {
                    "role": "user",
                    "content": f"📄 Información registrada del usuario:\n{resumen_usuario}"
                })
        except Exception as e:
            logging.warning(f"⚠️ No se pudo inyectar resumen del proyecto: {e}")

        # Cargar historial reciente si no está
        try:
            historial_db = cargar_historial_por_identity(user_identity)[-MAX_CONTEXT_LENGTH:]
            for m in historial_db:
                if m not in user_contexts[user_identity]:
                    user_contexts[user_identity].append(m)
        except Exception as e:
            logging.warning(f"⚠️ No se pudo cargar historial de chat: {e}")

        if not user_name:
            bienvenida = "👋 ¡Hola! Soy INNOVUG, tu asistente virtual 🤖\n\nPara comenzar, por favor ingresa tu nombre completo:"
            user_contexts[user_identity].append({"role": "assistant", "content": bienvenida})
            guardar_mensaje(user_identity, "assistant", bienvenida)
            return jsonify({"response": bienvenida})

        # Procesamiento de PDF
        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                uploaded_text = extract_text_from_pdf(pdf_file)
                if not compare_pdfs(REFERENCE_TEXT, uploaded_text):
                    return jsonify({"response": (
                        "📄 El archivo enviado no parece una propuesta válida. Por favor, descarga el formato oficial desde: "
                        "<a href='https://www.dropbox.com/scl/fi/zuibj62g5wjsdzcovf4pb/FICHA-DE-EMPRENDEDORES_NOMBRE-NEGOCIO.docx?rlkey=sec681vbpcthobyjvzqacs084&st=wwpcxlje&dl=0' target='_blank'>Formato Propuesta WORD</a>"
                    )})

                # Calcular hash del texto
                hash_pdf = generar_hash_pdf(uploaded_text)

                # Buscar evaluación previa
                try:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT e.detalle
                        FROM evaluaciones e
                        JOIN projects p ON p.id_version = e.project_id_version
                        WHERE p.user_identity = %s AND e.hash_pdf = %s
                        ORDER BY e.created_at DESC
                        LIMIT 1
                    """, (user_identity, hash_pdf))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()

                    if row:
                        logging.info("📄 Reutilizando evaluación previa por hash.")
                        guardar_mensaje(user_identity, 'assistant', row[0])
                        return jsonify({"response": row[0]})

                except Exception as e:
                    logging.warning(f"⚠️ No se pudo verificar hash en BD: {e}")

                # Evaluar nuevo PDF
                datos_extraidos = extraer_datos_pdf_con_ia(uploaded_text, user_identity)
                datos_extraidos["cedula"] = datos_extraidos.get("cedula")
                datos_extraidos["identity"] = user_identity

                user_contexts[user_identity].append({'role': 'user', 'content': f"DATOS EXTRAÍDOS DEL PDF:\n{uploaded_text}"})
                guardar_mensaje(user_identity, 'user', uploaded_text)

                if SYSTEM_PROMPT and not any(m['role'] == 'system' for m in user_contexts[user_identity]):
                    user_contexts[user_identity].insert(0, {'role': 'system', 'content': SYSTEM_PROMPT})

                respuesta = openai_IA(user_contexts[user_identity])
                user_contexts[user_identity].append({'role': 'assistant', 'content': respuesta})
                guardar_mensaje(user_identity, 'assistant', respuesta)

                # Guardar en BD con hash
                upsert_pdf_data(user_identity, datos_extraidos, respuesta, hash_pdf)

                return jsonify({"response": respuesta})

            except Exception as e:
                logging.error(f"❌ Error procesando PDF: {e}")
                return jsonify({"response": f"Error procesando PDF: {str(e)}"})

        # Procesamiento de texto normal
        if user_message:
            user_contexts[user_identity].append({'role': 'user', 'content': user_message})
            guardar_mensaje(user_identity, 'user', user_message)

        if SYSTEM_PROMPT and not any(m['role'] == 'system' for m in user_contexts[user_identity]):
            user_contexts[user_identity].insert(0, {'role': 'system', 'content': SYSTEM_PROMPT})

        respuesta = openai_IA(user_contexts[user_identity])
        user_contexts[user_identity].append({'role': 'assistant', 'content': respuesta})
        guardar_mensaje(user_identity, 'assistant', respuesta)

        return jsonify({"response": respuesta})

    except Exception as e:
        logging.error(f"❌ Error general en /chat: {str(e)}")
        return jsonify({"response": "Error interno del servidor"}), 500
