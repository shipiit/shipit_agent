// Render a useful Markdown subset through DOM nodes. Raw HTML stays literal text.
function inline(parent, text) {
  const pattern =
    /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
  let offset = 0,
    match;
  while ((match = pattern.exec(text))) {
    parent.append(document.createTextNode(text.slice(offset, match.index)));
    const node = document.createElement(
      match[2] ? "strong" : match[3] ? "code" : "a",
    );
    node.textContent = match[2] || match[3] || match[4];
    if (match[5]) {
      node.href = match[5];
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    }
    parent.append(node);
    offset = pattern.lastIndex;
  }
  parent.append(document.createTextNode(text.slice(offset)));
}
export function renderMarkdown(container, text) {
  container.replaceChildren();
  const lines = String(text).split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const pre = document.createElement("pre"),
        code = document.createElement("code");
      const parts = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```"))
        parts.push(lines[i++]);
      code.textContent = parts.join("\n");
      pre.append(code);
      container.append(pre);
      i++;
      continue;
    }
    if (/\|/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
      const wrap = document.createElement("div");
      wrap.className = "table-scroll";
      const table = document.createElement("table");
      const add = (row, header) => {
        const tr = document.createElement("tr");
        for (const value of row
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")) {
          const cell = document.createElement(header ? "th" : "td");
          inline(cell, value.trim());
          tr.append(cell);
        }
        table.append(tr);
      };
      add(line, true);
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim())
        add(lines[i++], false);
      wrap.append(table);
      container.append(wrap);
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    const bullet = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
    const node = document.createElement(
      heading ? "h" + Math.min(heading[1].length + 1, 5) : "p",
    );
    if (bullet) node.className = "bullet";
    inline(node, heading ? heading[2] : bullet ? bullet[1] : line);
    container.append(node);
    i++;
  }
}
