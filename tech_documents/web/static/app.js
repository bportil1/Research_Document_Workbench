"use strict";

const projectSelect = document.getElementById("projectSelect");
const fileList = document.getElementById("fileList");
const fileContextMenu = document.getElementById("fileContextMenu");
const editor = document.getElementById("editor");
const markdownPreview = document.getElementById("markdownPreview");
const pdfPreview = document.getElementById("pdfPreview");
const compilerLog = document.getElementById("compilerLog");
const buildDiagnostics = document.getElementById("buildDiagnostics");
const buildDiagnosticsTitle = document.getElementById("buildDiagnosticsTitle");
const buildDiagnosticsSummary = document.getElementById("buildDiagnosticsSummary");
const buildDiagnosticsList = document.getElementById("buildDiagnosticsList");
const buildAnywayBtn = document.getElementById("buildAnywayBtn");
const toggleRawLogBtn = document.getElementById("toggleRawLogBtn");
const contextProjectRoot = document.getElementById("contextProjectRoot");
const contextDocumentsRoot = document.getElementById("contextDocumentsRoot");
const contextMainTex = document.getElementById("contextMainTex");
const contextBuildRoot = document.getElementById("contextBuildRoot");
const currentFilename = document.getElementById("currentFilename");
const statusEl = document.getElementById("status");
const cursorStatus = document.getElementById("cursorStatus");
const wordCount = document.getElementById("wordCount");
const outline = document.getElementById("outline");
const editorGrid = document.getElementById("editorGrid");
const searchInput = document.getElementById("searchInput");
const textToolbar = document.getElementById("textToolbar");
const notebookWorkspace = document.getElementById("notebookWorkspace");
const notebookCells = document.getElementById("notebookCells");
const notebookFilename = document.getElementById("notebookFilename");
const notebookKernelStatus = document.getElementById("notebookKernelStatus");
const notebookDependencyNotice = document.getElementById("notebookDependencyNotice");
const notebookPresentation = document.getElementById("notebookPresentation");
const notebookReveal = document.getElementById("notebookReveal");
const notebookRevealSlides = document.getElementById("notebookRevealSlides");
const notebookPresentationTitle = document.getElementById("notebookPresentationTitle");
const notebookPresentationStatus = document.getElementById("notebookPresentationStatus");
const notebookExportDialog = document.getElementById("notebookExportDialog");
const notebookExportPreflight = document.getElementById("notebookExportPreflight");
const notebookExportFormat = document.getElementById("notebookExportFormat");
const notebookExportName = document.getElementById("notebookExportName");
const notebookExportDescription = document.getElementById("notebookExportDescription");
const notebookExportResult = document.getElementById("notebookExportResult");
const notebookExportRunBtn = document.getElementById("notebookExportRunBtn");
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
const projectContextDialog = document.getElementById("projectContextDialog");
const projectRootDisplay = document.getElementById("projectRootDisplay");
const documentsRootInput = document.getElementById("documentsRootInput");
const mainTexSelect = document.getElementById("mainTexSelect");
const projectContextMessage = document.getElementById("projectContextMessage");
const attachProjectDialog = document.getElementById("attachProjectDialog");
const attachProjectPath = document.getElementById("attachProjectPath");
const attachProjectName = document.getElementById("attachProjectName");
const attachProjectMessage = document.getElementById("attachProjectMessage");
const latexProjectDialog = document.getElementById("latexProjectDialog");
const latexProjectDirectory = document.getElementById("latexProjectDirectory");
const latexProjectTemplate = document.getElementById("latexProjectTemplate");
const latexProjectTitle = document.getElementById("latexProjectTitle");
const latexProjectAuthors = document.getElementById("latexProjectAuthors");
const latexCreateBib = document.getElementById("latexCreateBib");
const latexCreateImages = document.getElementById("latexCreateImages");
const latexSetDocumentsRoot = document.getElementById("latexSetDocumentsRoot");
const latexProjectMessage = document.getElementById("latexProjectMessage");

let projects = [];
let currentProject = "";
let currentFile = "";
let selectedItem = null;
let dirty = false;
let autosaveTimer = null;
let searchMatches = [];
let searchIndex = -1;
let activeBuildDiagnostics = [];
let activeBuildDiagnosticIndex = -1;
let lastCompilerLog = "";
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

let notebookDocument = null;
let notebookSelectedIndex = -1;
let notebookRunning = false;
const notebookEditors = new Map();
const notebookMarkdownEditing = new Set();
let notebookRevealDeck = null;
let notebookExportCapabilities = null;

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

function notebookApiUrl(path = currentFile) {
  return `/api/notebooks/${encodeURIComponent(currentProject)}/${encodeRelativePath(path)}`;
}

function isNotebookPath(path) {
  return String(path || "").toLowerCase().endsWith(".ipynb");
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
  updateProjectContextBar(project);
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
    disposeNotebookEditors();
    notebookDocument = null;
    showTextWorkspace();
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
  updateProjectContextBar(projectData());
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
          setStatus(`${node.path} is not an editable Workbench document.`);
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
  if (isNotebookPath(filename)) {
    await openNotebook(filename);
    return;
  }

  disposeNotebookEditors();
  notebookDocument = null;
  showTextWorkspace();
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
  if (isNotebookPath(currentFile)) {
    await saveCurrentNotebook();
    return;
  }
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
  hideRawCompilerLog();
  buildDiagnostics.hidden = true;
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
  const filename = prompt(`New file in ${location}\nFilename (.md, .tex, .bib, .txt, .diagram, or .ipynb):`);
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
    disposeNotebookEditors();
    notebookDocument = null;
    showTextWorkspace();
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


function showTextWorkspace() {
  notebookWorkspace.hidden = true;
  editorGrid.hidden = false;
  textToolbar.hidden = false;
  document.getElementById("compileBtn").disabled = false;
  document.getElementById("printBtn").disabled = false;
}

function showNotebookWorkspace() {
  editorGrid.hidden = true;
  textToolbar.hidden = true;
  notebookWorkspace.hidden = false;
  document.getElementById("compileBtn").disabled = true;
  document.getElementById("printBtn").disabled = true;
  outline.innerHTML = "";
  markdownPreview.style.display = "none";
  pdfPreview.style.display = "none";
  compilerLog.style.display = "none";
}

function disposeNotebookEditor(cellId) {
  const existing = notebookEditors.get(cellId);
  if (!existing) return;
  try {
    existing.destroy();
  } catch (_) {
    // The cell DOM may already have been removed.
  }
  notebookEditors.delete(cellId);
}

function disposeNotebookEditors() {
  Array.from(notebookEditors.keys()).forEach(disposeNotebookEditor);
}

function newNotebookCellId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  }
  return `cell${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function newNotebookCell(kind = "code", source = "") {
  if (kind === "markdown") {
    return {
      cell_type: "markdown",
      id: newNotebookCellId(),
      metadata: {},
      source,
    };
  }
  return {
    cell_type: "code",
    id: newNotebookCellId(),
    metadata: {},
    source,
    execution_count: null,
    outputs: [],
  };
}

function normalizeNotebookDocument(notebook) {
  const normalized = notebook && typeof notebook === "object" ? notebook : {};
  if (!Array.isArray(normalized.cells)) normalized.cells = [];
  if (!normalized.metadata || typeof normalized.metadata !== "object") normalized.metadata = {};
  if (!Number.isInteger(normalized.nbformat)) normalized.nbformat = 4;
  if (!Number.isInteger(normalized.nbformat_minor)) normalized.nbformat_minor = 5;
  normalized.cells.forEach(cell => {
    if (!cell.id) cell.id = newNotebookCellId();
    if (!cell.metadata || typeof cell.metadata !== "object") cell.metadata = {};
    if (Array.isArray(cell.source)) cell.source = cell.source.join("");
    if (typeof cell.source !== "string") cell.source = String(cell.source || "");
    if (cell.cell_type === "code") {
      if (!Array.isArray(cell.outputs)) cell.outputs = [];
      if (!("execution_count" in cell)) cell.execution_count = null;
    }
  });
  return normalized;
}

async function openNotebook(filename) {
  disposeNotebookEditors();
  notebookMarkdownEditing.clear();
  showNotebookWorkspace();
  const data = await api(notebookApiUrl(filename));
  currentFile = data.filename;
  selectedItem = {
    type: "file",
    name: basename(currentFile),
    path: currentFile,
    editable: true,
  };
  ensureCurrentParentsExpanded(currentFile);
  notebookDocument = normalizeNotebookDocument(data.notebook);
  notebookSelectedIndex = notebookDocument.cells.length ? 0 : -1;
  dirty = false;
  notebookFilename.textContent = currentFile;
  currentFilename.textContent = currentFile;
  renderNotebook();
  updateNotebookKernelStatus(data.kernel);
  renderNotebookOutline();
  updateDiagramBuilderAvailability();
  renderFiles();
  setStatus(`Opened notebook ${currentFile}`);
}

async function saveCurrentNotebook() {
  if (!currentProject || !currentFile || !notebookDocument) return;
  await api(notebookApiUrl(), {
    method: "PUT",
    body: JSON.stringify({ notebook: notebookDocument }),
  });
  dirty = false;
  setStatus(`Saved ${currentFile} at ${new Date().toLocaleTimeString()}`);
}

function markNotebookDirty(message = "Unsaved notebook changes") {
  dirty = true;
  setStatus(message);
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => {
    saveCurrentNotebook().catch(error => setStatus(`Save failed: ${error.message}`));
  }, 800);
}

function updateNotebookKernelStatus(kernel) {
  if (!kernel) return;
  notebookKernelStatus.classList.remove("running", "busy");
  if (!kernel.available) {
    notebookKernelStatus.textContent = "Python kernel unavailable";
    notebookDependencyNotice.hidden = false;
    notebookDependencyNotice.textContent =
      "Notebook execution requires nbformat, jupyter_client, and ipykernel. " +
      "Install the Workbench notebook dependencies to run cells; editing and saving remain available.";
    return;
  }
  notebookDependencyNotice.hidden = true;
  if (kernel.running) {
    notebookKernelStatus.textContent = "Python 3 · idle";
    notebookKernelStatus.classList.add("running");
  } else {
    notebookKernelStatus.textContent = "Python 3 · starts on first run";
  }
}

function setNotebookKernelBusy(message = "Python 3 · busy") {
  notebookKernelStatus.textContent = message;
  notebookKernelStatus.classList.remove("running");
  notebookKernelStatus.classList.add("busy");
}

function notebookCellElement(cellId) {
  return Array.from(notebookCells.children).find(
    element => element.dataset?.cellId === cellId
  ) || null;
}

function makeNotebookButton(label, title, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.title = title;
  button.addEventListener("click", event => {
    event.stopPropagation();
    Promise.resolve(handler()).catch(error => setStatus(error.message));
  });
  return button;
}

function notebookText(value) {
  if (Array.isArray(value)) return value.join("");
  if (value === null || value === undefined) return "";
  return String(value);
}

function rewriteNotebookProjectAssets(container) {
  if (!currentProject || !currentFile) return;
  const baseDirectory = dirname(currentFile);
  container.querySelectorAll("img[src]").forEach(image => {
    const source = image.getAttribute("src") || "";
    if (/^(?:https?:|data:|blob:|\/\/|#)/i.test(source)) return;
    const resolved = resolveProjectRelativePath(baseDirectory, source);
    if (!resolved) return;
    image.src = `/api/project-asset/${encodeURIComponent(currentProject)}/${encodeRelativePath(resolved)}`;
  });
}

function renderNotebookMarkdown(cell, index, body) {
  const editing = notebookMarkdownEditing.has(cell.id) || !cell.source.trim();
  if (editing) {
    const input = document.createElement("textarea");
    input.className = "notebook-markdown-editor";
    input.spellcheck = true;
    input.value = cell.source;
    input.placeholder = "Write Markdown…";
    input.addEventListener("input", () => {
      cell.source = input.value;
      markNotebookDirty();
      renderNotebookOutline();
    });
    input.addEventListener("keydown", event => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        notebookMarkdownEditing.delete(cell.id);
        rerenderNotebookCell(index);
      } else if (event.shiftKey && event.key === "Enter") {
        event.preventDefault();
        notebookMarkdownEditing.delete(cell.id);
        rerenderNotebookCell(index);
        if (index + 1 < notebookDocument.cells.length) focusNotebookCell(index + 1);
        else insertNotebookCell("code", notebookDocument.cells.length);
      }
    });
    body.appendChild(input);
    queueMicrotask(() => input.focus());
    return;
  }

  const rendered = document.createElement("article");
  rendered.className = "notebook-markdown-rendered";
  const html = marked.parse(cell.source || "");
  rendered.innerHTML = DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  rendered.querySelectorAll('img[src^="attachment:"]').forEach(image => {
    const name = decodeURIComponent((image.getAttribute("src") || "").slice("attachment:".length));
    const attachment = cell.attachments?.[name];
    if (!attachment) return;
    if (attachment["image/png"]) image.src = `data:image/png;base64,${notebookText(attachment["image/png"])}`;
    else if (attachment["image/jpeg"]) image.src = `data:image/jpeg;base64,${notebookText(attachment["image/jpeg"])}`;
    else if (attachment["image/svg+xml"]) {
      const svg = notebookText(attachment["image/svg+xml"]);
      image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    }
  });
  rewriteNotebookProjectAssets(rendered);
  rendered.querySelectorAll("pre code").forEach(code => hljs.highlightElement(code));
  if (typeof renderMathInElement === "function") {
    renderMathInElement(rendered, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
  }
  rendered.addEventListener("dblclick", () => {
    notebookMarkdownEditing.add(cell.id);
    rerenderNotebookCell(index);
  });
  body.appendChild(rendered);
}

function resizeAceNotebookEditor(aceEditor, host) {
  const lines = Math.max(3, Math.min(22, aceEditor.session.getScreenLength() + 1));
  host.style.height = `${lines * 20 + 18}px`;
  aceEditor.resize();
}

function renderNotebookCode(cell, index, body) {
  const host = document.createElement("div");
  host.className = "notebook-code-editor";
  body.appendChild(host);

  if (window.ace) {
    const aceEditor = window.ace.edit(host);
    notebookEditors.set(cell.id, aceEditor);
    aceEditor.setTheme("ace/theme/tomorrow_night");
    aceEditor.session.setMode("ace/mode/python");
    aceEditor.session.setValue(cell.source || "");
    aceEditor.session.setUseSoftTabs(true);
    aceEditor.session.setTabSize(4);
    aceEditor.session.setUseWrapMode(false);
    aceEditor.setOptions({
      fontSize: "14px",
      showPrintMargin: false,
      highlightActiveLine: true,
      enableBasicAutocompletion: false,
      enableLiveAutocompletion: false,
    });
    aceEditor.commands.addCommand({
      name: "runCellAndAdvance",
      bindKey: { win: "Shift-Enter", mac: "Shift-Enter" },
      exec: () => runNotebookCell(index, true),
    });
    aceEditor.commands.addCommand({
      name: "runCell",
      bindKey: { win: "Ctrl-Enter", mac: "Command-Enter" },
      exec: () => runNotebookCell(index, false),
    });
    aceEditor.commands.addCommand({
      name: "saveNotebook",
      bindKey: { win: "Ctrl-S", mac: "Command-S" },
      exec: () => saveCurrentNotebook().catch(error => setStatus(error.message)),
    });
    aceEditor.session.on("change", () => {
      cell.source = aceEditor.session.getValue();
      resizeAceNotebookEditor(aceEditor, host);
      markNotebookDirty();
    });
    resizeAceNotebookEditor(aceEditor, host);
  } else {
    host.remove();
    const fallback = document.createElement("textarea");
    fallback.className = "notebook-code-fallback";
    fallback.spellcheck = false;
    fallback.value = cell.source || "";
    fallback.placeholder = "Python code…";
    fallback.addEventListener("input", () => {
      cell.source = fallback.value;
      markNotebookDirty();
    });
    fallback.addEventListener("keydown", event => {
      if (event.key === "Tab") {
        event.preventDefault();
        fallback.setRangeText("    ", fallback.selectionStart, fallback.selectionEnd, "end");
        cell.source = fallback.value;
        markNotebookDirty();
      } else if (event.shiftKey && event.key === "Enter") {
        event.preventDefault();
        runNotebookCell(index, true);
      } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        runNotebookCell(index, false);
      }
    });
    body.appendChild(fallback);
  }
}

function renderNotebookRaw(cell, body) {
  const input = document.createElement("textarea");
  input.className = "notebook-code-fallback";
  input.spellcheck = false;
  input.value = cell.source || "";
  input.placeholder = "Raw notebook cell…";
  input.addEventListener("input", () => {
    cell.source = input.value;
    markNotebookDirty();
  });
  body.appendChild(input);
}

function stripAnsi(text) {
  return notebookText(text).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
}

function appendNotebookMimeOutput(container, data) {
  const item = document.createElement("div");
  item.className = "notebook-output-item";

  if (data && data["image/svg+xml"]) {
    item.innerHTML = DOMPurify.sanitize(notebookText(data["image/svg+xml"]), {
      USE_PROFILES: { svg: true, svgFilters: true },
    });
  } else if (data && data["image/png"]) {
    const image = document.createElement("img");
    image.alt = "Notebook output";
    image.src = `data:image/png;base64,${notebookText(data["image/png"])}`;
    item.appendChild(image);
  } else if (data && data["image/jpeg"]) {
    const image = document.createElement("img");
    image.alt = "Notebook output";
    image.src = `data:image/jpeg;base64,${notebookText(data["image/jpeg"])}`;
    item.appendChild(image);
  } else if (data && data["text/html"]) {
    const html = document.createElement("div");
    html.className = "notebook-output-html";
    html.innerHTML = DOMPurify.sanitize(notebookText(data["text/html"]), {
      USE_PROFILES: { html: true },
    });
    rewriteNotebookProjectAssets(html);
    item.appendChild(html);
  } else if (data && data["application/json"] !== undefined) {
    const pre = document.createElement("pre");
    const value = data["application/json"];
    pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    item.appendChild(pre);
  } else {
    const pre = document.createElement("pre");
    pre.textContent = notebookText(data?.["text/plain"] ?? "");
    item.appendChild(pre);
  }
  container.appendChild(item);
}

function renderCellOutputs(cell, container) {
  container.innerHTML = "";
  if (cell.cell_type !== "code") return;
  (cell.outputs || []).forEach(output => {
    if (output.output_type === "stream") {
      const item = document.createElement("div");
      item.className = "notebook-output-item";
      const pre = document.createElement("pre");
      if (output.name === "stderr") pre.className = "stderr";
      pre.textContent = notebookText(output.text);
      item.appendChild(pre);
      container.appendChild(item);
    } else if (output.output_type === "error") {
      const item = document.createElement("div");
      item.className = "notebook-output-item";
      const pre = document.createElement("pre");
      pre.className = "error";
      const traceback = Array.isArray(output.traceback)
        ? output.traceback.map(stripAnsi).join("\n")
        : `${output.ename || "Error"}: ${output.evalue || ""}`;
      pre.textContent = traceback;
      item.appendChild(pre);
      container.appendChild(item);
    } else if (output.output_type === "display_data" || output.output_type === "execute_result") {
      appendNotebookMimeOutput(container, output.data || {});
    }
  });
}


const NOTEBOOK_SLIDE_ROLES = [
  ["", "Normal"],
  ["slide", "New slide"],
  ["subslide", "Sub-slide"],
  ["fragment", "Fragment"],
  ["skip", "Skip"],
  ["notes", "Speaker notes"],
];

function notebookSlideRole(cell) {
  return notebookText(cell?.metadata?.slideshow?.slide_type || "");
}

function setNotebookSlideRole(index, role) {
  const cell = notebookDocument?.cells[index];
  if (!cell) return;
  if (!cell.metadata || typeof cell.metadata !== "object") cell.metadata = {};
  if (!role) {
    if (cell.metadata.slideshow && typeof cell.metadata.slideshow === "object") {
      delete cell.metadata.slideshow.slide_type;
      if (!Object.keys(cell.metadata.slideshow).length) delete cell.metadata.slideshow;
    }
  } else {
    if (!cell.metadata.slideshow || typeof cell.metadata.slideshow !== "object") {
      cell.metadata.slideshow = {};
    }
    cell.metadata.slideshow.slide_type = role;
  }
  markNotebookDirty("Updated presentation role");
  rerenderNotebookCell(index);
}

function notebookSlideRoleSelect(cell, index) {
  const select = document.createElement("select");
  select.className = "notebook-slide-role";
  select.title = "Presentation role";
  const active = notebookSlideRole(cell);
  NOTEBOOK_SLIDE_ROLES.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = active === value;
    select.appendChild(option);
  });
  select.addEventListener("change", event => {
    event.stopPropagation();
    setNotebookSlideRole(index, select.value);
  });
  return select;
}

function renderPresentationMarkdown(cell, container) {
  const rendered = document.createElement("div");
  rendered.className = "notebook-presentation-markdown";
  rendered.innerHTML = DOMPurify.sanitize(marked.parse(cell.source || ""), {
    USE_PROFILES: { html: true },
  });
  rendered.querySelectorAll('img[src^="attachment:"]').forEach(image => {
    const name = decodeURIComponent((image.getAttribute("src") || "").slice("attachment:".length));
    const attachment = cell.attachments?.[name];
    if (!attachment) return;
    if (attachment["image/png"]) image.src = `data:image/png;base64,${notebookText(attachment["image/png"])}`;
    else if (attachment["image/jpeg"]) image.src = `data:image/jpeg;base64,${notebookText(attachment["image/jpeg"])}`;
    else if (attachment["image/svg+xml"]) {
      image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(notebookText(attachment["image/svg+xml"]))}`;
    }
  });
  rewriteNotebookProjectAssets(rendered);
  rendered.querySelectorAll("pre code").forEach(code => hljs.highlightElement(code));
  if (typeof renderMathInElement === "function") {
    renderMathInElement(rendered, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
  }
  container.appendChild(rendered);
}

function renderPresentationCode(cell, index, container) {
  const shell = document.createElement("div");
  shell.className = "notebook-presentation-code";
  const header = document.createElement("div");
  header.className = "notebook-presentation-code-header";
  const label = document.createElement("span");
  label.textContent = `Python · In [${cell.execution_count ?? " "}]`;
  const run = document.createElement("button");
  run.type = "button";
  run.textContent = "Run live";
  run.title = "Execute this cell using the notebook's current Python kernel";
  run.addEventListener("click", event => {
    event.stopPropagation();
    runNotebookCell(index, false).catch(error => setStatus(`Run failed: ${error.message}`));
  });
  header.append(label, run);
  shell.appendChild(header);
  const pre = document.createElement("pre");
  const code = document.createElement("code");
  code.className = "language-python";
  code.textContent = cell.source || "";
  pre.appendChild(code);
  shell.appendChild(pre);
  hljs.highlightElement(code);
  const output = document.createElement("div");
  output.className = "notebook-output notebook-presentation-output";
  renderCellOutputs(cell, output);
  shell.appendChild(output);
  container.appendChild(shell);
}

function ensurePresentationGroup(groups) {
  if (!groups.length) groups.push([[]]);
  const horizontal = groups[groups.length - 1];
  if (!horizontal.length) horizontal.push([]);
  return horizontal[horizontal.length - 1];
}

function presentationGroups() {
  const groups = [];
  let currentVertical = null;
  (notebookDocument?.cells || []).forEach((cell, index) => {
    const role = notebookSlideRole(cell);
    if (role === "skip") return;
    if (role === "slide" || !currentVertical) {
      groups.push([[]]);
      currentVertical = groups[groups.length - 1][0];
    } else if (role === "subslide") {
      groups[groups.length - 1].push([]);
      currentVertical = groups[groups.length - 1][groups[groups.length - 1].length - 1];
    }
    currentVertical = currentVertical || ensurePresentationGroup(groups);
    currentVertical.push({ cell, index, role });
  });
  return groups;
}

function renderPresentationCell(entry, container) {
  const { cell, index, role } = entry;
  if (role === "notes") {
    const notes = document.createElement("aside");
    notes.className = "notes";
    notes.dataset.presentationCellId = cell.id;
    if (cell.cell_type === "markdown") renderPresentationMarkdown(cell, notes);
    else notes.textContent = cell.source || "";
    container.appendChild(notes);
    return;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "notebook-presentation-cell";
  wrapper.dataset.presentationCellId = cell.id;
  if (role === "fragment") wrapper.classList.add("fragment");
  if (cell.cell_type === "markdown") renderPresentationMarkdown(cell, wrapper);
  else if (cell.cell_type === "code") renderPresentationCode(cell, index, wrapper);
  else {
    const pre = document.createElement("pre");
    pre.textContent = cell.source || "";
    wrapper.appendChild(pre);
  }
  container.appendChild(wrapper);
}

function buildNotebookPresentationSlides() {
  notebookRevealSlides.innerHTML = "";
  const groups = presentationGroups();
  if (!groups.length) {
    const section = document.createElement("section");
    section.innerHTML = "<h2>Empty presentation</h2><p>Add notebook cells or change cells from Skip.</p>";
    notebookRevealSlides.appendChild(section);
    return;
  }
  groups.forEach(verticalSlides => {
    const horizontal = document.createElement("section");
    verticalSlides.forEach(entries => {
      const slide = document.createElement("section");
      entries.forEach(entry => renderPresentationCell(entry, slide));
      horizontal.appendChild(slide);
    });
    notebookRevealSlides.appendChild(horizontal);
  });
}

async function openNotebookPresentation() {
  if (!notebookDocument || !currentFile) return;
  if (!window.Reveal) {
    setStatus("Reveal.js is not installed. Run python3 scripts/vendor_reveal.py once.");
    return;
  }
  if (dirty) await saveCurrentNotebook();
  buildNotebookPresentationSlides();
  notebookPresentationTitle.textContent = basename(currentFile);
  notebookPresentationStatus.textContent = "Live notebook · same Python kernel · exports never execute cells";
  notebookPresentation.hidden = false;
  notebookRevealDeck = new window.Reveal(notebookReveal, {
    embedded: true,
    hash: false,
    controls: true,
    progress: true,
    center: false,
    transition: "slide",
    margin: 0.08,
  });
  await notebookRevealDeck.initialize();
  notebookRevealDeck.focus();
  setStatus(`Presenting ${currentFile}`);
}

async function closeNotebookPresentation() {
  if (notebookRevealDeck) {
    try { notebookRevealDeck.destroy(); } catch (_) { /* presentation is already leaving */ }
  }
  notebookRevealDeck = null;
  notebookPresentation.hidden = true;
  setStatus(currentFile ? `Returned to ${currentFile}` : "Ready");
}

function refreshNotebookPresentationCell(index) {
  if (notebookPresentation.hidden || !notebookDocument?.cells[index]) return;
  const cell = notebookDocument.cells[index];
  const wrapper = notebookRevealSlides.querySelector(`[data-presentation-cell-id="${CSS.escape(cell.id)}"]`);
  if (!wrapper || cell.cell_type !== "code") return;
  const label = wrapper.querySelector(".notebook-presentation-code-header span");
  if (label) label.textContent = `Python · In [${cell.execution_count ?? " "}]`;
  const output = wrapper.querySelector(".notebook-presentation-output");
  if (output) renderCellOutputs(cell, output);
  notebookRevealDeck?.sync();
}

function renderNotebookExportPreflight(capabilities) {
  notebookExportPreflight.innerHTML = "";
  [
    ["nbconvert", "Notebook exporter", "HTML / Markdown"],
    ["reveal", "Reveal.js", "Live + offline HTML slides"],
    ["quarto", "Quarto", "Word / PowerPoint + export orchestration"],
    ["latex", "LaTeX", "PDF / Beamer"],
  ].forEach(([key, label, detail]) => {
    const row = document.createElement("div");
    row.className = `notebook-export-capability ${capabilities[key] ? "available" : "missing"}`;
    row.innerHTML = `<strong>${label}</strong><span>${capabilities[key] ? "Ready" : "Unavailable"}</span><small>${detail}</small>`;
    notebookExportPreflight.appendChild(row);
  });
}

function updateNotebookExportSelection() {
  const selected = notebookExportCapabilities?.formats?.find(item => item.id === notebookExportFormat.value);
  if (!selected) {
    notebookExportDescription.textContent = "";
    notebookExportRunBtn.disabled = true;
    return;
  }
  notebookExportDescription.textContent = selected.available
    ? selected.description
    : selected.reason;
  notebookExportRunBtn.disabled = !selected.available;
}

async function openNotebookExportDialog() {
  if (!notebookDocument || !currentFile) return;
  if (dirty) await saveCurrentNotebook();
  notebookExportResult.textContent = "Checking export capabilities…";
  notebookExportCapabilities = await api(`${notebookApiUrl()}/exports`);
  renderNotebookExportPreflight(notebookExportCapabilities);
  notebookExportFormat.innerHTML = "";
  notebookExportCapabilities.formats.forEach(format => {
    const option = document.createElement("option");
    option.value = format.id;
    option.disabled = !format.available;
    option.textContent = `${format.kind === "presentation" ? "Presentation" : "Document"} · ${format.label}${format.available ? "" : " — unavailable"}`;
    notebookExportFormat.appendChild(option);
  });
  const firstAvailable = notebookExportCapabilities.formats.find(item => item.available);
  if (firstAvailable) notebookExportFormat.value = firstAvailable.id;
  notebookExportName.value = basename(currentFile).replace(/\.ipynb$/i, "");
  notebookExportResult.textContent = "Exports are written to builds/notebooks/ and use stored outputs only.";
  updateNotebookExportSelection();
  notebookExportDialog.showModal();
}

async function runNotebookExport() {
  const selected = notebookExportCapabilities?.formats?.find(item => item.id === notebookExportFormat.value);
  if (!selected?.available) return;
  notebookExportRunBtn.disabled = true;
  notebookExportResult.textContent = `Exporting ${selected.label}…`;
  try {
    const result = await api(`${notebookApiUrl()}/exports`, {
      method: "POST",
      body: JSON.stringify({
        format: selected.id,
        output_name: notebookExportName.value.trim(),
      }),
    });
    notebookExportResult.innerHTML = "";
    const message = document.createElement("span");
    message.textContent = `Created ${result.path} `;
    const link = document.createElement("a");
    link.href = result.download_url;
    link.textContent = "Download";
    link.target = "_blank";
    notebookExportResult.append(message, link);
    await loadProjects(currentProject, currentFile);
    setStatus(`Exported ${result.path}`);
  } finally {
    notebookExportRunBtn.disabled = false;
  }
}

function renderNotebookCell(cell, index) {
  if (!cell.id) cell.id = newNotebookCellId();
  const article = document.createElement("article");
  article.className = "notebook-cell";
  article.dataset.cellId = cell.id;
  article.dataset.index = String(index);
  if (index === notebookSelectedIndex) article.classList.add("selected");
  article.addEventListener("click", () => {
    notebookSelectedIndex = index;
    notebookCells.querySelectorAll(".notebook-cell").forEach((node, nodeIndex) => {
      node.classList.toggle("selected", nodeIndex === index);
    });
  });

  const gutter = document.createElement("div");
  gutter.className = "notebook-cell-gutter";
  gutter.textContent = cell.cell_type === "code"
    ? `In [${cell.execution_count ?? " "}]:`
    : cell.cell_type === "markdown" ? "Markdown" : "Raw";
  article.appendChild(gutter);

  const main = document.createElement("div");
  main.className = "notebook-cell-main";
  article.appendChild(main);

  const header = document.createElement("div");
  header.className = "notebook-cell-header";
  const kind = document.createElement("span");
  kind.className = "notebook-cell-kind";
  kind.textContent = cell.cell_type === "code"
    ? "Python"
    : cell.cell_type === "markdown" ? "Markdown" : "Raw";
  header.appendChild(kind);

  const actions = document.createElement("div");
  actions.className = "notebook-cell-actions";
  if (cell.cell_type === "code") {
    actions.appendChild(makeNotebookButton("Run", "Run cell (Ctrl+Enter)", () => runNotebookCell(index, false)));
    actions.appendChild(makeNotebookButton("Run ↓", "Run cell and advance (Shift+Enter)", () => runNotebookCell(index, true)));
  } else if (cell.cell_type === "markdown") {
    const label = notebookMarkdownEditing.has(cell.id) || !cell.source.trim() ? "Render" : "Edit";
    actions.appendChild(makeNotebookButton(label, "Toggle Markdown editing/rendering", () => {
      if (notebookMarkdownEditing.has(cell.id)) notebookMarkdownEditing.delete(cell.id);
      else notebookMarkdownEditing.add(cell.id);
      rerenderNotebookCell(index);
    }));
  }

  actions.appendChild(makeNotebookButton("+↑", "Insert cell above", () => insertNotebookCell("code", index)));
  actions.appendChild(makeNotebookButton("+↓", "Insert cell below", () => insertNotebookCell("code", index + 1)));
  actions.appendChild(makeNotebookButton("↑", "Move cell up", () => moveNotebookCell(index, -1)));
  actions.appendChild(makeNotebookButton("↓", "Move cell down", () => moveNotebookCell(index, 1)));
  actions.appendChild(makeNotebookButton("Duplicate", "Duplicate cell", () => duplicateNotebookCell(index)));

  const typeSelect = document.createElement("select");
  typeSelect.title = "Cell type";
  [["code", "Code"], ["markdown", "Markdown"], ["raw", "Raw"]].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = cell.cell_type === value;
    typeSelect.appendChild(option);
  });
  typeSelect.addEventListener("change", event => {
    event.stopPropagation();
    changeNotebookCellType(index, typeSelect.value);
  });
  actions.appendChild(typeSelect);
  actions.appendChild(notebookSlideRoleSelect(cell, index));
  actions.appendChild(makeNotebookButton("Delete", "Delete cell", () => deleteNotebookCell(index)));
  header.appendChild(actions);
  main.appendChild(header);

  const body = document.createElement("div");
  body.className = "notebook-cell-body";
  if (cell.cell_type === "markdown") renderNotebookMarkdown(cell, index, body);
  else if (cell.cell_type === "code") renderNotebookCode(cell, index, body);
  else renderNotebookRaw(cell, body);
  main.appendChild(body);

  const output = document.createElement("div");
  output.className = "notebook-output";
  renderCellOutputs(cell, output);
  main.appendChild(output);
  return article;
}

function renderNotebook() {
  disposeNotebookEditors();
  notebookCells.innerHTML = "";
  if (!notebookDocument) return;
  notebookDocument.cells.forEach((cell, index) => {
    notebookCells.appendChild(renderNotebookCell(cell, index));
  });
  if (!notebookDocument.cells.length) {
    const empty = document.createElement("div");
    empty.className = "notebook-dependency-notice";
    empty.textContent = "This notebook has no cells. Add a Markdown or code cell to begin.";
    notebookCells.appendChild(empty);
  }
}

function rerenderNotebookCell(index) {
  if (!notebookDocument?.cells[index]) return;
  const cell = notebookDocument.cells[index];
  const existing = notebookCellElement(cell.id);
  disposeNotebookEditor(cell.id);
  const replacement = renderNotebookCell(cell, index);
  if (existing) existing.replaceWith(replacement);
  else renderNotebook();
  renderNotebookOutline();
}

function renderNotebookOutline() {
  outline.innerHTML = "";
  if (!notebookDocument) return;
  notebookDocument.cells.forEach((cell, index) => {
    if (cell.cell_type !== "markdown") return;
    notebookText(cell.source).split("\n").forEach(line => {
      const match = /^(#{1,4})\s+(.+?)\s*$/.exec(line);
      if (!match) return;
      const link = document.createElement("a");
      link.href = "#";
      link.className = `level-${Math.min(4, match[1].length)}`;
      link.textContent = match[2];
      link.addEventListener("click", event => {
        event.preventDefault();
        notebookSelectedIndex = index;
        notebookCellElement(cell.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      outline.appendChild(link);
    });
  });
}

function insertNotebookCell(kind, index) {
  if (!notebookDocument) return;
  const safeIndex = Math.max(0, Math.min(notebookDocument.cells.length, index));
  const cell = newNotebookCell(kind);
  notebookDocument.cells.splice(safeIndex, 0, cell);
  notebookSelectedIndex = safeIndex;
  if (kind === "markdown") notebookMarkdownEditing.add(cell.id);
  markNotebookDirty();
  renderNotebook();
  renderNotebookOutline();
  queueMicrotask(() => focusNotebookCell(safeIndex));
}

function deleteNotebookCell(index) {
  if (!notebookDocument?.cells[index]) return;
  const cell = notebookDocument.cells[index];
  if (!confirm(`Delete this ${cell.cell_type} cell?`)) return;
  disposeNotebookEditor(cell.id);
  notebookMarkdownEditing.delete(cell.id);
  notebookDocument.cells.splice(index, 1);
  notebookSelectedIndex = Math.min(index, notebookDocument.cells.length - 1);
  markNotebookDirty();
  renderNotebook();
  renderNotebookOutline();
}

function duplicateNotebookCell(index) {
  if (!notebookDocument?.cells[index]) return;
  const source = notebookDocument.cells[index];
  const copy = JSON.parse(JSON.stringify(source));
  copy.id = newNotebookCellId();
  if (copy.cell_type === "code") {
    copy.execution_count = null;
    copy.outputs = [];
  }
  notebookDocument.cells.splice(index + 1, 0, copy);
  notebookSelectedIndex = index + 1;
  markNotebookDirty();
  renderNotebook();
  renderNotebookOutline();
  queueMicrotask(() => focusNotebookCell(index + 1));
}

function moveNotebookCell(index, direction) {
  if (!notebookDocument?.cells[index]) return;
  const destination = index + direction;
  if (destination < 0 || destination >= notebookDocument.cells.length) return;
  const [cell] = notebookDocument.cells.splice(index, 1);
  notebookDocument.cells.splice(destination, 0, cell);
  notebookSelectedIndex = destination;
  markNotebookDirty();
  renderNotebook();
  renderNotebookOutline();
  queueMicrotask(() => focusNotebookCell(destination));
}

function changeNotebookCellType(index, cellType) {
  const cell = notebookDocument?.cells[index];
  if (!cell || cell.cell_type === cellType) return;
  disposeNotebookEditor(cell.id);
  cell.cell_type = cellType;
  if (cellType === "code") {
    cell.execution_count = null;
    cell.outputs = [];
    delete cell.attachments;
  } else {
    delete cell.execution_count;
    delete cell.outputs;
    if (cellType === "markdown") notebookMarkdownEditing.add(cell.id);
    else {
      delete cell.attachments;
      notebookMarkdownEditing.delete(cell.id);
    }
  }
  markNotebookDirty();
  rerenderNotebookCell(index);
}

function focusNotebookCell(index) {
  const cell = notebookDocument?.cells[index];
  if (!cell) return;
  notebookSelectedIndex = index;
  const element = notebookCellElement(cell.id);
  element?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const aceEditor = notebookEditors.get(cell.id);
  if (aceEditor) {
    aceEditor.focus();
    return;
  }
  const input = element?.querySelector("textarea");
  if (input) input.focus();
  else if (cell.cell_type === "markdown") {
    notebookMarkdownEditing.add(cell.id);
    rerenderNotebookCell(index);
  }
}

function refreshNotebookCellResult(index) {
  const cell = notebookDocument?.cells[index];
  if (!cell) return;
  const element = notebookCellElement(cell.id);
  if (!element) return;
  const gutter = element.querySelector(".notebook-cell-gutter");
  if (gutter && cell.cell_type === "code") {
    gutter.textContent = `In [${cell.execution_count ?? " "}]:`;
  }
  const output = element.querySelector(".notebook-output");
  if (output) renderCellOutputs(cell, output);
}

async function executeNotebookCell(index) {
  const cell = notebookDocument?.cells[index];
  if (!cell || cell.cell_type !== "code") return false;
  const element = notebookCellElement(cell.id);
  element?.classList.add("notebook-cell-running");
  setNotebookKernelBusy(`Python 3 · running cell ${index + 1}`);
  try {
    const result = await api(`${notebookApiUrl()}/execute`, {
      method: "POST",
      body: JSON.stringify({ source: cell.source || "" }),
    });
    cell.execution_count = result.execution_count ?? null;
    cell.outputs = Array.isArray(result.outputs) ? result.outputs : [];
    updateNotebookKernelStatus(result.kernel);
    refreshNotebookCellResult(index);
    refreshNotebookPresentationCell(index);
    markNotebookDirty(`Executed cell ${index + 1}`);
    return true;
  } catch (error) {
    notebookKernelStatus.textContent = "Python 3 · execution failed";
    notebookKernelStatus.classList.remove("busy", "running");
    throw error;
  } finally {
    element?.classList.remove("notebook-cell-running");
  }
}

async function runNotebookCell(index, advance = false) {
  if (notebookRunning) {
    setStatus("A notebook execution is already in progress.");
    return;
  }
  notebookRunning = true;
  setNotebookControlsDisabled(true);
  try {
    await executeNotebookCell(index);
    if (advance) {
      if (index + 1 < notebookDocument.cells.length) {
        focusNotebookCell(index + 1);
      } else {
        insertNotebookCell("code", notebookDocument.cells.length);
      }
    }
  } finally {
    notebookRunning = false;
    setNotebookControlsDisabled(false);
  }
}

function setNotebookControlsDisabled(disabled) {
  [
    "notebookRunAllBtn",
    "notebookRestartRunAllBtn",
    "notebookRestartBtn",
    "notebookClearOutputsBtn",
  ].forEach(id => {
    const button = document.getElementById(id);
    if (button) button.disabled = disabled;
  });
  const interrupt = document.getElementById("notebookInterruptBtn");
  if (interrupt) interrupt.disabled = false;
}

async function runAllNotebookCells() {
  if (!notebookDocument || notebookRunning) return;
  notebookRunning = true;
  setNotebookControlsDisabled(true);
  try {
    for (let index = 0; index < notebookDocument.cells.length; index += 1) {
      if (notebookDocument.cells[index].cell_type === "code") {
        await executeNotebookCell(index);
      }
    }
    setStatus("Notebook run complete.");
  } finally {
    notebookRunning = false;
    setNotebookControlsDisabled(false);
  }
}

async function interruptNotebookKernel() {
  if (!currentFile || !isNotebookPath(currentFile)) return;
  setNotebookKernelBusy("Python 3 · interrupting…");
  const result = await api(`${notebookApiUrl()}/kernel/interrupt`, { method: "POST" });
  setStatus(result.interrupted ? "Kernel interrupt requested." : "No running kernel to interrupt.");
  const status = await api(`${notebookApiUrl()}/kernel`);
  updateNotebookKernelStatus(status);
}

async function restartNotebookKernel() {
  if (!currentFile || !isNotebookPath(currentFile)) return;
  setNotebookKernelBusy("Python 3 · restarting…");
  const result = await api(`${notebookApiUrl()}/kernel/restart`, { method: "POST" });
  updateNotebookKernelStatus(result.kernel);
  setStatus("Python kernel restarted.");
}

async function restartAndRunAllNotebookCells() {
  if (notebookRunning) return;
  await restartNotebookKernel();
  await runAllNotebookCells();
}

function clearNotebookOutputs() {
  if (!notebookDocument) return;
  notebookDocument.cells.forEach((cell, index) => {
    if (cell.cell_type !== "code") return;
    cell.outputs = [];
    cell.execution_count = null;
    refreshNotebookCellResult(index);
  });
  markNotebookDirty("Cleared notebook outputs");
}

async function createNotebook(targetFolder = selectedFolder()) {
  if (!currentProject) return;
  const location = targetFolder || "project root";
  let filename = prompt(`New Python notebook in ${location}\nFilename:`, "analysis.ipynb");
  if (!filename) return;
  if (filename.includes("/") || filename.includes("\\")) {
    setStatus("Enter a filename only; select the destination folder in the sidebar.");
    return;
  }
  if (!filename.toLowerCase().endsWith(".ipynb")) filename += ".ipynb";
  const path = joinPath(targetFolder, filename);
  await api(`/api/files/${encodeURIComponent(currentProject)}`, {
    method: "POST",
    body: JSON.stringify({ path, content: "" }),
  });
  ensureCurrentParentsExpanded(path);
  await loadProjects(currentProject, path);
}



function updateProjectContextBar(project) {
  if (!project) {
    contextProjectRoot.textContent = "—";
    contextDocumentsRoot.textContent = "—";
    contextMainTex.textContent = "—";
    contextBuildRoot.textContent = "—";
    return;
  }
  contextProjectRoot.textContent = project.project_root || project.name;
  contextDocumentsRoot.textContent = project.documents_root || ".";
  contextMainTex.textContent = project.main_tex || "not set";
  contextBuildRoot.textContent = project.build_root || project.documents_path || project.project_root || "—";
}

function openProjectContextDialog() {
  const project = projectData();
  if (!project) return;
  projectRootDisplay.value = project.project_root || "";
  documentsRootInput.value = project.documents_root || "";
  mainTexSelect.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "— use currently opened .tex file —";
  mainTexSelect.appendChild(none);
  (project.files || [])
    .filter(file => file.editable && file.path.toLowerCase().endsWith(".tex"))
    .forEach(file => {
      const option = document.createElement("option");
      option.value = file.path;
      option.textContent = file.path;
      mainTexSelect.appendChild(option);
    });
  mainTexSelect.value = project.main_tex || "";
  projectContextMessage.textContent = project.linked
    ? "Attached project: files remain in their original repository."
    : "Workbench-managed project.";
  projectContextDialog.showModal();
}

async function saveProjectContext() {
  if (!currentProject) return;
  projectContextMessage.textContent = "Saving directory context…";
  try {
    const data = await api(`/api/projects/${encodeURIComponent(currentProject)}/context`, {
      method: "PUT",
      body: JSON.stringify({
        documents_root: documentsRootInput.value.trim(),
        main_tex: mainTexSelect.value,
      }),
    });
    projectContextDialog.close();
    await loadProjects(currentProject, currentFile);
    setStatus(`Documents Root set to ${data.documents_root || "project root"}.`);
  } catch (error) {
    projectContextMessage.textContent = error.message;
  }
}

function openAttachProjectDialog() {
  attachProjectPath.value = "";
  attachProjectName.value = "";
  attachProjectMessage.textContent = "The folder is opened in place; it is not copied into Workbench.";
  attachProjectDialog.showModal();
}

async function attachExistingProject() {
  attachProjectMessage.textContent = "Attaching folder…";
  try {
    const data = await api("/api/projects/link", {
      method: "POST",
      body: JSON.stringify({ path: attachProjectPath.value.trim(), name: attachProjectName.value.trim() }),
    });
    attachProjectDialog.close();
    await loadProjects(data.project);
    setStatus(`Attached ${data.context.project_root}`);
  } catch (error) {
    attachProjectMessage.textContent = error.message;
  }
}

function openLatexProjectDialog() {
  const project = projectData();
  if (!project) return;
  latexProjectDirectory.value = project.documents_root || selectedFolder() || "";
  latexProjectTitle.value = "Research Document";
  latexProjectAuthors.value = "";
  latexCreateBib.checked = true;
  latexCreateImages.checked = true;
  latexSetDocumentsRoot.checked = true;
  latexProjectMessage.textContent = "Creates main.tex plus optional bib.bib and images/.";
  latexProjectDialog.showModal();
}

async function createLatexProjectFromDialog() {
  if (!currentProject) return;
  latexProjectMessage.textContent = "Creating LaTeX project…";
  try {
    const data = await api(`/api/latex/projects/${encodeURIComponent(currentProject)}`, {
      method: "POST",
      body: JSON.stringify({
        directory: latexProjectDirectory.value.trim(),
        template: latexProjectTemplate.value,
        title: latexProjectTitle.value,
        authors: latexProjectAuthors.value,
        create_bibliography: latexCreateBib.checked,
        create_images: latexCreateImages.checked,
        set_documents_root: latexSetDocumentsRoot.checked,
      }),
    });
    latexProjectDialog.close();
    await loadProjects(currentProject, data.main_tex);
    setStatus(`Created ${data.template} LaTeX project at ${data.directory || "project root"}.`);
  } catch (error) {
    latexProjectMessage.textContent = error.message;
  }
}

function diagnosticSummary(diagnostics) {
  const items = diagnostics || [];
  const errors = items.filter(item => item.severity === "error" && !item.secondary).length;
  const warnings = items.filter(item => item.severity === "warning" && !item.secondary).length;
  const secondary = items.filter(item => item.secondary).length;
  const parts = [];
  if (errors) parts.push(`${errors} error${errors === 1 ? "" : "s"}`);
  if (warnings) parts.push(`${warnings} warning${warnings === 1 ? "" : "s"}`);
  if (secondary) parts.push(`${secondary} downstream message${secondary === 1 ? "" : "s"} suppressed`);
  return parts.join(" · ") || "No structured issues";
}

function clearBuildDiagnostics() {
  activeBuildDiagnostics = [];
  activeBuildDiagnosticIndex = -1;
  buildDiagnostics.hidden = true;
  buildDiagnosticsList.innerHTML = "";
  buildAnywayBtn.hidden = true;
  document.getElementById("prevBuildErrorBtn").disabled = true;
  document.getElementById("nextBuildErrorBtn").disabled = true;
}

function hideRawCompilerLog() {
  compilerLog.style.display = "none";
  toggleRawLogBtn.textContent = "Show raw log";
}

function toggleRawCompilerLog() {
  const showing = compilerLog.style.display === "block";
  if (showing) {
    hideRawCompilerLog();
  } else {
    compilerLog.textContent = lastCompilerLog || "No raw compiler log is available for this result.";
    compilerLog.style.display = "block";
    toggleRawLogBtn.textContent = "Hide raw log";
  }
}

function resolveDiagnosticPath(diagnostic) {
  const raw = String(diagnostic?.file || "").replace(/^\.\//, "");
  if (!raw) return "";
  const project = projectData();
  if (!project) return "";
  const exact = project.files.find(file => file.path === raw && file.editable);
  if (exact) return exact.path;
  const matches = project.files.filter(file => file.editable && (file.path === raw || file.path.endsWith(`/${raw}`) || file.name === raw));
  return matches.length === 1 ? matches[0].path : "";
}

function lineOffset(text, lineNumber) {
  const target = Math.max(1, Number(lineNumber) || 1);
  if (target === 1) return 0;
  let line = 1;
  let index = 0;
  while (line < target) {
    const next = text.indexOf("\n", index);
    if (next < 0) return text.length;
    index = next + 1;
    line += 1;
  }
  return index;
}

async function jumpToLine(lineNumber, path = currentFile) {
  const savedDiagnostics = [...activeBuildDiagnostics];
  const savedIndex = activeBuildDiagnosticIndex;
  if (path && path !== currentFile) await openFile(path);
  const offset = lineOffset(editor.value, lineNumber);
  editor.focus();
  editor.setSelectionRange(offset, offset);
  const totalLines = Math.max(1, editor.value.split("\n").length);
  const ratio = totalLines <= 1 ? 0 : (Math.max(1, Number(lineNumber) || 1) - 1) / (totalLines - 1);
  editor.scrollTop = ratio * Math.max(0, editor.scrollHeight - editor.clientHeight);
  updateCursorStatus();
  if (savedDiagnostics.length) {
    activeBuildDiagnostics = savedDiagnostics;
    activeBuildDiagnosticIndex = savedIndex;
    renderBuildDiagnostics(savedDiagnostics, { title: buildDiagnosticsTitle.textContent || "LaTeX diagnostics" });
  }
}

async function jumpToDiagnostic(index) {
  const navigable = activeBuildDiagnostics
    .map((item, itemIndex) => ({ item, itemIndex }))
    .filter(entry => entry.item.line || entry.item.file);
  if (!navigable.length) return;
  let position = navigable.findIndex(entry => entry.itemIndex === activeBuildDiagnosticIndex);
  if (position < 0) position = 0;
  const direction = index < activeBuildDiagnosticIndex ? -1 : 1;
  position = (position + direction + navigable.length) % navigable.length;
  const selected = navigable[position];
  activeBuildDiagnosticIndex = selected.itemIndex;
  const diagnostic = selected.item;
  const path = resolveDiagnosticPath(diagnostic);
  if (diagnostic.line) {
    await jumpToLine(diagnostic.line, path || currentFile);
  } else if (path && path !== currentFile) {
    await openFile(path);
  }
}

function renderBuildDiagnostics(diagnostics, options = {}) {
  activeBuildDiagnostics = [...(diagnostics || [])];
  activeBuildDiagnosticIndex = activeBuildDiagnostics.length ? 0 : -1;
  buildDiagnostics.hidden = false;
  buildDiagnosticsTitle.textContent = options.title || "LaTeX diagnostics";
  buildDiagnosticsSummary.textContent = options.summary || diagnosticSummary(activeBuildDiagnostics);
  buildAnywayBtn.hidden = !options.allowForce;
  buildDiagnosticsList.innerHTML = "";

  const primary = activeBuildDiagnostics.filter(item => !item.secondary);
  const secondaryCount = activeBuildDiagnostics.length - primary.length;
  const displayItems = primary.length ? primary : activeBuildDiagnostics;
  displayItems.forEach((item, displayIndex) => {
    const actualIndex = activeBuildDiagnostics.indexOf(item);
    const card = document.createElement("article");
    card.className = `build-diagnostic ${item.severity || "warning"}${item.secondary ? " secondary" : ""}`;
    const title = document.createElement("div");
    title.className = "build-diagnostic-title";
    const message = document.createElement("span");
    message.textContent = item.message || "LaTeX issue";
    title.appendChild(message);
    if (item.file || item.line) {
      const location = document.createElement("span");
      location.className = "build-diagnostic-location";
      location.textContent = `${item.file || currentFile}${item.line ? `:${item.line}` : ""}`;
      title.appendChild(location);
    }
    card.appendChild(title);
    if (item.suggestion) {
      const suggestion = document.createElement("div");
      suggestion.className = "build-diagnostic-suggestion";
      suggestion.textContent = item.suggestion;
      card.appendChild(suggestion);
    }
    if (item.detail) {
      const detail = document.createElement("div");
      detail.className = "build-diagnostic-detail";
      detail.textContent = item.detail;
      card.appendChild(detail);
    }
    if (item.line || item.file) {
      const actions = document.createElement("div");
      actions.className = "build-diagnostic-actions";
      const jump = document.createElement("button");
      jump.type = "button";
      jump.textContent = item.line ? "Open / jump to issue" : "Open file";
      jump.addEventListener("click", () => jumpToDiagnostic(actualIndex).catch(error => setStatus(error.message)));
      actions.appendChild(jump);
      card.appendChild(actions);
    }
    buildDiagnosticsList.appendChild(card);
  });

  if (secondaryCount) {
    const note = document.createElement("div");
    note.className = "build-diagnostic secondary";
    note.textContent = `${secondaryCount} downstream warning${secondaryCount === 1 ? "" : "s"} hidden because a primary failure should be fixed first.`;
    buildDiagnosticsList.appendChild(note);
  }

  const navigable = activeBuildDiagnostics.filter(item => item.line || item.file);
  document.getElementById("prevBuildErrorBtn").disabled = navigable.length === 0;
  document.getElementById("nextBuildErrorBtn").disabled = navigable.length === 0;
  markdownPreview.style.display = "none";
  pdfPreview.style.display = "none";
}

async function compileCurrentFile(force = false) {
  if (!currentProject) return;
  let target = currentFile;
  const project = projectData();
  if (!String(target || "").toLowerCase().endsWith(".tex")) {
    target = project?.main_tex || "";
  }
  if (!target || !target.toLowerCase().endsWith(".tex")) {
    setStatus("Select a .tex file or configure a Main LaTeX file before compiling.");
    renderBuildDiagnostics([
      {
        severity: "error",
        code: "no-main-tex",
        message: "No LaTeX main file is selected.",
        suggestion: "Open a .tex file or use Directory context to choose the Main LaTeX file.",
      },
    ], { title: "Build cannot start" });
    return;
  }

  if (dirty && currentFile === target) await saveCurrentFile();
  const compileButton = document.getElementById("compileBtn");
  compileButton.disabled = true;
  compileButton.textContent = force ? "Building anyway..." : "Preflight + Build...";

  try {
    setStatus(force ? "Compiling LaTeX despite preflight blockers..." : "Checking and compiling LaTeX...");
    hideRawCompilerLog();
    const data = await api(
      `/api/compile/${encodeURIComponent(currentProject)}/${encodeRelativePath(target)}`,
      { method: "POST", body: JSON.stringify({ force }) }
    );
    lastCompilerLog = data.log || "";
    const warnings = (data.diagnostics || []).filter(item => item.severity === "warning");
    if (warnings.length) {
      renderBuildDiagnostics(warnings, {
        title: "Build succeeded with warnings",
        summary: `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`,
      });
    } else {
      clearBuildDiagnostics();
    }
    pdfPreview.src = `${data.pdf_url}?t=${Date.now()}`;
    pdfPreview.style.display = "block";
    markdownPreview.style.display = "none";
    setStatus("LaTeX compilation succeeded.");
  } catch (error) {
    const payload = error.payload || {};
    lastCompilerLog = payload.log || "";
    const diagnostics = payload.diagnostics || payload.preflight?.diagnostics || [];
    const preflightBlocked = Boolean(payload.preflight && payload.preflight.ok === false && !force);
    renderBuildDiagnostics(diagnostics.length ? diagnostics : [{
      severity: "error",
      code: "build-failed",
      message: error.message,
      suggestion: "Open the raw build log for compiler details.",
    }], {
      title: preflightBlocked ? "Preflight found blockers" : "Build failed",
      summary: diagnosticSummary(diagnostics),
      allowForce: preflightBlocked,
    });
    pdfPreview.style.display = "none";
    markdownPreview.style.display = "none";
    setStatus(preflightBlocked ? "Fix the LaTeX preflight blockers or choose Build anyway." : `Compilation failed: ${error.message}`);
    console.error("LaTeX compilation failed:", payload || error);
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

document.getElementById("newNotebookBtn")
  ?.addEventListener("click", () =>
    createNotebook().catch(error => setStatus(error.message)));

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
  .addEventListener("click", () => compileCurrentFile(false));

document.getElementById("attachProjectBtn")
  ?.addEventListener("click", openAttachProjectDialog);
document.getElementById("projectContextBtn")
  ?.addEventListener("click", openProjectContextDialog);
document.getElementById("newLatexProjectBtn")
  ?.addEventListener("click", openLatexProjectDialog);
document.getElementById("saveProjectContextBtn")
  ?.addEventListener("click", () => saveProjectContext());
document.getElementById("attachProjectRunBtn")
  ?.addEventListener("click", () => attachExistingProject());
document.getElementById("latexProjectCreateBtn")
  ?.addEventListener("click", () => createLatexProjectFromDialog());
document.getElementById("useProjectRootBtn")
  ?.addEventListener("click", () => { documentsRootInput.value = ""; });
document.getElementById("useCurrentFolderBtn")
  ?.addEventListener("click", () => { documentsRootInput.value = dirname(currentFile); });
buildAnywayBtn?.addEventListener("click", () => compileCurrentFile(true));
toggleRawLogBtn?.addEventListener("click", toggleRawCompilerLog);

document.getElementById("goTopBtn")?.addEventListener("click", () => jumpToLine(1));
document.getElementById("goBottomBtn")?.addEventListener("click", () => {
  const lines = Math.max(1, editor.value.split("\n").length);
  jumpToLine(lines).catch(error => setStatus(error.message));
});
document.getElementById("goLineBtn")?.addEventListener("click", () => {
  const current = Number((cursorStatus.textContent.match(/Ln (\d+)/) || [])[1] || 1);
  const requested = prompt("Go to line:", String(current));
  if (!requested) return;
  const line = Number(requested);
  if (!Number.isInteger(line) || line < 1) {
    setStatus("Line number must be a positive integer.");
    return;
  }
  jumpToLine(line).catch(error => setStatus(error.message));
});
document.getElementById("prevBuildErrorBtn")?.addEventListener("click", () => {
  jumpToDiagnostic(activeBuildDiagnosticIndex - 1).catch(error => setStatus(error.message));
});
document.getElementById("nextBuildErrorBtn")?.addEventListener("click", () => {
  jumpToDiagnostic(activeBuildDiagnosticIndex + 1).catch(error => setStatus(error.message));
});

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



document.getElementById("notebookAddMarkdownBtn")?.addEventListener("click", () => {
  const index = notebookSelectedIndex >= 0 ? notebookSelectedIndex + 1 : notebookDocument?.cells.length || 0;
  insertNotebookCell("markdown", index);
});
document.getElementById("notebookAddCodeBtn")?.addEventListener("click", () => {
  const index = notebookSelectedIndex >= 0 ? notebookSelectedIndex + 1 : notebookDocument?.cells.length || 0;
  insertNotebookCell("code", index);
});
document.getElementById("notebookAddEndMarkdownBtn")?.addEventListener("click", () =>
  insertNotebookCell("markdown", notebookDocument?.cells.length || 0));
document.getElementById("notebookAddEndCodeBtn")?.addEventListener("click", () =>
  insertNotebookCell("code", notebookDocument?.cells.length || 0));
document.getElementById("notebookRunAllBtn")?.addEventListener("click", () =>
  runAllNotebookCells().catch(error => setStatus(`Run failed: ${error.message}`)));
document.getElementById("notebookRestartRunAllBtn")?.addEventListener("click", () =>
  restartAndRunAllNotebookCells().catch(error => setStatus(`Run failed: ${error.message}`)));
document.getElementById("notebookInterruptBtn")?.addEventListener("click", () =>
  interruptNotebookKernel().catch(error => setStatus(`Interrupt failed: ${error.message}`)));
document.getElementById("notebookRestartBtn")?.addEventListener("click", () =>
  restartNotebookKernel().catch(error => setStatus(`Restart failed: ${error.message}`)));
document.getElementById("notebookClearOutputsBtn")?.addEventListener("click", clearNotebookOutputs);
document.getElementById("notebookPresentBtn")?.addEventListener("click", () =>
  openNotebookPresentation().catch(error => setStatus(`Presentation failed: ${error.message}`)));
document.getElementById("notebookExportBtn")?.addEventListener("click", () =>
  openNotebookExportDialog().catch(error => setStatus(`Export setup failed: ${error.message}`)));
document.getElementById("notebookPresentationCloseBtn")?.addEventListener("click", () =>
  closeNotebookPresentation().catch(error => setStatus(error.message)));
document.getElementById("notebookPresentationPrevBtn")?.addEventListener("click", () => notebookRevealDeck?.prev());
document.getElementById("notebookPresentationNextBtn")?.addEventListener("click", () => notebookRevealDeck?.next());
document.getElementById("notebookPresentationOverviewBtn")?.addEventListener("click", () => notebookRevealDeck?.toggleOverview());
notebookExportFormat?.addEventListener("change", updateNotebookExportSelection);
notebookExportRunBtn?.addEventListener("click", () =>
  runNotebookExport().catch(error => {
    notebookExportResult.textContent = `Export failed: ${error.message}`;
    setStatus(`Export failed: ${error.message}`);
  }));

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
  if (!notebookWorkspace.hidden && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveCurrentNotebook().catch(error => setStatus(error.message));
    return;
  }
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
