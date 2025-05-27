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
  } else {
    pdfPreview.style.display = "none";
    pdfPreview.innerHTML = "";
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
  if (!message && file) {
    message = "Analiza este archivo, por favor.";
  }

  if (message) addMessage(`Tú: ${message}`, "mensaje-usuario");
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
    addMessage(`INNOVUG: ${data.response}`, "mensaje-bot");
    botAudio.play();
  } catch (err) {
    addMessage(`Error: ${err.message}`, "mensaje-bot");
  }
});

function addMessage(text, clase) {
  const div = document.createElement("div");
  div.className = clase + " fade-in";
  const hora = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  div.innerHTML = `${text}<span class='timestamp'>${hora}</span>`;
  chatOutput.appendChild(div);
  chatOutput.scrollTop = chatOutput.scrollHeight;
}
