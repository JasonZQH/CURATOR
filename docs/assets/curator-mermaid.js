/* Shared Mermaid setup for the Curator docs.
   Loads Mermaid from a pinned CDN and themes it to the brand palette so every
   diagram matches the logo's blue -> violet -> magenta signal system. Diagrams
   are authored as text in <div class="mermaid"> blocks; classDefs named live /
   verify / review / gate / pass / target / ledger encode Phase 0 vs V1 state. */

import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";

mermaid.initialize({
  startOnLoad: true,
  securityLevel: "loose",
  theme: "base",
  flowchart: { htmlLabels: true, curve: "basis", padding: 14, nodeSpacing: 46, rankSpacing: 58 },
  themeVariables: {
    fontFamily:
      'Inter, "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
    fontSize: "14px",
    background: "transparent",
    primaryColor: "#0e1a33",
    primaryBorderColor: "#3b8cff",
    primaryTextColor: "#eaf1ff",
    secondaryColor: "#170f2e",
    tertiaryColor: "#0b1022",
    lineColor: "#8b7ad0",
    textColor: "#c3cde6",
    nodeTextColor: "#eaf1ff",
    titleColor: "#eef2ff",
    edgeLabelBackground: "#0b1022",
    clusterBkg: "rgba(59,140,255,0.05)",
    clusterBorder: "#22304f",
    noteBkgColor: "#101733",
    noteBorderColor: "#22304f",
    noteTextColor: "#c3cde6",
  },
});
