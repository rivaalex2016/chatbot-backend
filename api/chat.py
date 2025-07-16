import os
import re
import logging
import pdfplumber
import openai
import json
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

def extraer_datos_structurados_desde_texto(texto):
    import json

    prompt = """
    Eres un asistente que extrae datos estructurados de propuestas de emprendimiento. Devuelve un JSON con este formato exacto:

    {
    "nombre_del_negocio": "...",
    "problema_y_solucion": "...",
    "mercado": "...",
    "competencia": "...",
    "modelo_de_negocio": "...",
    "escalabilidad": "...",
    "nombres": "...",
    "apellidos": "...",
    "cedula": "...",
    "facultad": "...",
    "carrera": "...",
    "numero_de_telefono": "...",
    "correo_electronico": "...",
    "semestre_que_cursa": "...",
    "equipo_integrantes": [
        {
        "nombres": "...",
        "apellidos": "...",
        "cedula": "...",
        "rol": "...",
        "funcion": "..."
        }
    ]
    }

    Devuelve únicamente el JSON sin texto adicional ni explicaciones.
    """

    mensajes = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": texto}
    ]

    response = openai.ChatCompletion.create(
        model=MODEL,
        messages=mensajes,
        temperature=0.2,
    )

    raw = response.choices[0].message['content'].strip()

    # 🔧 Eliminar envoltura de bloque de código si existe
    if raw.startswith("```") and raw.endswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    # 🔍 Log opcional para depurar
    logging.debug(f"📤 Contenido limpiado para json.loads:\n{raw}")

    if not raw:
        raise ValueError("❌ Respuesta de OpenAI vacía")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON inválido después de limpiar:\n{raw}")
        raise e

def evaluar_propuesta_con_ia(texto):
    mensajes = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Texto extraído del PDF:\n{texto}"}
    ]
    response = openai.ChatCompletion.create(
        model=MODEL,
        messages=mensajes,
        temperature=0.3,
    )
    return response.choices[0].message['content']

def upsert_pdf_data(user_identity, datos, hash_pdf):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        print("🟢 Iniciando inserción de datos desde PDF...")

        # Asegurar campos del proyecto
        campos_proyecto = [
            "nombre_del_negocio", "problema_y_solucion", "mercado",
            "competencia", "modelo_de_negocio", "escalabilidad"
        ]
        for campo in campos_proyecto:
            datos[campo] = datos.get(campo, "") or ""

        # 1. Insertar en `projects`
        cur.execute("""
            INSERT INTO projects (
                user_identity, nombre_del_negocio, problema_y_solucion,
                mercado, competencia, modelo_de_negocio, escalabilidad
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id_version;
        """, (
            user_identity,
            datos["nombre_del_negocio"],
            datos["problema_y_solucion"],
            datos["mercado"],
            datos["competencia"],
            datos["modelo_de_negocio"],
            datos["escalabilidad"]
        ))
        project_id = cur.fetchone()[0]
        print("✅ Proyecto insertado. ID:", project_id)

        # 2. Insertar en `lider_proyecto`
        campos_lider = [
            "nombres", "apellidos", "cedula", "facultad",
            "carrera", "numero_de_telefono", "correo_electronico", "semestre_que_cursa"
        ]
        for campo in campos_lider:
            datos[campo] = datos.get(campo, "") or ""

        cur.execute("""
            INSERT INTO lider_proyecto (
                project_id_version, nombres, apellidos, cedula,
                facultad, carrera, numero_telefono, correo_electronico, semestre_que_cursa
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            project_id,
            datos["nombres"],
            datos["apellidos"],
            datos["cedula"],
            datos["facultad"],
            datos["carrera"],
            datos["numero_de_telefono"],
            datos["correo_electronico"],
            datos["semestre_que_cursa"]
        ))
        print("✅ Líder del proyecto insertado.")

        # 3. Insertar en `integrantes_equipo`
        integrantes = datos.get("equipo_integrantes", [])
        for integrante in integrantes:
            for campo in ["nombres", "apellidos", "cedula", "rol", "funcion"]:
                integrante[campo] = integrante.get(campo, "") or ""

            cur.execute("""
                INSERT INTO integrantes_equipo (
                    project_id_version, nombres, apellidos, cedula, rol, funcion
                ) VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                project_id,
                integrante["nombres"],
                integrante["apellidos"],
                integrante["cedula"],
                integrante["rol"],
                integrante["funcion"]
            ))
        print(f"✅ {len(integrantes)} integrantes insertados.")

        # 4. Extraer promedio de evaluación y estado
        match = re.search(r"promedio\s*final.*?=\s*(\d+(?:[.,]\d+)?)", respuesta_ia.lower())
        promedio = 0.0
        if match:
            try:
                promedio = float(match.group(1).replace(",", "."))
                promedio = round(promedio, 2)
                if not (0 <= promedio <= 10):
                    promedio = 0.0
            except:
                promedio = 0.0

        estado = "aprobado_chatbot" if promedio >= 8 else "pendiente_aprobacion_chatbot"

        # 5. Insertar en `evaluaciones`
        cur.execute("""
            INSERT INTO evaluaciones (
                project_id_version, detalle, promedio_evaluacion, hash_pdf, proposal_status
            ) VALUES (%s, %s, %s, %s, %s);
        """, (
            project_id,
            respuesta_ia,
            promedio,
            hash_pdf,
            estado
        ))
        print("✅ Evaluación insertada con promedio:", promedio, "y estado:", estado)

        conn.commit()
        cur.close()
        conn.close()
        print("✅ Todos los datos guardados correctamente.")

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
            saludo = (
                f"¡Hola de nuevo, {user_name}! 👋\n\n"
                "🙌 Ya estás registrado en el sistema.\n\n"
                "**¿Qué deseas hacer hoy?**\n\n"
                "➡️  *Hacer preguntas sobre INNOVUG*❓\n\n"
                "➡️  *Subir una nueva propuesta en PDF para ser evaluada*📄\n\n"
                "_Estoy listo para ayudarte 😊_"
            ) if user_name else "👋 ¡Hola! Antes de continuar, por favor ingresa tu nombre completo:"
            user_contexts.setdefault(user_identity, []).append({"role": "assistant", "content": saludo})
            guardar_mensaje(user_identity, "assistant", saludo)
            return jsonify({"response": saludo, "nombre": user_name} if user_name else {"response": saludo})

        if etapa == "nombre" and user_message:
            set_user_name(user_identity, user_message.title())
            saludo = (
                f"¡Perfecto, {user_message.title()}! 👋\n\n"
                "✅ Ya estás registrado correctamente.\n\n"
                "**Ahora puedes elegir:**\n\n"
                "➡️  *Hacer preguntas sobre INNOVUG*❓\n\n"
                "➡️  *Subir tu propuesta en PDF para que la analice y la evalúe con criterios técnicos📄*\n\n"
                "_¿Con qué te gustaría empezar?_"
            )
            user_contexts.setdefault(user_identity, []).append({"role": "assistant", "content": saludo})
            guardar_mensaje(user_identity, "assistant", saludo)
            return jsonify({"response": saludo})

        if user_identity not in user_contexts:
            user_contexts[user_identity] = cargar_historial_por_identity(user_identity)

        # Procesamiento de PDF
        if pdf_file and pdf_file.filename.endswith(".pdf"):
            try:
                uploaded_text = extract_text_from_pdf(pdf_file)
                logging.debug(f"📄 Texto extraído del PDF:\n{uploaded_text[:1000]}...")
                if not compare_pdfs(REFERENCE_TEXT, uploaded_text):
                    return jsonify({"response": (
                        "📄 El archivo enviado no parece una propuesta válida. Por favor, descarga el formato oficial desde: "
                        "<a href='https://www.dropbox.com/scl/fi/zuibj62g5wjsdzcovf4pb/FICHA-DE-EMPRENDEDORES_NOMBRE-NEGOCIO.docx?rlkey=sec681vbpcthobyjvzqacs084&st=wwpcxlje&dl=0' target='_blank'>Formato Propuesta WORD</a>"
                    )})

                hash_pdf = generar_hash_pdf(uploaded_text)

                # Verificar si ya fue evaluado
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

                # 🚀 NUEVO FLUJO: extracción separada
                datos_extraidos = extraer_datos_structurados_desde_texto(uploaded_text)
                logging.debug(f"🧾 JSON extraído del PDF:\n{json.dumps(datos_extraidos, indent=2, ensure_ascii=False)}")

                # ✅ Validar que al menos el líder esté presente
                if not all([
                    datos_extraidos.get("nombres", "").strip(),
                    datos_extraidos.get("apellidos", "").strip(),
                    datos_extraidos.get("cedula", "").strip()
                ]):
                    return jsonify({
                        "response": (
                            "❌ La propuesta está incompleta.\n\n"
                            "Para poder evaluarla, asegúrate de que el líder del proyecto tenga al menos:\n"
                            "- Nombres\n- Apellidos\n- Cédula\n\n"
                            "Por favor, corrige el documento y vuelve a intentarlo."
                        )
                    })

                respuesta_evaluacion = evaluar_propuesta_con_ia(uploaded_text)

                # Guardar en base de datos
                upsert_pdf_data(user_identity, datos_extraidos, respuesta_evaluacion, hash_pdf)

                user_contexts[user_identity].append({'role': 'assistant', 'content': respuesta_evaluacion})
                guardar_mensaje(user_identity, 'assistant', respuesta_evaluacion)

                return jsonify({"response": respuesta_evaluacion})

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
