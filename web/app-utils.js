"use strict";
// Modal genérico e utilidades partilhadas (texto, erros, escapes).
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

/* ---------------- Modal genérico ---------------- */
let modalOkHandler = null;
function showModal({ title, bodyHTML, onOk, okLabel, danger }) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHTML;
  modalOkHandler = onOk;
  const okBtn = $("#modal-ok");
  okBtn.textContent = okLabel || "Guardar";
  okBtn.classList.toggle("danger-btn", !!danger);
  $("#modal").classList.remove("hidden");
  okBtn.onclick = async () => {
    okBtn.disabled = true;
    let close = true;
    try { if (modalOkHandler) close = await modalOkHandler(); }
    finally { okBtn.disabled = false; }
    if (close !== false) hideModal();
  };
  const first = $("#modal-body").querySelector("input, select, textarea");
  if (first) first.focus();
}
function hideModal() {
  $("#modal").classList.add("hidden");
  $("#modal-body").innerHTML = "";
  $("#modal-ok").classList.remove("danger-btn");
  modalOkHandler = null;
}

/* ---------------- Utilidades ---------------- */
function autosize() {
  const t = el.composer;
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 180) + "px";
}
function showError(msg) {
  el.errorBox.textContent = msg || "Erro desconhecido.";
  el.errorBox.classList.remove("hidden");
}
function clearError() {
  el.errorBox.classList.add("hidden");
  el.errorBox.textContent = "";
}
// Converte os delimitadores de matemática do ChatGPT (\(…\) e \[…\]) para os de cifrão ($…$ e $$…$$),
// que o markdown não altera. Deixa o código intacto (não converte dentro de ``` … ``` nem de `…`), para
// não estragar um "$" ou "\(" que faça parte de código. Sem isto, o marked "come" o \( antes da KaTeX o ver.
function convertMathOutsideInlineCode(line) {
  let out = "";
  let i = 0;
  while (i < line.length) {
    if (line[i] === "`") {
      let j = i + 1;
      while (j < line.length && line[j] !== "`") j++;
      out += line.slice(i, Math.min(j + 1, line.length));
      i = j + 1;
    } else if (line[i] === "\\" && (line[i + 1] === "[" || line[i + 1] === "]")) {
      out += "$$";
      i += 2;
    } else if (line[i] === "\\" && (line[i + 1] === "(" || line[i + 1] === ")")) {
      out += "$";
      i += 2;
    } else {
      out += line[i];
      i += 1;
    }
  }
  return out;
}
function normalizeMathDelims(src) {
  const lines = String(src == null ? "" : src).split("\n");
  let inFence = false;
  let fence = "";
  for (let i = 0; i < lines.length; i++) {
    const mark = lines[i].match(/^\s*(```+|~~~+)/);
    if (mark) {
      if (!inFence) { inFence = true; fence = mark[1][0]; }
      else if (lines[i].trim().startsWith(fence)) { inFence = false; }
      continue;
    }
    if (!inFence) lines[i] = convertMathOutsideInlineCode(lines[i]);
  }
  return lines.join("\n");
}
function formatText(text) {
  text = normalizeMathDelims(text);
  try {
    if (window.marked && window.DOMPurify) {
      if (!window.__studioMarkedReady) {
        const renderer = new window.marked.Renderer();
        renderer.code = ({ text: code, lang }) => {
          const language = (lang || "").trim().split(/\s+/)[0];
          let highlighted;
          try {
            highlighted = language && window.hljs && window.hljs.getLanguage(language)
              ? window.hljs.highlight(code, { language }).value
              : window.hljs ? window.hljs.highlightAuto(code).value : esc(code);
          } catch (error) {
            highlighted = esc(code);
          }
          return `<pre class="code-block"><code class="hljs${language ? " language-" + esc(language) : ""}">${highlighted}</code><button class="copy-code" type="button" title="Copiar código">copiar</button></pre>`;
        };
        window.marked.setOptions({ renderer, gfm: true, breaks: true });
        window.__studioMarkedReady = true;
      }
      const clean = window.DOMPurify.sanitize(window.marked.parse(String(text == null ? "" : text)));
      const wrapper = document.createElement("div");
      wrapper.innerHTML = clean;
      wrapper.querySelectorAll("a").forEach((link) => {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      });
      return wrapper.innerHTML;
    }
  } catch (error) {
    /* usa o fallback abaixo */
  }
  let s = esc(text);
  s = s.replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="code-block"><code>${code}</code></pre>`);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  return `<div class="plain-text">${s}</div>`;
}

// Desenha a matemática em LaTeX (KaTeX) dentro de um elemento já com o HTML posto.
// Suporta $$…$$ e \[…\] (em bloco) e $…$ e \(…\) (em linha), como o ChatGPT. Não toca em código.
function renderMath(node) {
  if (!node || !window.renderMathInElement) return;
  try {
    window.renderMathInElement(node, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
    });
  } catch (error) {
    /* matemática malformada: deixa o texto como estava */
  }
}

async function copyCode(button) {
  const pre = button.closest("pre");
  const text = pre?.querySelector("code")?.innerText || pre?.innerText || "";
  try {
    await navigator.clipboard.writeText(text);
    setStatusMessage("Código copiado.");
  } catch (error) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    setStatusMessage("Código copiado.");
  }
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
