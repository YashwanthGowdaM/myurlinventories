(() => {
  "use strict";

  const filter = document.getElementById("filter");
  if (filter) {
    const rows = Array.from(document.querySelectorAll("tbody tr[data-search]"));
    const count = document.getElementById("count");
    const none = document.getElementById("no-match");
    const total = rows.length;
    const plural = (n) => `${n} link${n === 1 ? "" : "s"}`;

    const apply = () => {
      const terms = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
      let shown = 0;
      for (const row of rows) {
        const hay = row.dataset.search;
        const match = terms.every((t) => hay.includes(t));
        row.hidden = !match;
        if (match) shown += 1;
      }
      count.textContent = terms.length ? `${shown} of ${plural(total)}` : plural(total);
      if (none) none.hidden = shown !== 0 || total === 0;
    };

    filter.addEventListener("input", apply);
    document.addEventListener("keydown", (e) => {
      const tag = (e.target.tagName || "").toLowerCase();
      if (e.key === "/" && !["input", "textarea"].includes(tag) && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        filter.focus();
      }
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });
})();
