// 🌐 URL dinámica (local o producción)
const API_BASE = window.location.hostname.includes("localhost") || window.location.hostname === "127.0.0.1"
  ? "http://127.0.0.1:5000"
  : "https://chatbot-backend-nqls.onrender.com";


let userId = null;
let temporizadorSesionId = null;

window.onload = () => {
  userId = localStorage.getItem("user_id");
  const cerrarBtn = document.getElementById("cerrar-sesion");
  const inicioSesion = localStorage.getItem("session_start");
  const ahora = Date.now();
  const duracionSesion = 10 * 60 * 1000; // 10 minutos

  if (userId && inicioSesion && (ahora - parseInt(inicioSesion, 10)) > duracionSesion) {
    alert("🔒 Tu sesión ha expirado por inactividad.");
    cerrarSesion(true);
    return;
  }

  if (userId) {
    userInput.disabled = true;
    enviarMensaje("__ping__");
    cerrarBtn.style.display = "inline-block";

    if (!inicioSesion) {
      localStorage.setItem("session_start", Date.now().toString());
    }

    iniciarTemporizadorSesion();
  } else {
    mostrarSolicitudCedula();
    userInput.disabled = true;
    cerrarBtn.style.display = "none";
  }
};

const chatOutput = document.getElementById("chat-output");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const fileInput = document.getElementById("file-input");
const pdfPreview = document.getElementById("pdf-preview");
const botAudio = document.getElementById("bot-audio");
const chatWrapper = document.querySelector('.chat-input-wrapper');
const removeFileBtn = document.getElementById("remove-file");

function mostrarNombreUsuario(nombre) {
  const nombreSpan = document.getElementById("nombre-usuario");
  const contenedor = document.getElementById("usuario-info");

  nombreSpan.textContent = `👤 Bienvenido, ${nombre}`;
  contenedor.style.display = "inline-flex";
}

function cerrarSesion(forzado = false) {
  if (!forzado) {
    const confirmar = confirm("¿Estás seguro de que quieres cerrar sesión?");
    if (!confirmar) return;
  }

  // Limpia datos de sesión
  localStorage.removeItem("user_id");
  localStorage.removeItem("nombre_usuario");
  localStorage.removeItem("session_start");
  localStorage.removeItem("politicas_aceptadas"); // ❗ Elimina la aceptación de políticas

  // 🧽 Limpiar el contador visual también
  const timerEl = document.getElementById("temporizador-sesion");
  if (timerEl) {
    timerEl.textContent = "";
    timerEl.classList.remove("alerta"); // si estaba en rojo
  }

  document.getElementById("usuario-info").style.display = "none";
  location.reload();
}

document.getElementById("cerrar-sesion").addEventListener("click", cerrarSesion);


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
  scrollChatToBottom();
}

function mostrarPoliticasDespuesDelNombre(callback = () => {}) {
  const politicas = document.createElement("div");
  politicas.className = "mensaje-bot fade-in";
  politicas.id = "politicas-box";

  politicas.innerHTML = `
    <p><strong>Antes de continuar</strong>, debes aceptar nuestras <strong>políticas de privacidad y uso del chatbot</strong>.</p>
    <p>Puedes revisarlas aquí 👉 
      <a href="https://www.dropbox.com/scl/fi/xm4upeyq8yjdf0l1ay3ig/POL-TICA-DE-PRIVACIDAD-Y-USO-DEL-CHATBOT-INNOVUG.pdf?rlkey=nztgunry3giz9eo285c24tk25&st=s7r9p3ow&dl=0" 
         target="_blank" rel="noopener noreferrer">
         Ver documento PDF
      </a>
    </p>
    <p>¿Aceptas continuar?</p>
    <button class="btn btn-sm btn-success mt-2" id="btn-aceptar-politicas">Aceptar</button>
    <button class="btn btn-sm btn-danger mt-2" id="btn-rechazar-politicas">Cancelar</button>
  `;

  chatOutput.appendChild(politicas);
  scrollChatToBottom();

  document.getElementById("btn-aceptar-politicas").addEventListener("click", () => {
    localStorage.setItem("politicas_aceptadas", "true");
    politicas.remove();
    addMessage("✅ Políticas aceptadas", "mensaje-usuario");
    callback();
  });

  document.getElementById("btn-rechazar-politicas").addEventListener("click", () => {
    fetch(`${API_BASE}/api/usuarios/${userId}`, { method: "DELETE" })
      .then(() => {
        localStorage.clear();
        politicas.innerHTML = "<p>❌ No puedes continuar si no aceptas las políticas. Tus datos han sido eliminados.</p>";
        userInput.disabled = true;
        fileInput.disabled = true;
        document.getElementById("cerrar-sesion").style.display = "inline-block";
      })
      .catch(err => {
        console.error("❌ Error eliminando datos:", err);
        politicas.innerHTML = "<p>❌ Ocurrió un error al eliminar los datos. Intenta de nuevo.</p>";
        userInput.disabled = true;
        fileInput.disabled = true;
        document.getElementById("cerrar-sesion").style.display = "inline-block";
      });
  });
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
  addMessage(`Cédula registrada: ${userId}`, "mensaje-usuario");

  const inputBox = input.closest(".mensaje-bot");
  if (inputBox) inputBox.remove();

  const yaTieneNombre = localStorage.getItem("nombre_usuario");

  enviarMensaje("__ping__"); // Verifica si ya tiene nombre

  // 🛠️ Si ya tiene nombre, iniciar sesión y temporizador
  if (yaTieneNombre) {
    localStorage.setItem("session_start", Date.now().toString());
    iniciarTemporizadorSesion();
    document.getElementById("cerrar-sesion").style.display = "inline-block";
  }
};

function iniciarTemporizadorSesion() {
  const timerEl = document.getElementById("temporizador-sesion");
  const duracionSesion = 10 * 60 * 1000;
  const aviso2Min = 2 * 60 * 1000;
  let yaPregunto = false;

  // ✅ Limpiar temporizador anterior si existe
  if (temporizadorSesionId) {
    clearTimeout(temporizadorSesionId);
    temporizadorSesionId = null;
  }

  function actualizarTemporizador() {
    const inicioStr = localStorage.getItem("session_start");
    if (!inicioStr) return;

    const inicio = parseInt(inicioStr, 10);
    const ahora = Date.now();
    const restante = duracionSesion - (ahora - inicio);

    if (restante <= 0) {
      alert("🔒 Tu sesión ha sido cerrada por inactividad.");
      cerrarSesion(true);  // ← Se cierra directamente, sin confirmar
      return;
    }

    const minutos = Math.floor(restante / 60000);
    const segundos = Math.floor((restante % 60000) / 1000);

    if (restante <= aviso2Min && !yaPregunto) {
      yaPregunto = true;

      const extender = confirm("⏳ Tu sesión está por expirar. ¿Deseas extenderla 10 minutos más?");
      if (extender) {
        localStorage.setItem("session_start", Date.now().toString());
        yaPregunto = false;
      } else {
        timerEl.classList.add("alerta");
      }
    }

    if (timerEl) {
      timerEl.textContent = `⏳ ${minutos}:${segundos.toString().padStart(2, "0")}`;
    }

    // ⏱️ Guardamos el ID para evitar duplicados
    temporizadorSesionId = setTimeout(actualizarTemporizador, 1000);
  }

  actualizarTemporizador();
}

window.guardarNombre = () => {
  const input = document.getElementById("nombre-input");
  const nombre = input.value.trim();

  if (nombre.split(" ").length < 2) {
    alert("Por favor ingresa tu nombre completo (nombre y apellido).");
    return;
  }

  addMessage(`Nombre registrado: ${nombre}`, "mensaje-usuario");

  const escribiendo = document.createElement("div");
  escribiendo.className = "mensaje-bot fade-in";
  escribiendo.id = "escribiendo";
  escribiendo.innerHTML = "<em>Escribiendo...</em>";
  chatOutput.appendChild(escribiendo);

  const formData = new FormData();
  formData.append("user_id", userId);
  formData.append("message", nombre);
  formData.append("etapa", "nombre");

  fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    body: formData,
  })
    .then((res) => res.json())
    .then((data) => {
      document.getElementById("escribiendo")?.remove();

      localStorage.setItem("nombre_usuario", nombre);
      localStorage.setItem("session_start", Date.now().toString());
      iniciarTemporizadorSesion();

      const yaAcepto = localStorage.getItem("politicas_aceptadas");

      if (!yaAcepto) {
        mostrarPoliticasDespuesDelNombre(() => {
          mostrarNombreUsuario(nombre);
          userInput.disabled = false;
          document.getElementById("cerrar-sesion").style.display = "inline-block";
          addMessage(`INNOVUG: ${marked.parse(data.response)}`, "mensaje-bot", true);
          botAudio.play();
        });
      } else {
        mostrarNombreUsuario(nombre);
        userInput.disabled = false;
        document.getElementById("cerrar-sesion").style.display = "inline-block";
        addMessage(`INNOVUG: ${marked.parse(data.response)}`, "mensaje-bot", true);
        botAudio.play();
      }
    })
    .catch((err) => {
      document.getElementById("escribiendo")?.remove();
      addMessage(`Error: ${err.message}`, "mensaje-bot");
    });

  const mensaje = input.closest(".mensaje-bot");
  if (mensaje) mensaje.remove();
};

function scrollChatToBottom() {
  chatOutput.scrollTop = chatOutput.scrollHeight;
}

function mostrarSolicitudNombre() {
  const mensajeNombre = document.createElement("div");
  mensajeNombre.className = "mensaje-bot fade-in";
  mensajeNombre.innerHTML = `
    <p>¡Gracias! Ahora, por favor ingresa tu <strong>nombre completo</strong>:</p>
    <input type="text" id="nombre-input" class="form-control mt-2" placeholder="Ej: Juan Pérez" />
    <button id="nombre-submit-btn" onclick="guardarNombre()">Guardar</button>
  `;
  chatOutput.appendChild(mensajeNombre);
  scrollChatToBottom();

  // Enfocar automáticamente el input
  setTimeout(() => {
    document.getElementById("nombre-input")?.focus();
  }, 100);
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];

  if (file && file.type === "application/pdf") {
    if (!userId || !/^\d{10}$/.test(userId)) {
      alert("Debes ingresar tu cédula antes de subir un archivo.");
      fileInput.value = null;
      pdfPreview.style.display = "none";
      pdfPreview.innerHTML = "";
      return;
    }

    const reader = new FileReader();
    reader.onload = function (e) {
      pdfPreview.style.display = "block";
      pdfPreview.innerHTML = `<embed src="${e.target.result}" type="application/pdf" />`;
    };
    reader.readAsDataURL(file);

    chatWrapper.classList.add("attached");
    userInput.disabled = true;
    userInput.value = "";
  } else {
    pdfPreview.style.display = "none";
    pdfPreview.innerHTML = "";
    chatWrapper.classList.remove("attached");
    userInput.disabled = false;
  }
});

if (removeFileBtn) {
  removeFileBtn.addEventListener("click", () => {
    pdfPreview.style.display = "none";
    pdfPreview.innerHTML = "";
    fileInput.value = null;
    chatWrapper.classList.remove("attached");
    userInput.disabled = false;
  });
}

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
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      body: formData
    });

    const data = await response.json();
    document.getElementById("escribiendo")?.remove();

    // 🔎 Si el mensaje fue __ping__, buscar el nombre en la respuesta
    if (message === "__ping__") {
      const nombreDetectado = data.nombre?.trim();

      if (nombreDetectado) {
        localStorage.setItem("nombre_usuario", nombreDetectado);
        mostrarNombreUsuario(nombreDetectado);
        userInput.disabled = false;
        document.getElementById("cerrar-sesion").style.display = "inline-block";

        // ✅ Corregido: iniciar temporizador al detectar nombre
        localStorage.setItem("session_start", Date.now().toString());
        iniciarTemporizadorSesion();
      }

      addMessage(`INNOVUG: ${marked.parse(data.response)}`, "mensaje-bot", true);
      return;
    }

    // 🧠 Procesamiento normal de otros mensajes
    addMessage(`INNOVUG: ${marked.parse(data.response)}`, "mensaje-bot", true);
    botAudio.play();

    // Detectar nombre en respuesta si aplica
    const match = data.response.match(/Hola de nuevo,\s*(.+?)!/i);
    if (match && match[1]) {
      const nombre = match[1].trim();
      localStorage.setItem("nombre_usuario", nombre);
      mostrarNombreUsuario(nombre);
    }

  } catch (err) {
    document.getElementById("escribiendo")?.remove();
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
  scrollChatToBottom();
}
