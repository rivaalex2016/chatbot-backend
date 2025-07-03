const chatOutput = document.getElementById("chat-output");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const fileInput = document.getElementById("file-input");
const pdfPreview = document.getElementById("pdf-preview");
const botAudio = document.getElementById("bot-audio");
const chatWrapper = document.querySelector('.chat-input-wrapper');
const removeFileBtn = document.getElementById("remove-file");

let userId = localStorage.getItem("user_id");

// 🚀 Mostrar bienvenida inicial
if (!userId) {
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
  userInput.disabled = true;
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
  if (file) chatWrapper.classList.add("attached");
  else chatWrapper.classList.remove("attached");
});

removeFileBtn.addEventListener("click", () => {
  fileInput.value = "";
  chatWrapper.classList.remove("attached");
  pdfPreview.innerHTML = "";
  pdfPreview.style.display = "none";
  userInput.disabled = false;
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!userId || !/^\d{10}$/.test(userId)) {
    alert("Debes ingresar tu cédula antes de continuar.");
    return;
  }

  let message = userInput.value.trim();
  const file = fileInput.files[0];

  if (!message && !file) return;

  const isManualInput = Boolean(message);

  if (isManualInput) addMessage(`Tú: ${message}`, "mensaje-usuario");
  if (file) addMessage(`Tú (archivo): ${file.name}`, "mensaje-usuario");

  userInput.value = "";
  fileInput.value = "";
  chatWrapper.classList.remove("attached");
  pdfPreview.innerHTML = "";
  pdfPreview.style.display = "none";
  userInput.disabled = false;

  const formData = new FormData();
  formData.append("message", message);
  formData.append("user_id", userId);
  formData.append("manual_input", isManualInput.toString());

  if (file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (ext === "pdf") formData.append("pdf", file);
    else if (ext === "csv") formData.append("csv", file);
    else if (ext === "xlsx") formData.append("xlsx", file);
  }

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
    const links = div.querySelectorAll("a");
    links.forEach(link => {
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
    });
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
