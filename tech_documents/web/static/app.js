"use strict";

const projectSelect = document.getElementById("projectSelect");
const fileList = document.getElementById("fileList");
const fileContextMenu = document.getElementById("fileContextMenu");
const editor = document.getElementById("editor");
const markdownPreview = document.getElementById("markdownPreview");
const pdfPreview = document.getElementById("pdfPreview");
const compilerLog = document.getElementById("compilerLog");
const currentFilename = document.getElementById("currentFilename");
const statusEl = document.getElementById("status");
const cursorStatus = document.getElementById("cursorStatus");
const wordCount = document.getElementById("wordCount");
const outline = document.getElementById("outline");
const editorGrid = document.getElementById("editorGrid");
const searchInput = document.getElementById("searchInput");
const diagramBuilderBtn = document.getElementById("diagramBuilderBtn");
const diagramBuilderModal = document.getElementById("diagramBuilderModal");
const diagramBuilderSource = document.getElementById("diagramBuilderSource");
const diagramBuilderPreview = document.getElementById("diagramBuilderPreview");
const diagramBuilderErrors = document.getElementById("diagramBuilderErrors");
const diagramBuilderStats = document.getElementById("diagramBuilderStats");
const diagramDirection = document.getElementById("diagramDirection");
const diagramPreset = document.getElementById("diagramPreset");
const diagramBuilderApplyBtn = document.getElementById("diagramBuilderApplyBtn");
const diagramOutputBase = document.getElementById("diagramOutputBase");
const diagramExportStatus = document.getElementById("diagramExportStatus");
const diagramInsertTarget = document.getElementById("diagramInsertTarget");
const diagramInsertFormat = document.getElementById("diagramInsertFormat");
const diagramInsertCaption = document.getElementById("diagramInsertCaption");
const diagramInsertLabel = document.getElementById("diagramInsertLabel");
const diagramFigureMode = document.getElementById("diagramFigureMode");
const diagramLabelControl = document.getElementById("diagramLabelControl");
const diagramFigureModeControl = document.getElementById("diagramFigureModeControl");
const diagramExportInsertBtn = document.getElementById("diagramExportInsertBtn");
const diagramInsertStatus = document.getElementById("diagramInsertStatus");

let projects = [];
let currentProject = "";
let currentFile = "";
let selectedItem = null;
let dirty = false;
let autosaveTimer = null;
let searchMatches = [];
let searchIndex = -1;
const expandedFolders = new Set();

const editorHistories = new Map();
const HISTORY_LIMIT = 200;
const HISTORY_COALESCE_MS = 700;
let applyingHistoryState = false;
let diagramPreviewTimer = null;
let diagramPreviewGeneration = 0;
let diagramBuilderTimer = null;
let diagramBuilderGeneration = 0;
let diagramBuilderNormalizedSource = "";

marked.setOptions({
  gfm: true,
  breaks: false,
});

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "strict",
  theme: "default",
  flowchart: {
    htmlLabels: false,
    useMaxWidth: true,
  },
});

function setStatus(message) {
  statusEl.textContent = message;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message = typeof data === "string"
      ? data
      : data.error || data.message || response.statusText;
    const error = new Error(message);
    error.payload = typeof data === "object" ? data : { log: data };
    throw error;
  }

  return data;
}

function projectData() {
  return projects.find(project => project.name === currentProject) || null;
}

function encodeRelativePath(path) {
  return String(path)
    .split("/")
    .filter(Boolean)
    .map(segment => encodeURIComponent(segment))
    .join("/");
}

function fileApiUrl(path) {
  return `/api/files/${encodeURIComponent(currentProject)}/${encodeRelativePath(path)}`;
}

function itemApiUrl(path) {
  return `/api/items/${encodeURIComponent(currentProject)}/${encodeRelativePath(path)}`;
}

function dirname(path) {
  const index = String(path).lastIndexOf("/");
  return index < 0 ? "" : path.slice(0, index);
}

function basename(path) {
  const parts = String(path).split("/");
  return parts[parts.length - 1] || "";
}

function joinPath(parent, child) {
  const cleanParent = String(parent || "").replace(/^\/+|\/+$/g, "");
  const cleanChild = String(child || "").replace(/^\/+|\/+$/g, "");
  return cleanParent ? `${cleanParent}/${cleanChild}` : cleanChild;
}

function resolveProjectRelativePath(baseDirectory, relativePath) {
  const raw = String(relativePath || "").replace(/\\/g, "/");
  if (!raw || /^(?:[a-z]+:|\/|#)/i.test(raw)) return null;
  const parts = [...String(baseDirectory || "").split("/"), ...raw.split("/")];
  const resolved = [];
  for (const part of parts) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (resolved.length === 0) return null;
      resolved.pop();
    } else {
      resolved.push(part);
    }
  }
  return resolved.join("/");
}

function rewriteMarkdownProjectAssets() {
  if (!currentProject || !currentFile) return;
  const baseDirectory = dirname(currentFile);
  markdownPreview.querySelectorAll("img[src]").forEach(image => {
    const source = image.getAttribute("src") || "";
    if (/^(?:https?:|data:|blob:|\/\/|#)/i.test(source)) return;
    const resolved = resolveProjectRelativePath(baseDirectory, source);
    if (!resolved) return;
    image.src = `/api/project-asset/${encodeURIComponent(currentProject)}/${encodeRelativePath(resolved)}`;
  });
}

function selectedFolder() {
  if (!selectedItem) return "";
  return selectedItem.type === "directory"
    ? selectedItem.path
    : dirname(selectedItem.path);
}

function folderKey(path) {
  return `${currentProject}:${path}`;
}

function ensureCurrentParentsExpanded(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  if (parts.length < 2) return;
  let prefix = "";
  for (let i = 0; i < parts.length - 1; i++) {
    prefix = joinPath(prefix, parts[i]);
    expandedFolders.add(folderKey(prefix));
  }
}

function historyKey(project = currentProject, filename = currentFile) {
  return `${project}\u0000${filename}`;
}

function captureEditorState() {
  return {
    value: editor.value,
    start: editor.selectionStart,
    end: editor.selectionEnd,
    direction: editor.selectionDirection || "none",
  };
}

function sameEditorState(a, b) {
  return Boolean(a && b) &&
    a.value === b.value &&
    a.start === b.start &&
    a.end === b.end &&
    a.direction === b.direction;
}

function historyForCurrentFile(create = true) {
  if (!currentProject || !currentFile) return null;
  const key = historyKey();
  let history = editorHistories.get(key);
  if (!history && create) {
    history = {
      states: [captureEditorState()],
      index: 0,
      lastInputType: "",
      lastRecordedAt: 0,
    };
    editorHistories.set(key, history);
  }
  return history;
}

function initializeEditorHistory(content) {
  if (!currentProject || !currentFile) return;
  const key = historyKey();
  const existing = editorHistories.get(key);
  const currentState = existing?.states?.[existing.index];

  if (existing && currentState && currentState.value === content) {
    editor.setSelectionRange(
      Math.min(currentState.start, content.length),
      Math.min(currentState.end, content.length),
      currentState.direction
    );
    updateUndoRedoButtons();
    return;
  }

  editorHistories.set(key, {
    states: [captureEditorState()],
    index: 0,
    lastInputType: "",
    lastRecordedAt: 0,
  });
  updateUndoRedoButtons();
}

function recordEditorState(inputType = "input", forceNewStep = false) {
  if (applyingHistoryState || !currentProject || !currentFile) return;
  const history = historyForCurrentFile(true);
  const snapshot = captureEditorState();
  const current = history.states[history.index];
  if (sameEditorState(snapshot, current)) return;

  if (history.index < history.states.length - 1) {
    history.states = history.states.slice(0, history.index + 1);
  }

  const now = Date.now();
  const coalescableTypes = new Set([
    "insertText",
    "deleteContentBackward",
    "deleteContentForward",
  ]);
  const canCoalesce = !forceNewStep &&
    coalescableTypes.has(inputType) &&
    history.lastInputType === inputType &&
    now - history.lastRecordedAt <= HISTORY_COALESCE_MS &&
    history.states.length > 1;

  if (canCoalesce) {
    history.states[history.index] = snapshot;
  } else {
    history.states.push(snapshot);
    history.index += 1;
    if (history.states.length > HISTORY_LIMIT) {
      history.states.shift();
      history.index -= 1;
    }
  }

  history.lastInputType = inputType;
  history.lastRecordedAt = now;
  updateUndoRedoButtons();
}

function applyHistoryState(state) {
  applyingHistoryState = true;
  editor.value = state.value;
  editor.setSelectionRange(
    Math.min(state.start, state.value.length),
    Math.min(state.end, state.value.length),
    state.direction
  );
  applyingHistoryState = false;

  scheduleAutosave();
  updatePreview();
  updateCursorStatus();
  findMatches();
}

function undoEditor() {
  const history = historyForCurrentFile(false);
  if (!history || history.index <= 0) {
    setStatus("Nothing to undo.");
    return;
  }
  history.index -= 1;
  history.lastInputType = "";
  applyHistoryState(history.states[history.index]);
  updateUndoRedoButtons();
  setStatus("Undo");
}

function redoEditor() {
  const history = historyForCurrentFile(false);
  if (!history || history.index >= history.states.length - 1) {
    setStatus("Nothing to redo.");
    return;
  }
  history.index += 1;
  history.lastInputType = "";
  applyHistoryState(history.states[history.index]);
  updateUndoRedoButtons();
  setStatus("Redo");
}

function updateUndoRedoButtons() {
  const history = historyForCurrentFile(false);
  const undoButton = document.getElementById("undoBtn");
  const redoButton = document.getElementById("redoBtn");
  if (undoButton) undoButton.disabled = !history || history.index <= 0;
  if (redoButton) redoButton.disabled = !history || history.index >= history.states.length - 1;
}

function remapHistoriesForMove(project, source, destination) {
  const prefix = `${project}\u0000`;
  const entries = Array.from(editorHistories.entries());
  entries.forEach(([key, history]) => {
    if (!key.startsWith(prefix)) return;
    const path = key.slice(prefix.length);
    if (path !== source && !path.startsWith(`${source}/`)) return;
    const suffix = path.slice(source.length);
    editorHistories.delete(key);
    editorHistories.set(historyKey(project, `${destination}${suffix}`), history);
  });
}

function deleteHistoriesForPath(project, path, recursive = false) {
  const prefix = `${project}\u0000`;
  Array.from(editorHistories.keys()).forEach(key => {
    if (!key.startsWith(prefix)) return;
    const filePath = key.slice(prefix.length);
    if (filePath === path || (recursive && filePath.startsWith(`${path}/`))) {
      editorHistories.delete(key);
    }
  });
}

function afterProgrammaticEdit() {
  recordEditorState("insertReplacementText", true);
  scheduleAutosave();
  updatePreview();
  updateCursorStatus();
  findMatches();
}

function firstEditableFile(project) {
  return project?.files?.find(file => file.editable)?.path || "";
}

async function loadProjects(preferredProject, preferredFile) {
  const data = await api("/api/projects");
  projects = data.projects;
  projectSelect.innerHTML = "";

  if (projects.length === 0) {
    await createProject("farmbot_notebook");
    return;
  }

  projects.forEach(project => {
    const option = document.createElement("option");
    option.value = project.name;
    option.textContent = project.name;
    projectSelect.appendChild(option);
  });

  currentProject =
    preferredProject && projects.some(project => project.name === preferredProject)
      ? preferredProject
      : projects[0].name;

  projectSelect.value = currentProject;
  const project = projectData();
  const preferredExists = preferredFile &&
    project.files.some(file => file.path === preferredFile && file.editable);
  const currentExists = currentFile &&
    project.files.some(file => file.path === currentFile && file.editable);
  const targetFile = preferredExists
    ? preferredFile
    : currentExists
      ? currentFile
      : firstEditableFile(project);

  if (targetFile) {
    ensureCurrentParentsExpanded(targetFile);
    await openFile(targetFile);
  } else {
    currentFile = "";
    editor.value = "";
    currentFilename.textContent = "No file selected";
    selectedItem = null;
    renderFiles();
    updatePreview();
    updateUndoRedoButtons();
    updateDiagramBuilderAvailability();
  }
}

async function refreshProjectIndex() {
  const data = await api("/api/projects");
  projects = data.projects;
  renderFiles();
}

function renderFiles() {
  fileList.innerHTML = "";
  const project = projectData();
  if (!project) return;

  const renderNodes = (nodes, container, depth = 0) => {
    nodes.forEach(node => {
      const wrapper = document.createElement("div");
      wrapper.className = "tree-node";

      const row = document.createElement("div");
      row.className = "tree-row";
      row.style.paddingLeft = `${6 + depth * 14}px`;
      row.dataset.path = node.path;
      row.dataset.type = node.type;
      row.title = node.path;
      row.draggable = true;

      if (node.type === "directory") {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "tree-toggle";
        const expanded = expandedFolders.has(folderKey(node.path));
        toggle.textContent = expanded ? "▾" : "▸";
        toggle.title = expanded ? "Collapse folder" : "Expand folder";
        toggle.addEventListener("click", event => {
          event.stopPropagation();
          const key = folderKey(node.path);
          if (expandedFolders.has(key)) expandedFolders.delete(key);
          else expandedFolders.add(key);
          renderFiles();
        });
        row.appendChild(toggle);
      } else {
        const spacer = document.createElement("span");
        spacer.className = "tree-spacer";
        row.appendChild(spacer);
      }

      const icon = document.createElement("span");
      icon.className = "tree-icon";
      icon.textContent = node.type === "directory" ? "▰" : node.editable ? "▤" : "◆";
      row.appendChild(icon);

      const label = document.createElement("span");
      label.className = "tree-label";
      label.textContent = node.name;
      row.appendChild(label);

      if (node.type === "file" && node.path === currentFile) {
        row.classList.add("active");
      }
      if (selectedItem && selectedItem.path === node.path) {
        row.classList.add("selected");
      }

      row.addEventListener("click", async () => {
        hideContextMenu();
        selectedItem = { ...node };
        if (node.type === "directory") {
          const key = folderKey(node.path);
          if (expandedFolders.has(key)) expandedFolders.delete(key);
          else expandedFolders.add(key);
          renderFiles();
          setStatus(`Selected folder ${node.path}`);
          return;
        }

        if (!node.editable) {
          renderFiles();
          setStatus(`${node.path} is not an editable text file.`);
          return;
        }

        if (dirty) await saveCurrentFile();
        await openFile(node.path);
      });

      row.addEventListener("contextmenu", event => {
        event.preventDefault();
        selectedItem = { ...node };
        renderFiles();
        showContextMenu(event.clientX, event.clientY, node);
      });

      row.addEventListener("dragstart", event => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", node.path);
      });

      if (node.type === "directory") {
        row.addEventListener("dragover", event => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          row.classList.add("drag-over");
        });
        row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
        row.addEventListener("drop", async event => {
          event.preventDefault();
          row.classList.remove("drag-over");
          const source = event.dataTransfer.getData("text/plain");
          if (!source) return;
          try {
            await moveItemToFolder(source, node.path);
          } catch (error) {
            setStatus(`Move failed: ${error.message}`);
          }
        });
      }

      wrapper.appendChild(row);

      if (node.type === "directory") {
        const children = document.createElement("div");
        children.className = "tree-children";
        children.hidden = !expandedFolders.has(folderKey(node.path));
        renderNodes(node.children || [], children, depth + 1);
        wrapper.appendChild(children);
      }

      container.appendChild(wrapper);
    });
  };

  const rootRow = document.createElement("div");
  rootRow.className = "tree-row project-root";
  if (selectedItem && selectedItem.type === "directory" && selectedItem.path === "") {
    rootRow.classList.add("selected");
  }
  rootRow.title = `${project.name} (project root)`;
  rootRow.draggable = false;

  const rootSpacer = document.createElement("span");
  rootSpacer.className = "tree-spacer";
  rootRow.appendChild(rootSpacer);

  const rootIcon = document.createElement("span");
  rootIcon.className = "tree-icon";
  rootIcon.textContent = "▰";
  rootRow.appendChild(rootIcon);

  const rootLabel = document.createElement("span");
  rootLabel.className = "tree-label";
  rootLabel.textContent = project.name;
  rootRow.appendChild(rootLabel);

  rootRow.addEventListener("click", () => {
    hideContextMenu();
    selectedItem = { type: "directory", name: project.name, path: "" };
    renderFiles();
    setStatus("Selected project root");
  });
  rootRow.addEventListener("contextmenu", event => {
    event.preventDefault();
    selectedItem = { type: "directory", name: project.name, path: "" };
    renderFiles();
    showContextMenu(event.clientX, event.clientY, selectedItem);
  });
  rootRow.addEventListener("dragover", event => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    rootRow.classList.add("drag-over");
  });
  rootRow.addEventListener("dragleave", () => rootRow.classList.remove("drag-over"));
  rootRow.addEventListener("drop", async event => {
    event.preventDefault();
    rootRow.classList.remove("drag-over");
    const source = event.dataTransfer.getData("text/plain");
    if (!source) return;
    try {
      await moveItemToFolder(source, "");
    } catch (error) {
      setStatus(`Move failed: ${error.message}`);
    }
  });

  fileList.appendChild(rootRow);
  renderNodes(project.tree || [], fileList, 1);
}

async function openFile(filename) {
  closeDiagramBuilder();
  const data = await api(fileApiUrl(filename));
  currentFile = data.filename;
  selectedItem = {
    type: "file",
    name: basename(currentFile),
    path: currentFile,
    editable: true,
  };
  ensureCurrentParentsExpanded(currentFile);
  editor.value = data.content;
  dirty = false;
  initializeEditorHistory(data.content);
  currentFilename.textContent = currentFile;
  setStatus(`Opened ${currentFile}`);
  renderFiles();
  updatePreview();
  updateCursorStatus();
  updateDiagramBuilderAvailability();
}

async function saveCurrentFile() {
  if (!currentProject || !currentFile) return;
  await api(fileApiUrl(currentFile), {
    method: "PUT",
    body: JSON.stringify({ content: editor.value }),
  });
  dirty = false;
  setStatus(`Saved ${currentFile} at ${new Date().toLocaleTimeString()}`);
}

function scheduleAutosave() {
  dirty = true;
  setStatus("Unsaved changes");
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => {
    saveCurrentFile().catch(error => setStatus(`Save failed: ${error.message}`));
  }, 800);
}

function currentExtension() {
  const index = currentFile.lastIndexOf(".");
  return index >= 0 ? currentFile.slice(index).toLowerCase() : "";
}

function updateDiagramBuilderAvailability() {
  if (!diagramBuilderBtn) return;
  const enabled = currentExtension() === ".diagram";
  diagramBuilderBtn.disabled = !enabled;
  diagramBuilderBtn.title = enabled
    ? "Open the visual builder for the current .diagram file"
    : "Open a .diagram file to use the Diagram Builder";
}

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/<[^>]*>/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function protectMath(markdown) {
  const placeholders = [];
  const patterns = [
    /\$\$[\s\S]*?\$\$/g,
    /\\\[[\s\S]*?\\\]/g,
    /\\\([\s\S]*?\\\)/g,
    /\$(?!\s)(?:\\.|[^$\\])+\$/g,
  ];

  let output = markdown;
  patterns.forEach(pattern => {
    output = output.replace(pattern, match => {
      const token = `MATHPLACEHOLDER${placeholders.length}END`;
      placeholders.push(match);
      return token;
    });
  });

  return { output, placeholders };
}

function restoreMath(html, placeholders) {
  let output = html;
  placeholders.forEach((math, index) => {
    output = output.replace(
      `MATHPLACEHOLDER${index}END`,
      math.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    );
  });
  return output;
}

function renderMarkdown() {
  const protectedMath = protectMath(editor.value);
  const rawHtml = marked.parse(protectedMath.output);
  const restored = restoreMath(rawHtml, protectedMath.placeholders);
  markdownPreview.innerHTML = DOMPurify.sanitize(restored, {
    ADD_TAGS: ["input"],
    ADD_ATTR: ["checked", "disabled", "type"],
  });

  rewriteMarkdownProjectAssets();

  markdownPreview.querySelectorAll("pre code").forEach(block => {
    if (!block.classList.contains("language-mermaid")) {
      hljs.highlightElement(block);
    }
  });

  if (window.renderMathInElement) {
    renderMathInElement(markdownPreview, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      ignoredTags: [
        "script", "noscript", "style", "textarea", "pre", "code",
      ],
      throwOnError: false,
    });
  }

  renderMermaid();
  buildMarkdownOutline();
}

async function renderMermaid() {
  const blocks = Array.from(
    markdownPreview.querySelectorAll("code.language-mermaid")
  );

  for (let i = 0; i < blocks.length; i++) {
    const code = blocks[i];
    const pre = code.parentElement;
    const source = code.textContent;
    try {
      const id = `mermaid-${Date.now()}-${i}`;
      const rendered = await mermaid.render(id, source);
      const wrapper = document.createElement("div");
      wrapper.className = "mermaid-rendered";
      wrapper.innerHTML = rendered.svg;
      pre.replaceWith(wrapper);
    } catch (error) {
      console.error("Mermaid rendering failed:", error);
    }
  }
}

function renderDiagramError(errors) {
  markdownPreview.innerHTML = "";
  const panel = document.createElement("div");
  panel.className = "diagram-error";
  const title = document.createElement("strong");
  title.textContent = "Diagram syntax error";
  panel.appendChild(title);
  const list = document.createElement("ul");
  (errors || ["Unable to parse diagram."]).forEach(message => {
    const item = document.createElement("li");
    item.textContent = message;
    list.appendChild(item);
  });
  panel.appendChild(list);
  markdownPreview.appendChild(panel);
}

async function renderDiagramPreviewNow(generation) {
  const source = editor.value;
  try {
    const result = await api("/api/diagram/parse", {
      method: "POST",
      body: JSON.stringify({ content: source }),
    });
    if (generation !== diagramPreviewGeneration || currentExtension() !== ".diagram") return;

    const rendered = await mermaid.render(`diagram-${Date.now()}-${generation}`, result.mermaid);
    if (generation !== diagramPreviewGeneration || currentExtension() !== ".diagram") return;

    markdownPreview.innerHTML = "";
    const summary = document.createElement("div");
    summary.className = "diagram-summary";
    summary.textContent = `${result.graph.nodes.length} nodes · ${result.graph.edges.length} edges`;
    markdownPreview.appendChild(summary);

    const wrapper = document.createElement("div");
    wrapper.className = "diagram-rendered";
    wrapper.innerHTML = rendered.svg;
    markdownPreview.appendChild(wrapper);
  } catch (error) {
    if (generation !== diagramPreviewGeneration || currentExtension() !== ".diagram") return;
    renderDiagramError(error.payload?.errors || [error.message]);
  }
}

function scheduleDiagramPreview() {
  clearTimeout(diagramPreviewTimer);
  diagramPreviewGeneration += 1;
  const generation = diagramPreviewGeneration;
  markdownPreview.innerHTML = '<div class="diagram-preview-status">Parsing diagram…</div>';
  diagramPreviewTimer = setTimeout(() => {
    renderDiagramPreviewNow(generation);
  }, 180);
}

function renderDiagramBuilderErrors(errors) {
  diagramBuilderErrors.innerHTML = "";
  if (!errors || errors.length === 0) {
    diagramBuilderErrors.hidden = true;
    return;
  }

  const title = document.createElement("strong");
  title.textContent = "Diagram syntax error";
  diagramBuilderErrors.appendChild(title);
  const list = document.createElement("ul");
  errors.forEach(message => {
    const item = document.createElement("li");
    item.textContent = message;
    list.appendChild(item);
  });
  diagramBuilderErrors.appendChild(list);
  diagramBuilderErrors.hidden = false;
}

async function renderDiagramBuilderNow(generation) {
  const source = diagramBuilderSource.value;
  const direction = diagramDirection.value;
  const preset = diagramPreset.value;

  try {
    const result = await api("/api/diagram/parse", {
      method: "POST",
      body: JSON.stringify({ content: source, direction, preset }),
    });
    if (generation !== diagramBuilderGeneration || diagramBuilderModal.hidden) return;

    const rendered = await mermaid.render(
      `diagram-builder-${Date.now()}-${generation}`,
      result.mermaid
    );
    if (generation !== diagramBuilderGeneration || diagramBuilderModal.hidden) return;

    diagramBuilderPreview.innerHTML = "";
    const wrapper = document.createElement("div");
    wrapper.className = "diagram-builder-rendered";
    wrapper.innerHTML = rendered.svg;
    diagramBuilderPreview.appendChild(wrapper);

    diagramBuilderStats.textContent =
      `${result.graph.nodes.length} nodes · ${result.graph.edges.length} edges`;
    diagramBuilderNormalizedSource = result.normalized_source;
    diagramBuilderApplyBtn.disabled = false;
    renderDiagramBuilderErrors([]);
  } catch (error) {
    if (generation !== diagramBuilderGeneration || diagramBuilderModal.hidden) return;
    diagramBuilderPreview.innerHTML =
      '<div class="diagram-preview-status">Fix the source errors to update the preview.</div>';
    diagramBuilderStats.textContent = "Preview unavailable";
    diagramBuilderNormalizedSource = "";
    diagramBuilderApplyBtn.disabled = true;
    renderDiagramBuilderErrors(error.payload?.errors || [error.message]);
  }
}

function scheduleDiagramBuilderPreview() {
  clearTimeout(diagramBuilderTimer);
  diagramBuilderGeneration += 1;
  const generation = diagramBuilderGeneration;
  diagramBuilderNormalizedSource = "";
  diagramBuilderApplyBtn.disabled = true;
  diagramBuilderPreview.innerHTML =
    '<div class="diagram-preview-status">Rendering diagram…</div>';
  diagramBuilderTimer = setTimeout(() => {
    renderDiagramBuilderNow(generation);
  }, 160);
}

async function openDiagramBuilder() {
  if (currentExtension() !== ".diagram") {
    setStatus("Open a .diagram file before using the Diagram Builder.");
    return;
  }

  diagramBuilderSource.value = editor.value;
  diagramBuilderModal.hidden = false;
  document.body.classList.add("diagram-builder-open");
  diagramBuilderApplyBtn.disabled = true;
  diagramBuilderNormalizedSource = "";
  renderDiagramBuilderErrors([]);

  try {
    const parsed = await api("/api/diagram/parse", {
      method: "POST",
      body: JSON.stringify({ content: editor.value }),
    });
    diagramDirection.value = parsed.graph.direction || "TB";
    diagramPreset.value = parsed.graph.preset || "architecture";
  } catch (_error) {
    diagramDirection.value = "TB";
    diagramPreset.value = "architecture";
  }

  diagramOutputBase.value = `figures/${diagramFileStem()}`;
  diagramInsertCaption.value = diagramHumanTitle();
  diagramInsertLabel.value = `fig:${diagramFileStem().replace(/[^A-Za-z0-9:._-]+/g, "-")}`;
  populateDiagramInsertTargets();
  updateDiagramInsertControls();
  diagramExportStatus.textContent = "No export yet.";

  scheduleDiagramBuilderPreview();
  setTimeout(() => diagramBuilderSource.focus(), 0);
}

function closeDiagramBuilder() {
  if (!diagramBuilderModal || diagramBuilderModal.hidden) return;
  clearTimeout(diagramBuilderTimer);
  diagramBuilderGeneration += 1;
  diagramBuilderModal.hidden = true;
  document.body.classList.remove("diagram-builder-open");
  diagramBuilderNormalizedSource = "";
}

async function commitDiagramBuilderSource() {
  if (!diagramBuilderNormalizedSource) {
    clearTimeout(diagramBuilderTimer);
    diagramBuilderGeneration += 1;
    await renderDiagramBuilderNow(diagramBuilderGeneration);
    if (!diagramBuilderNormalizedSource) {
      throw new Error("Fix the diagram source before saving or exporting.");
    }
  }

  const normalized = diagramBuilderNormalizedSource;
  if (editor.value !== normalized) {
    editor.value = normalized;
    editor.setSelectionRange(editor.value.length, editor.value.length);
    afterProgrammaticEdit();
  }
  diagramBuilderSource.value = normalized;
  await saveCurrentFile();
  return normalized;
}

async function applyDiagramBuilder() {
  await commitDiagramBuilderSource();
  const appliedFile = currentFile;
  const preset = diagramPreset.value;
  const direction = diagramDirection.value;
  closeDiagramBuilder();
  setStatus(`Applied ${preset} diagram style (${direction}) to ${appliedFile}`);
}

function insertDiagramType(kind) {
  const start = diagramBuilderSource.selectionStart;
  const end = diagramBuilderSource.selectionEnd;
  const selected = diagramBuilderSource.value.slice(start, end);
  const replacement = selected
    ? `${selected} [${kind}]`
    : `Node [${kind}]`;
  diagramBuilderSource.setRangeText(replacement, start, end, "end");
  diagramBuilderSource.focus();
  scheduleDiagramBuilderPreview();
}

function diagramFileStem() {
  return basename(currentFile).replace(/\.diagram$/i, "") || "diagram";
}

function diagramHumanTitle() {
  return diagramFileStem()
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, character => character.toUpperCase());
}

function normalizeDiagramOutputBase(value) {
  let output = String(value || "").trim().replace(/\\/g, "/");
  output = output.replace(/\.(svg|png|pdf)$/i, "");
  output = output.replace(/^\/+|\/+$/g, "");
  if (!output) output = `figures/${diagramFileStem()}`;
  if (output.split("/").some(part => !part || part === "." || part === "..")) {
    throw new Error("Output path must stay inside the project directory.");
  }
  return output;
}

function populateDiagramInsertTargets() {
  if (!diagramInsertTarget) return;
  const previous = diagramInsertTarget.value;
  const files = (projectData()?.files || []).filter(file =>
    [".md", ".markdown", ".tex"].includes(file.extension)
  );
  diagramInsertTarget.innerHTML = "";
  files.forEach(file => {
    const option = document.createElement("option");
    option.value = file.path;
    option.textContent = file.path;
    diagramInsertTarget.appendChild(option);
  });

  if (files.some(file => file.path === previous)) {
    diagramInsertTarget.value = previous;
  } else {
    const preferred = files.find(file => basename(file.path).toLowerCase() === "paper.tex")
      || files.find(file => file.extension === ".tex")
      || files[0];
    if (preferred) diagramInsertTarget.value = preferred.path;
  }

  diagramExportInsertBtn.disabled = files.length === 0;
  if (files.length === 0) {
    diagramInsertStatus.textContent = "Create a Markdown or LaTeX document before inserting a figure.";
  }
}

function updateDiagramInsertControls() {
  const target = diagramInsertTarget?.value || "";
  const extension = target.includes(".")
    ? target.slice(target.lastIndexOf(".")).toLowerCase()
    : "";
  const isTex = extension === ".tex";

  Array.from(diagramInsertFormat?.options || []).forEach(option => {
    option.disabled = isTex ? option.value === "svg" : option.value === "pdf";
  });

  if (isTex && diagramInsertFormat.value === "svg") diagramInsertFormat.value = "pdf";
  if (!isTex && diagramInsertFormat.value === "pdf") diagramInsertFormat.value = "svg";

  if (diagramLabelControl) diagramLabelControl.hidden = !isTex;
  if (diagramFigureModeControl) diagramFigureModeControl.hidden = !isTex;

  if (target) {
    diagramInsertStatus.textContent = isTex
      ? "PDF is recommended for LaTeX; the figure is inserted before \\end{document}."
      : "SVG is recommended for Markdown and stays sharp at any zoom level.";
  }
}

async function ensureDiagramBuilderPreview() {
  let svg = diagramBuilderPreview.querySelector("svg");
  if (svg && diagramBuilderNormalizedSource) return svg;

  clearTimeout(diagramBuilderTimer);
  diagramBuilderGeneration += 1;
  await renderDiagramBuilderNow(diagramBuilderGeneration);
  svg = diagramBuilderPreview.querySelector("svg");
  if (!svg || !diagramBuilderNormalizedSource) {
    throw new Error("The diagram preview is not available. Fix any source errors first.");
  }
  return svg;
}

function serializeDiagramSvg(svg) {
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");

  const viewBox = svg.viewBox?.baseVal;
  const rect = svg.getBoundingClientRect();
  let width = viewBox?.width || rect.width || 1200;
  let height = viewBox?.height || rect.height || 800;
  if (!Number.isFinite(width) || width <= 0) width = 1200;
  if (!Number.isFinite(height) || height <= 0) height = 800;

  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.style.maxWidth = "none";
  clone.style.background = "#ffffff";

  return {
    text: new XMLSerializer().serializeToString(clone),
    width,
    height,
  };
}

function svgToCanvas(svgData) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([svgData.text], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const image = new Image();

    image.onload = () => {
      URL.revokeObjectURL(url);
      const maxPixels = 24000000;
      const idealScale = 3;
      const pixelScale = Math.sqrt(maxPixels / Math.max(1, svgData.width * svgData.height));
      const scale = Math.max(0.5, Math.min(idealScale, pixelScale));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(svgData.width * scale));
      canvas.height = Math.max(1, Math.round(svgData.height * scale));
      const context = canvas.getContext("2d");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      resolve(canvas);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("The browser could not rasterize the SVG preview."));
    };
    image.src = url;
  });
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob);
      else reject(new Error("PNG export failed."));
    }, "image/png");
  });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(new Error("Unable to read generated asset."));
    reader.readAsDataURL(blob);
  });
}

async function canvasToPdfBlob(canvas) {
  const JsPDF = window.jspdf?.jsPDF;
  if (!JsPDF) {
    throw new Error("PDF export library is unavailable. Check the browser's internet connection and reload.");
  }

  const orientation = canvas.width >= canvas.height ? "landscape" : "portrait";
  const pdf = new JsPDF({ orientation, unit: "pt", format: "a4", compress: true });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const margin = 28;
  const scale = Math.min(
    (pageWidth - margin * 2) / canvas.width,
    (pageHeight - margin * 2) / canvas.height
  );
  const width = canvas.width * scale;
  const height = canvas.height * scale;
  const x = (pageWidth - width) / 2;
  const y = (pageHeight - height) / 2;
  pdf.addImage(canvas.toDataURL("image/png"), "PNG", x, y, width, height, undefined, "FAST");
  return pdf.output("blob");
}

async function saveDiagramAsset(format) {
  format = String(format || "").toLowerCase();
  if (!["svg", "png", "pdf"].includes(format)) {
    throw new Error(`Unsupported diagram export format: ${format}`);
  }

  diagramExportStatus.textContent = `Generating ${format.toUpperCase()}…`;
  await commitDiagramBuilderSource();
  const svg = await ensureDiagramBuilderPreview();
  const svgData = serializeDiagramSvg(svg);
  const base = normalizeDiagramOutputBase(diagramOutputBase.value);
  diagramOutputBase.value = base;
  const assetPath = `${base}.${format}`;

  let encoding = "text";
  let content = svgData.text;
  if (format !== "svg") {
    const canvas = await svgToCanvas(svgData);
    const blob = format === "png"
      ? await canvasToPngBlob(canvas)
      : await canvasToPdfBlob(canvas);
    encoding = "base64";
    content = await blobToBase64(blob);
  }

  const result = await api(`/api/diagram/assets/${encodeURIComponent(currentProject)}`, {
    method: "POST",
    body: JSON.stringify({ path: assetPath, encoding, content }),
  });

  const parent = dirname(result.path);
  if (parent) expandedFolders.add(folderKey(parent));
  await refreshProjectIndex();
  diagramExportStatus.textContent = `Saved ${result.path}`;
  setStatus(`Exported diagram to ${result.path}`);
  return result.path;
}

async function exportAndInsertDiagram() {
  const target = diagramInsertTarget.value;
  if (!target) throw new Error("Choose a Markdown or LaTeX target document.");
  const format = diagramInsertFormat.value;
  diagramExportInsertBtn.disabled = true;
  diagramInsertStatus.textContent = "Exporting current diagram…";

  try {
    const asset = await saveDiagramAsset(format);
    diagramInsertStatus.textContent = `Inserting ${asset} into ${target}…`;
    const result = await api(`/api/diagram/insert/${encodeURIComponent(currentProject)}`, {
      method: "POST",
      body: JSON.stringify({
        target,
        asset,
        caption: diagramInsertCaption.value,
        label: diagramInsertLabel.value,
        figure_mode: diagramFigureMode.value,
      }),
    });

    const message = result.already_present
      ? `${target} already references ${result.relative_asset}.`
      : `Inserted figure into ${target}.`;
    diagramInsertStatus.textContent = result.warning ? `${message} ${result.warning}` : message;

    closeDiagramBuilder();
    await refreshProjectIndex();
    await openFile(target);
    setStatus(result.warning ? `${message} ${result.warning}` : message);
  } finally {
    diagramExportInsertBtn.disabled = false;
  }
}

function buildMarkdownOutline() {
  outline.innerHTML = "";
  markdownPreview
    .querySelectorAll("h1, h2, h3, h4, h5, h6")
    .forEach((heading, index) => {
      const level = Number(heading.tagName.slice(1));
      const id = slugify(heading.textContent) || `heading-${index}`;
      heading.id = id;
      const link = document.createElement("a");
      link.href = `#${id}`;
      link.textContent = heading.textContent;
      link.className = `level-${Math.min(level, 4)}`;
      link.addEventListener("click", event => {
        event.preventDefault();
        heading.scrollIntoView({ behavior: "smooth" });
      });
      outline.appendChild(link);
    });
}

function buildLatexOutline() {
  outline.innerHTML = "";
  const pattern = /\\(section|subsection|subsubsection|paragraph)\*?\{([^}]*)\}/g;
  const levels = {
    section: 1,
    subsection: 2,
    subsubsection: 3,
    paragraph: 4,
  };
  let match;
  while ((match = pattern.exec(editor.value)) !== null) {
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = match[2];
    link.className = `level-${levels[match[1]]}`;
    const offset = match.index;
    link.addEventListener("click", event => {
      event.preventDefault();
      editor.focus();
      editor.setSelectionRange(offset, offset);
      updateCursorStatus();
    });
    outline.appendChild(link);
  }
}

function renderPlainSourcePreview() {
  markdownPreview.innerHTML = "";
  const pre = document.createElement("pre");
  const code = document.createElement("code");
  code.className = currentExtension() === ".bib"
    ? "language-bibtex"
    : "language-latex";
  code.textContent = editor.value;
  pre.appendChild(code);
  markdownPreview.appendChild(pre);
  hljs.highlightElement(code);
  buildLatexOutline();
}

function updatePreview() {
  pdfPreview.style.display = "none";
  compilerLog.style.display = "none";
  markdownPreview.style.display = "block";

  const extension = currentExtension();
  if (extension === ".md" || extension === ".markdown") {
    renderMarkdown();
  } else if (extension === ".diagram") {
    outline.innerHTML = "";
    scheduleDiagramPreview();
  } else {
    renderPlainSourcePreview();
  }

  const words = editor.value.trim()
    ? editor.value.trim().split(/\s+/).length
    : 0;
  wordCount.textContent = `${words} words`;
}

function updateCursorStatus() {
  const position = editor.selectionStart;
  const before = editor.value.slice(0, position);
  const lines = before.split("\n");
  cursorStatus.textContent =
    `Ln ${lines.length}, Col ${lines[lines.length - 1].length + 1}`;
}

function setView(view) {
  editorGrid.className = `editor-grid ${view}`;
  document.querySelectorAll("[data-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

function replaceSelection(before, after = before, placeholder = "") {
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const selected = editor.value.slice(start, end) || placeholder;
  const replacement = `${before}${selected}${after}`;
  editor.setRangeText(replacement, start, end, "select");
  editor.focus();
  afterProgrammaticEdit();
}

function insertAtLineStart(prefix) {
  const start = editor.selectionStart;
  const lineStart = editor.value.lastIndexOf("\n", start - 1) + 1;
  editor.setRangeText(prefix, lineStart, lineStart, "end");
  editor.focus();
  afterProgrammaticEdit();
}

function insertSnippet(snippet) {
  const start = editor.selectionStart;
  editor.setRangeText(snippet, start, start, "end");
  editor.focus();
  afterProgrammaticEdit();
}

function handleToolbar(command) {
  const extension = currentExtension();
  if (extension === ".diagram") {
    setStatus("Diagram files use the .diagram node/edge syntax; formatting commands are disabled here.");
    return;
  }
  const latex = extension === ".tex";

  const markdownCommands = {
    h1: () => insertAtLineStart("# "),
    h2: () => insertAtLineStart("## "),
    h3: () => insertAtLineStart("### "),
    bold: () => replaceSelection("**", "**", "bold text"),
    italic: () => replaceSelection("*", "*", "italic text"),
    code: () => replaceSelection("`", "`", "code"),
    codeblock: () => replaceSelection("```\n", "\n```", "code"),
    bullet: () => insertAtLineStart("- "),
    number: () => insertAtLineStart("1. "),
    task: () => insertAtLineStart("- [ ] "),
    quote: () => insertAtLineStart("> "),
    link: () => replaceSelection("[", "](https://example.com)", "link text"),
    table: () => insertSnippet(
      "\n| Column 1 | Column 2 |\n|---|---|\n| Value | Value |\n"
    ),
    equation: () => replaceSelection("$$\n", "\n$$", "E = mc^2"),
    section: () => insertAtLineStart("## "),
    figure: () => insertSnippet(
      "\n![Figure caption](images/figure.png)\n"
    ),
    citation: () => insertSnippet("[@citation-key]"),
  };

  const latexCommands = {
    h1: () => replaceSelection("\\section{", "}", "Section title"),
    h2: () => replaceSelection("\\subsection{", "}", "Subsection title"),
    h3: () => replaceSelection("\\subsubsection{", "}", "Subsubsection title"),
    bold: () => replaceSelection("\\textbf{", "}", "bold text"),
    italic: () => replaceSelection("\\emph{", "}", "italic text"),
    code: () => replaceSelection("\\texttt{", "}", "code"),
    codeblock: () => replaceSelection(
      "\\begin{verbatim}\n",
      "\n\\end{verbatim}",
      "code"
    ),
    bullet: () => insertSnippet(
      "\\begin{itemize}\n  \\item Item\n\\end{itemize}\n"
    ),
    number: () => insertSnippet(
      "\\begin{enumerate}\n  \\item Item\n\\end{enumerate}\n"
    ),
    task: () => insertSnippet("\\begin{itemize}\n  \\item[$\\square$] Task\n\\end{itemize}\n"),
    quote: () => replaceSelection(
      "\\begin{quote}\n",
      "\n\\end{quote}",
      "Quoted text"
    ),
    link: () => insertSnippet("\\href{https://example.com}{link text}"),
    table: () => insertSnippet(
      "\\begin{table}[ht]\n" +
      "\\centering\n" +
      "\\caption{Table caption}\n" +
      "\\begin{tabular}{ll}\n" +
      "\\toprule\n" +
      "Column 1 & Column 2 \\\\\n" +
      "\\midrule\n" +
      "Value & Value \\\\\n" +
      "\\bottomrule\n" +
      "\\end{tabular}\n" +
      "\\end{table}\n"
    ),
    equation: () => replaceSelection(
      "\\begin{equation}\n",
      "\n\\end{equation}",
      "E = mc^2"
    ),
    section: () => replaceSelection("\\section{", "}", "Section title"),
    figure: () => insertSnippet(
      "\\begin{figure}[ht]\n" +
      "\\centering\n" +
      "\\includegraphics[width=0.8\\linewidth]{images/figure.png}\n" +
      "\\caption{Figure caption}\n" +
      "\\label{fig:example}\n" +
      "\\end{figure}\n"
    ),
    citation: () => replaceSelection("\\cite{", "}", "citation-key"),
  };

  const handler = (latex ? latexCommands : markdownCommands)[command];
  handler?.();
}

async function createProject(defaultName = "") {
  const name = defaultName || prompt("Project name:");
  if (!name) return;
  await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await loadProjects(name, "paper.tex");
}

async function createFile(targetFolder = selectedFolder()) {
  if (!currentProject) return;
  const location = targetFolder || "project root";
  const filename = prompt(`New file in ${location}\nFilename (.md, .tex, .bib, .txt, or .diagram):`);
  if (!filename) return;
  if (filename.includes("/") || filename.includes("\\")) {
    setStatus("Enter a filename only; select the destination folder in the sidebar.");
    return;
  }
  const path = joinPath(targetFolder, filename);
  await api(`/api/files/${encodeURIComponent(currentProject)}`, {
    method: "POST",
    body: JSON.stringify({ path, content: "" }),
  });
  ensureCurrentParentsExpanded(path);
  await loadProjects(currentProject, path);
}

async function createFolder(targetFolder = selectedFolder()) {
  if (!currentProject) return;
  const location = targetFolder || "project root";
  const name = prompt(`New folder in ${location}\nFolder name:`);
  if (!name) return;
  if (name.includes("/") || name.includes("\\")) {
    setStatus("Enter a folder name only; nested folders can be created one level at a time.");
    return;
  }
  const path = joinPath(targetFolder, name);
  await api(`/api/folders/${encodeURIComponent(currentProject)}`, {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  expandedFolders.add(folderKey(path));
  await loadProjects(currentProject, currentFile);
  selectedItem = { type: "directory", name, path };
  renderFiles();
  setStatus(`Created folder ${path}`);
}

async function uploadFile(file) {
  if (!currentProject || !file) return;
  const folder = selectedFolder();
  const form = new FormData();
  form.append("file", file);
  form.append("folder", folder);
  const data = await api(`/api/upload/${encodeURIComponent(currentProject)}`, {
    method: "POST",
    body: form,
  });
  ensureCurrentParentsExpanded(data.filename);
  await loadProjects(currentProject, currentFile);
  selectedItem = {
    type: "file",
    name: basename(data.filename),
    path: data.filename,
    editable: Boolean(projectData()?.files.find(item => item.path === data.filename)?.editable),
  };
  renderFiles();
  setStatus(`Uploaded ${data.filename}`);
}

async function renameItem(item) {
  if (!item || !item.path) return;
  if (dirty) await saveCurrentFile();
  const oldName = basename(item.path);
  const newName = prompt("Rename to:", oldName);
  if (!newName || newName === oldName) return;
  if (newName.includes("/") || newName.includes("\\")) {
    setStatus("A rename changes only the item name, not its parent folder.");
    return;
  }
  const destination = joinPath(dirname(item.path), newName);
  await moveItem(item.path, destination);
}

async function moveItem(source, destination) {
  if (!source || source === destination) return;
  if (dirty) await saveCurrentFile();

  const previousCurrentFile = currentFile;
  const data = await api(`/api/items/${encodeURIComponent(currentProject)}`, {
    method: "PATCH",
    body: JSON.stringify({ source, destination }),
  });

  remapHistoriesForMove(currentProject, source, destination);

  let preferredFile = previousCurrentFile;
  if (previousCurrentFile === source) {
    preferredFile = destination;
  } else if (previousCurrentFile.startsWith(`${source}/`)) {
    preferredFile = `${destination}${previousCurrentFile.slice(source.length)}`;
  }

  const oldKey = folderKey(source);
  if (expandedFolders.has(oldKey)) {
    expandedFolders.delete(oldKey);
    expandedFolders.add(folderKey(destination));
  }

  selectedItem = {
    type: itemTypeFromKnownPath(source),
    name: basename(destination),
    path: destination,
  };
  ensureCurrentParentsExpanded(destination);
  await loadProjects(currentProject, preferredFile);
  setStatus(`Moved ${data.source} → ${data.destination}`);
}

function itemTypeFromKnownPath(path) {
  const findInTree = nodes => {
    for (const node of nodes || []) {
      if (node.path === path) return node.type;
      if (node.type === "directory") {
        const found = findInTree(node.children);
        if (found) return found;
      }
    }
    return null;
  };
  return findInTree(projectData()?.tree) || "file";
}

async function moveItemToFolder(source, targetFolder) {
  if (!source && source !== "") return;
  const destination = joinPath(targetFolder, basename(source));
  if (destination === source) return;
  await moveItem(source, destination);
}

async function promptMoveItem(item) {
  if (!item || !item.path) return;
  const currentParent = dirname(item.path);
  const target = prompt(
    "Move to folder (relative to project root; leave blank for root):",
    currentParent
  );
  if (target === null) return;
  const normalizedTarget = target.trim().replace(/^\/+|\/+$/g, "");
  const destination = joinPath(normalizedTarget, basename(item.path));
  await moveItem(item.path, destination);
}

async function deleteItem(item) {
  if (!item || !item.path) return;
  const isDirectory = item.type === "directory";
  const warning = isDirectory
    ? `Delete folder "${item.path}" and everything inside it?`
    : `Delete file "${item.path}"?`;
  if (!confirm(warning)) return;

  if (dirty) await saveCurrentFile();
  const affectsOpenFile = currentFile === item.path ||
    (isDirectory && currentFile.startsWith(`${item.path}/`));

  await api(itemApiUrl(item.path), { method: "DELETE" });
  deleteHistoriesForPath(currentProject, item.path, isDirectory);
  if (affectsOpenFile) {
    currentFile = "";
    editor.value = "";
    currentFilename.textContent = "No file selected";
    dirty = false;
  }
  selectedItem = null;
  await loadProjects(currentProject, affectsOpenFile ? "" : currentFile);
  setStatus(`Deleted ${item.path}`);
}

function showContextMenu(x, y, item) {
  selectedItem = { ...item };
  const isRoot = !item.path;
  fileContextMenu.querySelector('[data-file-action="open"]').hidden =
    item.type !== "file" || !item.editable;
  fileContextMenu.querySelector('[data-file-action="new-file"]').hidden =
    item.type !== "directory";
  fileContextMenu.querySelector('[data-file-action="new-folder"]').hidden =
    item.type !== "directory";
  fileContextMenu.querySelector('[data-file-action="rename"]').hidden = isRoot;
  fileContextMenu.querySelector('[data-file-action="move"]').hidden = isRoot;
  fileContextMenu.querySelector('[data-file-action="delete"]').hidden = isRoot;

  fileContextMenu.hidden = false;
  const width = fileContextMenu.offsetWidth;
  const height = fileContextMenu.offsetHeight;
  fileContextMenu.style.left = `${Math.min(x, window.innerWidth - width - 8)}px`;
  fileContextMenu.style.top = `${Math.min(y, window.innerHeight - height - 8)}px`;
}

function hideContextMenu() {
  fileContextMenu.hidden = true;
}

async function handleContextAction(action) {
  const item = selectedItem ? { ...selectedItem } : null;
  hideContextMenu();
  if (!item) return;

  if (action === "open" && item.type === "file" && item.editable) {
    if (dirty) await saveCurrentFile();
    await openFile(item.path);
  } else if (action === "new-file" && item.type === "directory") {
    await createFile(item.path);
  } else if (action === "new-folder" && item.type === "directory") {
    await createFolder(item.path);
  } else if (action === "rename") {
    await renameItem(item);
  } else if (action === "move") {
    await promptMoveItem(item);
  } else if (action === "delete") {
    await deleteItem(item);
  }
}

async function compileCurrentFile() {
  if (currentExtension() !== ".tex") {
    setStatus("Select a .tex file before compiling.");
    compilerLog.textContent = "Compilation is available only for .tex files.";
    compilerLog.style.display = "block";
    return;
  }

  const compileButton = document.getElementById("compileBtn");
  compileButton.disabled = true;
  compileButton.textContent = "Compiling...";

  try {
    await saveCurrentFile();
    setStatus("Compiling LaTeX...");
    compilerLog.textContent = "Running LaTeX compiler...";
    compilerLog.style.display = "block";

    const result = await api(
      `/api/compile/${encodeURIComponent(currentProject)}/${encodeRelativePath(currentFile)}`,
      { method: "POST" }
    );

    markdownPreview.style.display = "none";
    compilerLog.style.display = "none";
    pdfPreview.src = `${result.pdf_url}?t=${Date.now()}`;
    pdfPreview.style.display = "block";
    setStatus("Compilation succeeded.");
  } catch (error) {
    pdfPreview.style.display = "none";
    markdownPreview.style.display = "none";
    compilerLog.textContent =
      error.payload?.log || error.payload?.message || error.message;
    compilerLog.style.display = "block";
    setStatus(`Compilation failed: ${error.message}`);
    console.error("LaTeX compilation failed:", error.payload || error);
  } finally {
    compileButton.disabled = false;
    compileButton.textContent = "Compile LaTeX";
  }
}

function findMatches() {
  const query = searchInput.value;
  searchMatches = [];
  searchIndex = -1;
  if (!query) return;

  const lowerText = editor.value.toLowerCase();
  const lowerQuery = query.toLowerCase();
  let start = 0;

  while (true) {
    const index = lowerText.indexOf(lowerQuery, start);
    if (index < 0) break;
    searchMatches.push(index);
    start = index + Math.max(1, query.length);
  }
}

function navigateSearch(direction) {
  if (!searchInput.value) return;
  if (!searchMatches.length) findMatches();
  if (!searchMatches.length) {
    setStatus("No matches.");
    return;
  }

  searchIndex =
    (searchIndex + direction + searchMatches.length) % searchMatches.length;
  const start = searchMatches[searchIndex];
  const end = start + searchInput.value.length;
  editor.focus();
  editor.setSelectionRange(start, end);
  updateCursorStatus();
  setStatus(`Match ${searchIndex + 1} of ${searchMatches.length}`);
}

editor.addEventListener("input", event => {
  recordEditorState(event.inputType || "input");
  scheduleAutosave();
  updatePreview();
  updateCursorStatus();
  findMatches();
});

editor.addEventListener("click", updateCursorStatus);
editor.addEventListener("keyup", updateCursorStatus);

editor.addEventListener("beforeinput", event => {
  if (event.inputType === "historyUndo") {
    event.preventDefault();
    undoEditor();
  } else if (event.inputType === "historyRedo") {
    event.preventDefault();
    redoEditor();
  }
});

editor.addEventListener("keydown", event => {
  const modifier = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();
  if (modifier && key === "z") {
    event.preventDefault();
    if (event.shiftKey) redoEditor();
    else undoEditor();
    return;
  }
  if (modifier && key === "y") {
    event.preventDefault();
    redoEditor();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveCurrentFile().catch(error => setStatus(error.message));
  }

  if (event.key === "Tab") {
    event.preventDefault();
    editor.setRangeText(
      "  ",
      editor.selectionStart,
      editor.selectionEnd,
      "end"
    );
    afterProgrammaticEdit();
  }
});

projectSelect.addEventListener("change", async () => {
  if (dirty) await saveCurrentFile();
  currentProject = projectSelect.value;
  await loadProjects(currentProject);
});

document.getElementById("newProjectBtn")
  .addEventListener("click", () => createProject());

document.getElementById("newFileBtn")
  .addEventListener("click", () =>
    createFile().catch(error => setStatus(error.message)));

document.getElementById("newFolderBtn")
  .addEventListener("click", () =>
    createFolder().catch(error => setStatus(error.message)));

document.getElementById("undoBtn")
  ?.addEventListener("click", undoEditor);

document.getElementById("redoBtn")
  ?.addEventListener("click", redoEditor);

document.getElementById("saveBtn")
  .addEventListener("click", () =>
    saveCurrentFile().catch(error => setStatus(error.message)));

document.getElementById("compileBtn")
  .addEventListener("click", compileCurrentFile);

document.getElementById("printBtn")
  .addEventListener("click", () => window.print());

document.getElementById("downloadProjectBtn")
  .addEventListener("click", () => {
    if (!currentProject) return;
    window.location.href =
      `/api/download-project/${encodeURIComponent(currentProject)}`;
  });

document.getElementById("uploadInput")
  .addEventListener("change", event => {
    const file = event.target.files[0];
    uploadFile(file).catch(error => setStatus(error.message));
    event.target.value = "";
  });


fileContextMenu.querySelectorAll("[data-file-action]").forEach(button => {
  button.addEventListener("click", () => {
    handleContextAction(button.dataset.fileAction)
      .catch(error => setStatus(error.message));
  });
});

document.addEventListener("click", event => {
  if (!fileContextMenu.contains(event.target)) hideContextMenu();
});

window.addEventListener("resize", hideContextMenu);
window.addEventListener("blur", hideContextMenu);

document.querySelectorAll("[data-command]").forEach(button => {
  button.addEventListener("click", () =>
    handleToolbar(button.dataset.command));
});

document.querySelectorAll("[data-view]").forEach(button => {
  button.addEventListener("click", () =>
    setView(button.dataset.view));
});

diagramBuilderBtn?.addEventListener("click", () => {
  openDiagramBuilder().catch(error => setStatus(error.message));
});

document.getElementById("diagramBuilderCloseBtn")
  ?.addEventListener("click", closeDiagramBuilder);

document.getElementById("diagramBuilderCancelBtn")
  ?.addEventListener("click", closeDiagramBuilder);

diagramBuilderApplyBtn?.addEventListener("click", () => {
  applyDiagramBuilder().catch(error => setStatus(error.message));
});

diagramBuilderSource?.addEventListener("input", scheduleDiagramBuilderPreview);
diagramDirection?.addEventListener("change", scheduleDiagramBuilderPreview);
diagramPreset?.addEventListener("change", scheduleDiagramBuilderPreview);

document.getElementById("diagramExportSvgBtn")?.addEventListener("click", () => {
  saveDiagramAsset("svg").catch(error => {
    diagramExportStatus.textContent = `Export failed: ${error.message}`;
    setStatus(`Diagram export failed: ${error.message}`);
  });
});
document.getElementById("diagramExportPngBtn")?.addEventListener("click", () => {
  saveDiagramAsset("png").catch(error => {
    diagramExportStatus.textContent = `Export failed: ${error.message}`;
    setStatus(`Diagram export failed: ${error.message}`);
  });
});
document.getElementById("diagramExportPdfBtn")?.addEventListener("click", () => {
  saveDiagramAsset("pdf").catch(error => {
    diagramExportStatus.textContent = `Export failed: ${error.message}`;
    setStatus(`Diagram export failed: ${error.message}`);
  });
});
diagramInsertTarget?.addEventListener("change", updateDiagramInsertControls);
diagramInsertFormat?.addEventListener("change", updateDiagramInsertControls);
diagramExportInsertBtn?.addEventListener("click", () => {
  exportAndInsertDiagram().catch(error => {
    diagramInsertStatus.textContent = `Insert failed: ${error.message}`;
    setStatus(`Diagram insertion failed: ${error.message}`);
  });
});

document.querySelectorAll("[data-diagram-type]").forEach(button => {
  button.addEventListener("click", () => insertDiagramType(button.dataset.diagramType));
});

diagramBuilderModal?.addEventListener("click", event => {
  if (event.target === diagramBuilderModal) closeDiagramBuilder();
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape" && diagramBuilderModal && !diagramBuilderModal.hidden) {
    event.preventDefault();
    closeDiagramBuilder();
  }
});

searchInput.addEventListener("input", findMatches);
document.getElementById("prevSearchBtn")
  .addEventListener("click", () => navigateSearch(-1));
document.getElementById("nextSearchBtn")
  .addEventListener("click", () => navigateSearch(1));

window.addEventListener("beforeunload", event => {
  if (dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

updateDiagramBuilderAvailability();
loadProjects().catch(error => setStatus(`Startup failed: ${error.message}`));
