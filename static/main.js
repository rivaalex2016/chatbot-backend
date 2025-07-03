window.onload = () => {
  // 💥 Reiniciar sesión: forzar validación de cédula en cada recarga
  localStorage.removeItem("user_id");
  userId = null;
  mostrarSolicitudCedula();
  userInput.disabled = true;
};

let userId = null;

// 🌐 Elementos del DOM
const chatOutput = document.getElementById("chat-output");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const fileInput = document.getElementById("file-input");
const pdfPreview = document.getElementById("pdf-preview");
const botAudio = document.getElementById("bot-audio");
const chatWrapper = document.querySelector('.chat-input-wrapper');
const removeFileBtn = document.getElementById("remove-file");

function mostrarSolicitudCedula() {
  const bienvenida = document.createElement("div");
  bienvenida.className = "mensaje-bot fade-in";
  bienvenida.innerHTML = `
    <p><strong>Hola, soy INNOVUG 🤖</strong><br>Tu asistente para emprender con éxito.</p>
    <p>Para comenzar, por favor ingresa tu número de cédula:</p>
    <input type="text" id="cedula-input" class="form-control mt-2" maxlength="10" pattern="\\d{10}" placeholder="Ej: 0912345678">
    <button class="btn btn-sm btn-primary mt-2" onclick="guardarCedula()">Guardar</button>
  `;
  chatOutput.appendChild(bienvenida);
  chatOutput.scrollTop = chatOutput.scrollHeight;
}

window.guardarCedula = () => {
  const input = document.getElementById("cedula-input");
  const cedula = input.value.trim();
  if (!/^\d{10}$/.test(cedula)) {
    alert("Por favor ingresa una cédula válida de 10 dígitos.");
    return;
  }
  userId = cedula;
  localStorage.setItem("user_id", userId);
  userInput.disabled = false;
  addMessage(`Cédula registrada: ${userId}`, "mensaje-usuario");
  const inputBox = input.closest(".mensaje-bot");
  if (inputBox) inputBox.remove();

  enviarMensaje("");
};

function mostrarSolicitudNombre() {
  const mensajeNombre = document.createElement("div");
  mensajeNombre.className = "mensaje-bot fade-in";
  mensajeNombre.innerHTML = `
    <p>¡Gracias! Ahora, por favor ingresa tu <strong>nombre completo</strong>:</p>
    <input type="text" id="nombre-input" class="form-control mt-2" placeholder="Ej: Juan Pérez" />
    <button id="nombre-submit-btn" onclick="guardarNombre()">Guardar</button>
  `;
  chatOutput.appendChild(mensajeNombre);
  chatOutput.scrollTop = chatOutput.scrollHeight;
}

window.guardarNombre = () => {
  const input = document.getElementById("nombre-input");
  const nombre = input.value.trim();

  if (nombre.split(" ").length < 2) {
    alert("Por favor ingresa tu nombre completo (nombre y apellido).");
    return;
  }

  addMessage(`Nombre registrado: ${nombre}`, "mensaje-usuario");

  const formData = new FormData();
  formData.append("user_id", userId);
  formData.append("message", nombre);

  fetch("https://chatbot-backend-nqls.onrender.com/api/chat", {
    method: "POST",
    body: formData,
  })
    .then((res) => res.json())
    .then((data) => {
      addMessage(`INNOVUG: ${marked.parse(data.response)}`, "mensaje-bot", true);
      botAudio.play();
    })
    .catch((err) => {
      addMessage(`Error: ${err.message}`, "mensaje-bot");
    });

  const mensaje = input.closest(".mensaje-bot");
  if (mensaje) mensaje.remove();
};

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file && file.type === "application/pdf") {
    const reader = new FileReader();
    reader.onload = function (e) {
      pdfPreview.style.display = "block";
      pdfPreview.innerHTML = `<embed src="${e.target.result}" type="application/pdf" />`;
    };
    reader.readAsDataURL(file);
    userInput.disabled = true;
    userInput.value = "";
  } else {
    pdfPreview.style.display = "none";
    pdfPreview.innerHTML = "";
    userInput.disabled = false;
  }

  if (file) {
    chatWrapper.classList.add("attached");

    // ✅ Mostrar mensaje de archivo enviado
    addMessage(`Tú (archivo): ${file.name}`, "mensaje-usuario");

    // ✅ Enviar al backend
    enviarMensaje("", file);
  } else {
    chatWrapper.classList.remove("attached");
  }
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!userId || !/^\d{10}$/.test(userId)) {
    alert("Debes ingresar tu cédula antes de continuar.");
    return;
  }

  const message = userInput.value.trim();
  const file = fileInput.files[0];
  if (!message && !file) return;

  if (message) addMessage(`Tú: ${message}`, "mensaje-usuario");
  if (file) addMessage(`Tú (archivo): ${file.name}`, "mensaje-usuario");

  userInput.value = "";
  fileInput.value = "";
  chatWrapper.classList.remove("attached");
  pdfPreview.innerHTML = "";
  pdfPreview.style.display = "none";
  userInput.disabled = false;

  enviarMensaje(message, file);
});

async function enviarMensaje(message, file = null) {
  const formData = new FormData();
  formData.append("message", message);
  formData.append("user_id", userId);
  formData.append("manual_input", (!!message).toString());
  if (file) formData.append("pdf", file);

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
}

function addMessage(text, clase, isHtml = false) {
  const div = document.createElement("div");
  div.className = clase + " fade-in";
  const hora = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (isHtml) {
    div.innerHTML = `${text}<span class='timestamp'>${hora}</span>`;
    const links = div.querySelectorAll("a");
    links.forEach(link => {
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
    });

    if (
      clase === "mensaje-bot" &&
      text.toLowerCase().includes("por favor ingresa tu nombre completo")
    ) {
      setTimeout(() => mostrarSolicitudNombre(), 300);
    }

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
