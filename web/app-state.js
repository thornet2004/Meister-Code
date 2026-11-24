"use strict";
// Estado global da interface, atalhos do DOM e ponte com o Python (call).
// Script clássico: partilha o âmbito global com os outros ficheiros app-*.js (ver index.html).

const TYPES = ["chat", "image", "video", "audio"];
const TYPE_LABEL = { chat: "Chat", image: "Imagem", video: "Vídeo", audio: "Áudio" };

const state = {
  providers: [],
  projects: [],
  activeProjectId: "",
  conversations: [],
  activeConversationId: "",
  kinds: [],
  kindCaps: {},
  kindDetails: {},
  selections: { chat: {}, image: {}, video: {}, audio: {} },
  preferences: {},
  outputDir: "",
  configPath: "",
  projectsRoot: "",
  conversationsRoot: "",
};

let pendingAttachments = []; // {name, mime, b64, isImage, previewUrl}
let attachmentReads = 0;
let chatBusy = false;
let compacting = false;
let terminalBusy = false;
let terminalCursor = 0;      // posição já lida da saída do terminal
let terminalPolling = false;
const terminalHistory = [];
let terminalHistoryIndex = 0;
let browserOpen = false;
let browserNavigated = false;
let browserPoll = null;
let chatStreamEl = null;
let chatStreamText = "";
let contextUsage = null;
let contextWarningDismissed = false;
let sidebarQuery = "";
let lastDraftKey = null;
let paletteItems = [];
let paletteIndex = 0;
let paletteToken = 0;
let slashItems = [];
let slashIndex = 0;
let browserStateBusy = false;
const mediaCache = new Map(); // path -> dataURL
const catalogSyncAttempted = new Set();
const catalogLabels = {chat:"Chat",code:"Código",image:"Imagem",video:"Vídeo",audio:"Áudio / voz",transcription:"Transcrição",embeddings:"Embeddings",rerank:"Reranking",decisions:"Decisões",other:"Outros"};
let modelPickerBusy = false;

const $ = (sel) => document.querySelector(sel);
const el = {};

/* ---------------- Ponte com o Python ---------------- */
function api() {
  if (!window.pywebview || !window.pywebview.api) throw new Error("Bridge do pywebview ainda não está pronto.");
  return window.pywebview.api;
}
async function call(method, ...args) {
  try {
    const res = await api()[method](...args);
    return res || { ok: false, error: "Resposta vazia do backend." };
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}
