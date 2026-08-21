(function () {
  "use strict";
  if (window.hljs) return;

  const escapeHtml = value => String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
  const noop = () => {};

  window.hljs = {
    highlight(code) { return { value: escapeHtml(code) }; },
    highlightAuto(code) { return { value: escapeHtml(code) }; },
    highlightElement: noop,
    highlightBlock: noop,
    initHighlighting: noop,
    initHighlightingOnLoad: noop,
    configure: noop,
    registerLanguage: noop,
    registerAliases: noop,
    getLanguage() { return null; },
    listLanguages() { return []; },
  };
}());
