/* No trackers, framework, CDN, or patient data. Progressive enhancement only. */
(() => {
  "use strict";
  if (location.hash.startsWith("#/")) {
    location.replace(`guide.html${location.hash}`);
    return;
  }
  const translated = [...document.querySelectorAll("[data-en]")];
  for (const element of translated) element.dataset.zh = element.textContent;
  let english = new URLSearchParams(location.search).get("lang") === "en";
  const language = document.querySelector("#language");
  const rows = [...document.querySelectorAll("[data-category]")];
  const filters = [...document.querySelectorAll("[data-filter]")];
  const count = document.querySelector("#method-count");
  function updateCount() {
    const n = rows.filter((row) => !row.hidden).length;
    count.textContent = english ? `${n} methods shown` : `顯示 ${n} 個方法`;
  }
  function applyLanguage() {
    for (const element of translated)
      element.textContent = element.dataset[english ? "en" : "zh"];
    document.documentElement.lang = english ? "en" : "zh-Hant";
    document.title = english
      ? "Research Data Explorer — From research ideas to credible evidence"
      : "Research Data Explorer — 從研究想法到可信證據";
    language.textContent = english ? "繁中" : "EN";
    language.setAttribute(
      "aria-label",
      english ? "切換為繁體中文" : "Switch to English",
    );
    const diagram = document.querySelector("#architecture-image");
    diagram.src = `assets/architecture${english ? "" : "-zh"}.svg`;
    diagram.alt = english
      ? "Researchers and AI agents use MCP tools, analysis contracts and evidence records to produce reproducible research reports."
      : "研究者與 AI agent 透過 MCP 工具、分析契約與證據紀錄，共同形成可重現研究報告。";
    for (const link of document.querySelectorAll("[data-guide]"))
      link.href = `guide.html#/${link.dataset.guide === "installation" ? "setup" : link.dataset.guide}-${english ? "en" : "zh"}`;
    document.querySelector("#copy-status").textContent = "";
    updateCount();
  }
  language.addEventListener("click", () => {
    english = !english;
    const url = new URL(location.href);
    if (english) url.searchParams.set("lang", "en");
    else url.searchParams.delete("lang");
    history.replaceState(null, "", url);
    applyLanguage();
  });
  for (const button of filters)
    button.addEventListener("click", () => {
      for (const item of filters)
        item.setAttribute("aria-pressed", String(item === button));
      for (const row of rows)
        row.hidden =
          button.dataset.filter !== "all" &&
          row.dataset.category !== button.dataset.filter;
      updateCount();
    });
  const menu = document.querySelector("#menu-toggle"),
    nav = document.querySelector("#main-nav");
  function closeMenu() {
    menu.setAttribute("aria-expanded", "false");
    nav.classList.remove("open");
  }
  menu.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    menu.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("open", open);
  });
  nav.addEventListener("click", (event) => {
    if (event.target.closest("a")) closeMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
  document
    .querySelector("#copy-command")
    .addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(
          document.querySelector("#install-command").textContent,
        );
        document.querySelector("#copy-status").textContent = english
          ? "Commands copied."
          : "已複製指令。";
      } catch {
        document.querySelector("#copy-status").textContent = english
          ? "Select and copy the commands above."
          : "請選取上方指令並複製。";
      }
    });
  applyLanguage();
})();
