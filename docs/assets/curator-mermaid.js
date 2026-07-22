/* Shared Mermaid setup for the Curator docs.
   Loaded as a CLASSIC script (not an ES module) right after the vendored
   assets/mermaid.min.js, so the diagrams render when the file is opened
   directly (file://) and offline — module scripts are blocked over file://.
   Themed to the brand palette; classDefs named live / verify / review / gate /
   pass / target / ledger encode Phase 0 vs V1 state. */

(function () {
  "use strict";
  if (typeof mermaid === "undefined") return;

  mermaid.initialize({
    startOnLoad: false,
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

  function render() {
    try {
      mermaid.run({ querySelector: ".mermaid" });
    } catch (e) {
      /* leave the raw diagram source visible as a fallback */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
