"use strict";

(() => {
  const worker = new Worker(new URL("./worker.js", document.currentScript.src));
  const requests = new Map();
  let nextId = 0;
  let failed = false;

  worker.addEventListener("message", ({ data }) => {
    const request = requests.get(data.id);
    if (!request) return;
    requests.delete(data.id);
    if (data.error) request.reject(new Error(data.error));
    else request.resolve(data.result);
  });
  worker.addEventListener("error", () => {
    failed = true;
    for (const { reject } of requests.values()) reject(new Error("O painel não abriu. Recarregue a página."));
    requests.clear();
  });

  window.merchHostedApi = (path, data) => new Promise((resolve, reject) => {
    if (failed) {
      reject(new Error("O painel não abriu. Recarregue a página."));
      return;
    }
    const id = ++nextId;
    requests.set(id, { resolve, reject });
    worker.postMessage({ id, path, body: data === undefined ? null : JSON.stringify(data) });
  });

  document.querySelector("#export-trades").addEventListener("click", async (event) => {
    event.preventDefault();
    try {
      const csv = await window.merchHostedApi("/api/exports/trades.csv");
      const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
      const download = document.createElement("a");
      download.href = url;
      download.download = "merch-rs3-historico.csv";
      download.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      notify(error.message);
    }
  });
})();
