const chatOutput = document.getElementById("chat-output");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const fileInput = document.getElementById("file-input");
const userIdInput = document.getElementById("user-id");
const pdfPreview = document.getElementById("pdf-preview");
const botAudio = document.getElementById("bot-audio");
const chatWrapper = document.querySelector('.chat-input-wrapper');
const removeFileBtn = document.getElementById("remove-file");

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file && file.type === "application/pdf") {
    const reader = new FileReader();
    reader.onload = function (e) {
      pdfPreview.style.display = "block";
      pdfPreview.innerHTML = `<embed src="${e.target.result}" type="application/pdf" />`;
    };
    reader.readAsDataURL(file);

    userInput.disabled = true; // 🚫 bloquea input
  } else {
    pdfPreview.style.display = "none";
    pdfPreview.innerHTML = "";
    userInput.disabled = false; // ✅ vuelve a habilitar
  }

  if (file) {
    chatWrapper.classList.add("attached");
  } else {
    chatWrapper.classList.remove("attached");
  }
});

removeFileBtn.addEventListener("click", () => {
  fileInput.value = "";
  chatWrapper.classList.remove("attached");
  pdfPreview.innerHTML = "";
  pdfPreview.style.display = "none";
  userInput.disabled = false; // ✅ Rehabilita input
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  let message = userInput.value.trim();
  const file = fileInput.files[0];
  const userId = userIdInput.value.trim();

  if (!userId || !/^\d{10}$/.test(userId)) {
    alert("Por favor ingresa un No. Cédula válido de 10 dígitos.");
    return;
  }

  if (!message && !file) return;

let ocultarMensaje = false;

if (!message && file) {
  message = `Evalúa esta propuesta de emprendimiento con base en los siguientes criterios:
  
1. Problema / Solución
2. Mercado
3. Competencia
4. Modelo de negocio
5. Escalabilidad
6. Equipo

Para cada criterio, asigna una calificación:
- Inicial (2 puntos)
- En desarrollo (5 puntos)
- Desarrollado (8 puntos)
- Excelencia (10 puntos)

📋 Muestra los resultados en una tabla con tres columnas: Criterio, Calificación, y Justificación breve.

📊 Calcula el promedio total de calificación sobre 10 (suma de puntajes dividido para 6).

🔔 Según la calificación final:
- Si es exactamente 10, responde únicamente:
🏆 La propuesta ha alcanzado la calificación perfecta de 10/10. No se requieren recomendaciones.
- Si está entre 8 y 9.9, agrega el emoji 👍 al promedio y brinda 5 recomendaciones breves para alcanzar la excelencia.
- Si está entre 5 y 7.9, agrega ⚠️ y proporciona 5 recomendaciones claras para fortalecerla.
- Si es menor a 5, agrega ❗ y proporciona 5 sugerencias urgentes para replantearla.

🎯 Las recomendaciones deben ser útiles, prácticas y accionables. Usa viñetas o emojis para destacarlas.

Responde como un evaluador experto del Centro de Emprendimiento INNOVUG.`;

  ocultarMensaje = true;
}


  if (message && !ocultarMensaje) addMessage(`Tú: ${message}`, "mensaje-usuario");
  if (file) addMessage(`Tú (archivo): ${file.name}`, "mensaje-usuario");

  userInput.value = "";
  fileInput.value = "";
  chatWrapper.classList.remove("attached");
  pdfPreview.innerHTML = "";
  pdfPreview.style.display = "none";

  const formData = new FormData();
  formData.append("message", message);
  formData.append("user_id", userId);
  if (file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (ext === "pdf") formData.append("pdf", file);
    else if (ext === "csv") formData.append("csv", file);
    else if (ext === "xlsx") formData.append("xlsx", file);
  }
formData.append("manual_input", (!ocultarMensaje).toString());


  const escribiendo = document.createElement("div");
  escribiendo.className = "mensaje-bot fade-in";
  escribiendo.id = "escribiendo";
  escribiendo.innerHTML = "<em>Escribiendo...</em>";
  chatOutput.appendChild(escribiendo);

  try {
    const response = await fetch("https://chatbot-backend-nqls.onrender.com/api/chat", {
      method: "POST",
      body: formData
    });
    const data = await response.json();
    document.getElementById("escribiendo").remove();
    addMessage(`INNOVUG: ${marked.parse(data.response)}`, "mensaje-bot", true);
    botAudio.play();
  } catch (err) {
    addMessage(`Error: ${err.message}`, "mensaje-bot");
  }
});

function addMessage(text, clase, isHtml = false) {
  const div = document.createElement("div");
  div.className = clase + " fade-in";
  const hora = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (isHtml) {
    div.innerHTML = `${text}<span class='timestamp'>${hora}</span>`;
  } else {
    div.textContent = `${text}`;
    const span = document.createElement("span");
    span.className = "timestamp";
    span.textContent = hora;
    div.appendChild(span);
  }

  chatOutput.appendChild(div);
  chatOutput.scrollTop = chatOutput.scrollHeight;
}

