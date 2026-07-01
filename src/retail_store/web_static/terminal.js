const terminal = document.querySelector("#terminal");
const form = document.querySelector("#prompt-form");
const input = document.querySelector("#prompt-input");
const history = [];
let historyIndex = 0;
let running = false;

function appendLine(className, text) {
  const line = document.createElement("div");
  line.className = className;
  line.textContent = text;
  terminal.insertBefore(line, form);
  terminal.scrollTop = terminal.scrollHeight;
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
  input.style.overflowY = input.scrollHeight > 132 ? "auto" : "hidden";
}

async function runPrompt(prompt) {
  if (running || !prompt.trim()) return;
  running = true;
  history.push(prompt);
  historyIndex = history.length;
  appendLine("line command", `> ${prompt}`);
  input.value = "";
  resizeInput();
  input.disabled = true;
  form.classList.add("busy");

  try {
    const response = await fetch("/api/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const result = await response.json();
    appendLine("output", result.output || "No response.");
    if (result.exit) {
      appendLine("line muted", "Session ended. Refresh to start a new terminal view.");
    }
  } catch (error) {
    appendLine("output", `Unable to reach the retail agent: ${error.message}`);
  } finally {
    running = false;
    input.disabled = false;
    form.classList.remove("busy");
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  runPrompt(input.value);
});

input.addEventListener("input", resizeInput);

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    runPrompt(input.value);
    return;
  }
  if (event.key === "ArrowUp" && input.selectionStart === 0 && history.length) {
    event.preventDefault();
    historyIndex = Math.max(0, historyIndex - 1);
    input.value = history[historyIndex];
    resizeInput();
  }
  if (
    event.key === "ArrowDown" &&
    input.selectionStart === input.value.length &&
    history.length
  ) {
    event.preventDefault();
    historyIndex = Math.min(history.length, historyIndex + 1);
    input.value = history[historyIndex] || "";
    resizeInput();
  }
});

terminal.addEventListener("click", () => input.focus());
resizeInput();
