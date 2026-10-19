/* Small, safe Markdown renderer for AI answers (all HTML is escaped first). */
(function () {
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function inline(text) {
    let s = esc(text); const codes = [];
    s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>")
         .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>").replace(/(^|\s)_([^_\s][^_]*?)_(?=\s|$|[.,])/g, "$1<em>$2</em>")
         .replace(/~~([^~]+)~~/g, "<del>$1</del>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
  }
  const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
  const isSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  function render(md) {
    const lines = String(md || "").replace(/\r\n?/g, "\n").replace(/[\u202f\u00a0]/g, " ").split("\n");
    const out = []; let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*```/.test(line)) { const b = []; i++; while (i < lines.length && !/^\s*```/.test(lines[i])) b.push(lines[i++]); i++; out.push(`<pre><code>${esc(b.join("\n"))}</code></pre>`); continue; }
      if (isRow(line) && i + 1 < lines.length && isSep(lines[i + 1])) {
        const head = cells(line); i += 2; const rows = [];
        while (i < lines.length && isRow(lines[i])) rows.push(cells(lines[i++]));
        out.push(`<div class="md-table-wrap"><table class="md-table"><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>` +
          rows.map((r) => `<tr>${head.map((_, k) => `<td>${inline(r[k] ?? "")}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>");
        continue;
      }
      const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
      if (h) { const l = Math.min(h[1].length + 1, 6); out.push(`<h${l}>${inline(h[2])}</h${l}>`); i++; continue; }
      if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
      if (/^\s*>\s?/.test(line)) { const b = []; while (i < lines.length && /^\s*>\s?/.test(lines[i])) b.push(lines[i++].replace(/^\s*>\s?/, "")); out.push(`<blockquote>${inline(b.join(" "))}</blockquote>`); continue; }
      if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line), re = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/, items = [];
        while (i < lines.length && re.test(lines[i])) {
          const item = lines[i++].replace(re, ""), sub = [];
          while (i < lines.length && /^\s{2,}[-*+]\s+/.test(lines[i])) sub.push(lines[i++].replace(/^\s+[-*+]\s+/, ""));
          items.push(inline(item) + (sub.length ? `<ul>${sub.map((s) => `<li>${inline(s)}</li>`).join("")}</ul>` : ""));
        }
        const tag = ordered ? "ol" : "ul"; out.push(`<${tag}>${items.map((x) => `<li>${x}</li>`).join("")}</${tag}>`); continue;
      }
      if (!line.trim()) { i++; continue; }
      const p = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|[-*+]\s|\d+[.)]\s|>)/.test(lines[i]) && !(isRow(lines[i]) && i + 1 < lines.length && isSep(lines[i + 1]))) p.push(lines[i++]);
      if (p.length) out.push(`<p>${p.map(inline).join("<br>")}</p>`); else { out.push(`<p>${inline(lines[i])}</p>`); i++; }
    }
    return out.join("");
  }
  window.renderMarkdown = render;
})();
