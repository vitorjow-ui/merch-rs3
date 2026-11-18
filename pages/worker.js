"use strict";

const runtimeURL = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const ledgerPath = "/tmp/merch.sqlite3";

// Market uses a synchronous transport inside this dedicated worker only.
self.merchRequest = (url) => {
  const request = new XMLHttpRequest();
  request.open("GET", url, false);
  request.timeout = 8000;
  request.send();
  if (request.status !== 200) throw new Error(`HTTP ${request.status}`);
  return request.responseText;
};

function openLedgerStore() {
  return new Promise((resolve, reject) => {
    const scope = new URL("./", self.location.href).pathname;
    const request = indexedDB.open(`merch-rs3:${scope}`, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("ledger");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Armazenamento do painel bloqueado."));
  });
}

async function initialize() {
  importScripts(`${runtimeURL}pyodide.js`);
  const runtime = await loadPyodide({ indexURL: runtimeURL });
  await runtime.loadPackage("sqlite3");
  const modules = ["application", "browser", "ledger", "market", "opportunities", "recipes"];
  await Promise.all(modules.map(async (name) => {
    const response = await fetch(`./engine/${name}.py`);
    if (!response.ok) throw new Error(`Engine module ${name}: ${response.status}`);
    runtime.FS.writeFile(`${name}.py`, await response.text());
  }));
  const route = runtime.runPython("from browser import route\nroute");
  const emptyLedger = runtime.FS.readFile(ledgerPath);
  const database = await openLedgerStore();
  return { runtime, route, emptyLedger, database };
}

function transaction(database, mode, callback) {
  return new Promise((resolve, reject) => {
    const txn = database.transaction("ledger", mode);
    const store = txn.objectStore("ledger");
    const read = store.get("sqlite");
    let result;
    txn.oncomplete = () => resolve(result);
    txn.onabort = () => reject(txn.error ?? new Error("Armazenamento interrompido."));
    read.onsuccess = () => {
      try {
        result = callback(read.result, store);
      } catch (error) {
        reject(error);
        txn.abort();
      }
    };
  });
}

async function handle({ path, body }, engine) {
  const { database, runtime, route, emptyLedger } = engine;
  const dispatch = (file) => {
    runtime.FS.writeFile(ledgerPath, file ?? emptyLedger);
    return JSON.parse(route(path, body));
  };
  const changesLedger = body !== null && path !== "/api/calculate" && path !== "/api/craft-projection";
  if (changesLedger) {
    // One read-write transaction serializes edits from multiple open tabs.
    return transaction(database, "readwrite", (file, store) => {
      const result = dispatch(file);
      if (!result.error) store.put(runtime.FS.readFile(ledgerPath), "sqlite");
      return result;
    });
  }
  const file = await transaction(database, "readonly", (saved) => saved);
  return dispatch(file);
}

let startup;
let queue = Promise.resolve();
self.addEventListener("message", ({ data }) => {
  queue = queue.then(async () => {
    try {
      startup ??= initialize();
      const engine = await startup.catch((error) => {
        startup = undefined;
        throw error;
      });
      self.postMessage({ id: data.id, ...await handle(data, engine) });
    } catch (error) {
      console.error(error);
      self.postMessage({ id: data.id, error: "Falha ao abrir ou salvar o painel neste navegador." });
    }
  });
});
