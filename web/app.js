"use strict";

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const numberFormat = new Intl.NumberFormat("pt-BR");
const percentFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const timestampFormat = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const timeFormat = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const viewTitles = {
  visao: ["Oportunidades no GE", "Veja quanto cada operação pode render depois da tarifa."],
  mercado: ["Flip", "Compare o resultado de comprar e revender o mesmo item."],
  crafting: ["Crafting", "Compare o custo dos insumos com o valor líquido da peça pronta."],
  ofertas: ["Ofertas e posições", "Acompanhe seus slots, o saldo a recolher e o estoque disponível."],
  historico: ["Histórico de operações", "Consulte os preços executados e o resultado de cada venda."],
};
const dialogs = Object.fromEntries($$("dialog").map((dialog) => [dialog.id, dialog]));
let state;
let items = [];
let mode = "eligible";
let page = 1;
let marketRequest = 0;
let marketTimer;
let calcRequest = 0;
let calcTimer;
let detailItem;
let detailRevision = 0;
let offerItem;
let fillOffer;
let chartPoints = [];
let noticeTimer;

function escape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function gp(value) {
  if (value === null || value === undefined) return "—";
  const exact = String(value);
  return /^-?\d+$/.test(exact) ? numberFormat.format(BigInt(exact)) : numberFormat.format(Number(value));
}

const gpUnits = [[1_000_000_000n, "B"], [1_000_000n, "M"], [1_000n, "K"]];

function compactGp(value) {
  if (value == null || !/^-?\d+$/.test(String(value))) return gp(value);
  const amount = BigInt(value);
  const magnitude = amount < 0n ? -amount : amount;
  const index = gpUnits.findIndex(([unit]) => magnitude >= unit);
  if (index < 0) return gp(value);
  let [scale, suffix] = gpUnits[index];
  let rounded = (magnitude * 100n + scale / 2n) / scale;
  if (rounded >= 100_000n && index > 0) {
    [scale, suffix] = gpUnits[index - 1];
    rounded = (magnitude * 100n + scale / 2n) / scale;
  }
  const fraction = String(rounded % 100n).padStart(2, "0").replace(/0+$/, "");
  return `${amount < 0n ? "-" : ""}${gp(rounded / 100n)}${fraction ? "," + fraction : ""}${suffix}`;
}

function money(value, { plus = false } = {}) {
  if (value == null) return "—";
  const prefix = plus && BigInt(value) > 0n ? "+" : "";
  return `<span title="${escape(gp(value))}">${prefix}${escape(compactGp(value))}</span>`;
}

function parseGp(value) {
  const text = String(value).trim();
  if (/^(?:\d+|\d{1,3}(?:\.\d{3})+)$/.test(text)) return BigInt(text.replaceAll(".", ""));
  const match = /^(\d+|\d{1,3}(?:\.\d{3})+)(?:,(\d+))?\s*([BMK])$/i.exec(text);
  if (!match) throw new Error("Informe um valor como 1,5B, 300M, 50K ou um número inteiro.");
  const scale = gpUnits.find(([, suffix]) => suffix === match[3].toUpperCase())[0];
  const fraction = match[2] || "";
  const divisor = 10n ** BigInt(fraction.length);
  const total = BigInt(match[1].replaceAll(".", "") + fraction) * scale;
  if (total % divisor) throw new Error("O valor precisa corresponder a um número inteiro de moedas.");
  return total / divisor;
}

function displayGpInput(value) {
  const compact = compactGp(value);
  return String(parseGp(compact)) === String(value) ? compact : gp(value);
}

async function copyPrice(input, button) {
  if (!/^\d+$/.test(input.value)) {
    input.focus();
    return;
  }
  const label = button.textContent;
  try {
    await navigator.clipboard.writeText(input.value);
    button.textContent = "Copiado";
  } catch {
    input.select();
    button.textContent = "Selecionado";
  }
  setTimeout(() => { button.textContent = label; }, 1700);
}

function percent(value) {
  return value == null ? "—" : `${percentFormat.format(value)}%`;
}

function dateTime(seconds) {
  return seconds ? timestampFormat.format(new Date(seconds * 1000)) : "Sem execução";
}

function age(seconds) {
  if (!seconds) return "—";
  const minutes = Math.max(0, Math.floor((Date.now() / 1000 - seconds) / 60));
  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes} min atrás`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} h atrás`;
  return `${Math.floor(minutes / 1440)} d atrás`;
}

function signedClass(value) {
  return Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "";
}

async function api(path, data) {
  if (window.merchHostedApi) return window.merchHostedApi(path, data);
  const options = data === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  };
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Falha no painel local.");
  return result;
}

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 6000);
}

function view() {
  const hash = location.hash.slice(1);
  return Object.hasOwn(viewTitles, hash) ? hash : "visao";
}

function navigate() {
  const selected = view();
  $("#page-title").textContent = viewTitles[selected][0];
  $("#page-description").textContent = viewTitles[selected][1];
  for (const link of $$("[data-view]")) {
    const current = link.dataset.view === selected;
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
    const panel = document.getElementById(link.dataset.view);
    if (panel) panel.hidden = !current;
  }
  $("#account-metrics").hidden = !["ofertas", "historico"].includes(selected);
  if (selected === "mercado" && $("#legacy-details").open) loadMarket();
  showDecisionView(selected);
}

function renderState() {
  const { settings } = state;
  for (const key of ["available", "reserved", "stock", "profit"]) {
    document.getElementById(key).innerHTML = money(state[key]);
  }
  $("#profit").className = signedClass(state.profit);
  $("#capital-label").innerHTML = `Capital inicial · ${money(settings.capital)}`;
  $("#due-label").innerHTML = `${money(state.due)} a recolher`;
  $("#stock-label").textContent = `${gp(state.positions.reduce((total, pos) => total + pos.qty, 0))} un. em estoque`;
  $("#slot-label").textContent = `${state.slots} / ${settings.profile === "members" ? 8 : 3} slots`;
  renderOffers();
  renderHistory();
}

function table(headers, rows, emptyText) {
  if (!rows.length) return `<div class="empty">${emptyText}</div>`;
  const headings = headers.map((heading) => `<th scope="col">${heading}</th>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${headings}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

function renderOffers() {
  const labels = { open: "Aberta", completed: "Concluída", cancelled: "Cancelada" };
  const offers = state.offers.filter((offer) => offer.status === "open" || offer.items_due || offer.cash_due !== "0");
  $("#offers-list").innerHTML = table(
    ["Item", "Tipo", "Preço", "Executado", "Status", "A recolher", "Ações"],
    offers.map((offer) => {
      const pending = [];
      if (offer.items_due) pending.push(`${gp(offer.items_due)} un.`);
      if (offer.cash_due !== "0") pending.push(money(offer.cash_due));
      const collect = pending.length ? `<button class="button secondary small" data-collect="${offer.id}">Registrar coleta</button>` : "";
      const activeActions = offer.status === "open" ? `
        <button class="button secondary small" data-fill="${offer.id}">Registrar execução</button>
        <button class="button quiet small" data-cancel="${offer.id}">Registrar cancelamento</button>` : "";
      return `<tr><td>${escape(offer.name)} <span class="offer-id">#${offer.id}</span></td>
        <td>${offer.side === "buy" ? "Compra" : "Venda"}</td><td>${money(offer.target)}</td>
        <td>${gp(offer.qty - offer.remaining)} / ${gp(offer.qty)}</td>
        <td><span class="signal">${labels[offer.status]}</span></td>
        <td>${pending.join(" · ") || "—"}</td><td><div class="table-actions">${activeActions}${collect}</div></td></tr>`;
    }),
    "Nenhuma oferta ocupando slots. Use “Registrar oferta” após criar uma no GE.",
  );
  $("#positions-list").innerHTML = table(
    ["Item", "Quantidade", "Livre para venda", "A recolher", "Custo", "Ações"],
    state.positions.map((pos, index) => `<tr>
      <td>${escape(pos.name)}</td><td>${gp(pos.qty)}</td><td>${gp(pos.available)}</td>
      <td>${gp(pos.pending)}</td><td>${money(pos.cost)}</td>
      <td>${pos.available > 0 ? `<button class="button secondary small" data-sell="${index}">Registrar venda</button>` : "—"}</td>
      </tr>`),
    "Seu estoque aparece conforme você registra compras executadas.",
  );
}

function renderHistory() {
  $("#trade-history").innerHTML = table(
    ["Item", "Data", "Tipo", "Quantidade", "Preço", "Tarifa", "Lucro", "Tempo"],
    state.fills.map((fill) => {
      const profit = fill.side === "sell" ?
        BigInt(fill.price) * BigInt(fill.qty) - BigInt(fill.cost) - BigInt(fill.fee) : null;
      const minutes = Math.floor(Math.max(0, fill.created - fill.opened) / 60);
      const duration = minutes < 1 ? "< 1 min" : minutes < 60 ?
        `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
      return `<tr><td>${escape(fill.name)}</td><td>${dateTime(fill.created)}</td>
        <td>${fill.side === "buy" ? "Compra" : "Venda"}</td><td>${gp(fill.qty)}</td>
        <td>${money(fill.price)}</td><td>${money(fill.fee)}</td>
        <td class="${signedClass(profit)}">${money(profit)}</td><td>${escape(duration)}</td></tr>`;
    }),
    "Ainda não há execuções registradas.",
  );
}

function setMode(selected) {
  mode = selected;
  for (const button of $$("[data-mode]")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
}

async function loadMarket() {
  const revision = ++marketRequest;
  const params = new URLSearchParams({
    q: $("#search").value, membership: $("#membership").value,
    sort: $("#sort").value, mode, page: String(page),
  });
  try {
    const result = await api(`/api/market?${params}`);
    if (revision !== marketRequest) return;
    renderMarket(result);
  } catch (error) {
    if (revision !== marketRequest) return;
    renderMarket({ market: { status: "offline", lastSync: 0 }, items: [], count: 0, page: 1 });
    console.error(error);
  }
}

function renderMarket(result) {
  const feed = result.market;
  const status = $("#feed-status");
  const labels = { online: "Feed conectado", cached: "Dados em cache", offline: "Feed indisponível" };
  status.className = `status ${feed.status}`;
  status.innerHTML = `<span class="dot"></span> ${labels[feed.status]}`;
  status.title = feed.lastSync ? `Última consulta: ${dateTime(feed.lastSync)}` : "RuneScape Wiki";
  items = result.items;
  const empty = $("#market-empty");
  empty.hidden = items.length > 0;
  empty.textContent = feed.status !== "online" ?
    "O feed não está disponível para novos sinais. Você ainda pode calcular e registrar flips." :
    mode === "watch" ? "Nenhum favorito encontrado nesta busca." :
      mode === "eligible" ? "Nenhum item passou pelos filtros agora. Consulte “Todos os itens” para ver as referências." :
        "Nenhum item encontrado. Tente outro nome ou ID.";
  $("#market-table-wrap").hidden = !items.length;
  const watched = new Set(state?.watchlist || []);
  $("#market-rows").innerHTML = items.map((item) => {
    const indicator = !item.eligible ? ["watch", "Observar"] : item.quantity ? ["good", "Candidato"] : ["", "Sem quantidade"];
    const star = watched.has(item.id) ? " · Favorito" : "";
    return `<tr>
      <td><button class="item-button" data-detail="${item.id}">${escape(item.name)}</button>
        <small>${item.members ? "P2P" : "F2P"} · ID ${item.id}${star}</small></td>
      <td>${money(item.buy)}<small>${age(item.lowTime)}</small></td>
      <td>${money(item.sell)}<small>${age(item.highTime)}</small></td>
      <td>${item.quantity ? gp(item.quantity) : "—"}</td>
      <td class="${signedClass(item.profit)}">${money(item.profit)}</td>
      <td class="${signedClass(item.roi)}">${percent(item.roi)}</td>
      <td><span title="${escape(item.reason)}" class="signal ${indicator[0]}">${indicator[1]}</span></td>
      <td><button class="button secondary small row-details" data-detail="${item.id}" aria-label="Ver ${escape(item.name)}">›</button></td>
      </tr>`;
  }).join("");
  const first = (result.page - 1) * 30 + 1;
  $("#market-count").textContent = items.length ?
    `${gp(first)}–${gp(first + items.length - 1)} de ${gp(result.count)} · RuneScape Wiki` :
    "RuneScape Wiki · mercado principal";
  $("#prev").disabled = result.page <= 1;
  $("#next").disabled = result.page * 30 >= result.count;
}

function formError(form, message) {
  const error = $(".form-error", form);
  error.textContent = message;
  error.hidden = !message;
}

function formData(form) {
  return Object.fromEntries(new FormData(form));
}

function showSettings() {
  const form = $("#settings-form");
  if (!state) return;
  for (const [key, value] of Object.entries(state.settings)) {
    form.elements.namedItem(key).value = key === "capital" ? displayGpInput(value) : value;
  }
  formError(form, "");
  dialogs["settings-dialog"].showModal();
}

function offerSide() {
  const form = $("#offer-form");
  const sell = form.elements.side.value === "sell";
  $("#buy-field").hidden = sell;
  $("#sell-field").hidden = !sell;
  form.elements.name.required = !sell;
  form.elements.itemKey.required = sell;
  const pos = state?.positions.find((item) => item.key === form.elements.itemKey.value);
  $("#offer-hint").textContent = sell ?
    pos ? `${gp(pos.available)} un. coletadas e livres para venda.` : "Registre e recolha uma compra para vender pelo painel." :
    `Caixa livre no painel de ${compactGp(state?.available)}. Confirme seu limite de compra no GE.`;
}

function showOffer(preset = {}) {
  if (!state) return;
  const form = $("#offer-form");
  form.reset();
  offerItem = preset.item || null;
  form.elements.side.value = preset.side || "buy";
  form.elements.name.value = offerItem?.name || "";
  form.elements.name.readOnly = Boolean(offerItem);
  form.elements.itemKey.replaceChildren(new Option("Selecione um item", ""));
  for (const pos of state.positions.filter((position) => position.available > 0)) {
    form.elements.itemKey.add(new Option(pos.name, pos.key));
  }
  if (preset.key) form.elements.itemKey.value = preset.key;
  form.elements.qty.value = preset.qty || "";
  form.elements.price.value = preset.price || "";
  offerSide();
  formError(form, "");
  dialogs["offer-dialog"].showModal();
}

function showFill(id) {
  fillOffer = state.offers.find((offer) => offer.id === id);
  if (!fillOffer) return;
  const form = $("#fill-form");
  form.reset();
  form.elements.qty.value = fillOffer.remaining;
  form.elements.price.value = fillOffer.target;
  $("#fee-field").hidden = fillOffer.side === "buy";
  $("#fill-description").textContent =
    `${fillOffer.name} · ${gp(fillOffer.remaining)} un. restantes na oferta #${fillOffer.id}`;
  formError(form, "");
  dialogs["fill-dialog"].showModal();
}

function quote(label, price, description, id = "") {
  return `<div ${id ? `id="${id}"` : ""}><small>${label}</small><strong>${price}</strong><small>${description}</small></div>`;
}

async function showDetail(item = null) {
  detailItem = item;
  chartPoints = [];
  const revision = ++detailRevision;
  const form = $("#calculator-form");
  form.reset();
  $("#detail-title").textContent = item ? item.name : "Calcular um flip";
  $("#detail-kicker").textContent = item ? "Planejamento do flip" : "Calculadora";
  $("#detail-reason").textContent = item ? item.reason : "Informe seus preços e a quantidade para projetar o resultado.";
  $("#market-detail").hidden = !item;
  $("#watch-item").hidden = !item;
  $("#plan-offer").hidden = !item || Boolean(item.simulation);
  $("#exempt-field").hidden = Boolean(item);
  formError(form, "");
  $("#calculation").replaceChildren();
  if (item) {
    form.elements.buy.value = item.buy || "";
    form.elements.sell.value = item.sell || "";
    form.elements.qty.value = item.quantity || 1;
    form.elements.exempt.checked = /^(runescape )?bond$/i.test(item.name);
    const limit = item.limit ? `${gp(item.limitLeft)} / ${gp(item.limit)} un. estimadas` : "Buy limit indisponível";
    const reset = item.limitReset ? ` · Renova às ${timeFormat.format(new Date(item.limitReset * 1000))}` : "";
    $("#quote-labels").innerHTML =
      quote("Venda instantânea", money(item.low), escape(dateTime(item.lowTime))) +
      quote("Compra instantânea", money(item.high), escape(dateTime(item.highTime))) +
      quote("Preço-guia do GE", "—", "Consultando", "guide-quote") +
      quote("Buy limit", limit, `Confirme no GE${reset}`) +
      quote(`Vol. de compra (${item.volumeWindow || "1 h"})`, gp(item.hourHighVolume), "Unidades de compra instantânea") +
      quote(`Vol. de venda (${item.volumeWindow || "1 h"})`, gp(item.hourLowVolume), "Unidades de venda instantânea");
    $("#chart").hidden = true;
    $("#chart-status").hidden = false;
    $("#chart-status").textContent = "Carregando histórico…";
    renderWatch();
  }
  dialogs["detail-dialog"].showModal();
  calculate();
  if (!item) return;
  const readHistory = async () => {
    try {
      const data = await api(`/api/history/${item.id}`);
      if (revision !== detailRevision || !dialogs["detail-dialog"].open) return;
      chartPoints = data.points;
      $("#chart-status").textContent = data.cached ?
        "Histórico indisponível ou em cache." : "Sem execuções no período.";
      drawChart();
    } catch {
      if (revision === detailRevision) $("#chart-status").textContent = "Histórico indisponível.";
    }
  };
  const readGuide = async () => {
    try {
      const guide = await api(`/api/guide/${item.id}`);
      if (revision !== detailRevision || !dialogs["detail-dialog"].open) return;
      const element = $("#guide-quote");
      $("strong", element).innerHTML = money(guide.price);
      $$("small", element)[1].textContent = guide.time ?
        timestampFormat.format(new Date(guide.time)) : "Indisponível";
    } catch {
      if (revision === detailRevision) $$("small", $("#guide-quote"))[1].textContent = "Indisponível";
    }
  };
  await Promise.allSettled([readHistory(), readGuide()]);
}

function renderWatch() {
  const watched = state?.watchlist.includes(detailItem?.id);
  const button = $("#watch-item");
  button.textContent = watched ? "Remover dos favoritos" : "Favoritar";
  button.setAttribute("aria-pressed", String(Boolean(watched)));
}

function drawChart() {
  const canvas = $("#chart");
  if (!dialogs["detail-dialog"].open || !chartPoints.length) return;
  const values = chartPoints.flatMap((point) => [point.high, point.low]).filter(Number.isFinite);
  if (!values.length) return;
  canvas.hidden = false;
  const width = canvas.clientWidth;
  const height = 154;
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.scale(scale, scale);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min;
  const start = chartPoints[0].time;
  const end = chartPoints.at(-1).time;
  const left = Math.min(86, width / 3);
  const top = 13;
  const bottom = height - 25;
  context.font = "10px Segoe UI, sans-serif";
  context.fillStyle = "#a9afc1";
  context.strokeStyle = "#2b3040";
  for (let index = 0; index < 4; index++) {
    const y = top + index / 3 * (bottom - top);
    if (spread || index === 2) {
      context.fillText(compactGp(Math.round(max - index / 3 * spread)), 2, y + 3);
    }
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(width - 8, y);
    context.stroke();
  }
  context.fillText(timeFormat.format(new Date(start * 1000)), left, height - 5);
  context.fillText(timeFormat.format(new Date(end * 1000)), Math.max(left + 40, width - 38), height - 5);
  for (const [key, color] of [["high", "#83d6bd"], ["low", "#eac47a"]]) {
    context.fillStyle = color;
    context.strokeStyle = color;
    context.lineWidth = 1.5;
    let last = null;
    for (const point of chartPoints) {
      if (!Number.isFinite(point[key])) {
        last = null;
        continue;
      }
      const x = left + (end === start ? 0.5 : (point.time - start) / (end - start)) * (width - left - 8);
      const y = bottom - (spread ? (point[key] - min) / spread : 0.5) * (bottom - top);
      context.beginPath();
      if (last) {
        context.moveTo(last.x, last.y);
        context.lineTo(x, y);
        context.stroke();
      } else {
        context.arc(x, y, 2, 0, 2 * Math.PI);
        context.fill();
      }
      last = { x, y };
    }
  }
  if ($("#chart-status").textContent === "Sem execuções no período.") $("#chart-status").hidden = true;
}

async function calculate() {
  const form = $("#calculator-form");
  const revision = ++calcRequest;
  const data = formData(form);
  const results = $("#calculation");
  formError(form, "");
  if (!/^[0-9]+$/.test(data.buy) || !/^[0-9]+$/.test(data.sell) || !/^[0-9]+$/.test(data.qty)) {
    results.replaceChildren();
    $("#plan-offer").disabled = true;
    return;
  }
  try {
    const calculation = await api("/api/calculate", {
      ...data, exempt: form.elements.exempt.checked, instant: detailItem?.low,
    });
    if (revision !== calcRequest) return;
    const metrics = [
      ["Custo total", money(calculation.cost)],
      ["Lucro líquido", money(calculation.profit), signedClass(calculation.profit)],
      ["Retorno", percent(calculation.roi), signedClass(calculation.roi)],
      ["Tarifa por unidade", money(calculation.fee)],
      ["Preço de equilíbrio", money(calculation.breakEven)],
      ["Lucro se a saída cair 2%", money(calculation.stressProfit), signedClass(calculation.stressProfit)],
    ];
    if (calculation.instantProfit != null) {
      metrics.push(["Resultado à última saída instantânea", money(calculation.instantProfit), signedClass(calculation.instantProfit)]);
    }
    results.innerHTML = metrics.map(([label, value, color = ""]) =>
      `<div><small>${label}</small><strong class="${color}">${value}</strong></div>`).join("");
    $("#plan-offer").disabled = !state || BigInt(calculation.cost) > BigInt(state.available);
  } catch (error) {
    if (revision !== calcRequest) return;
    results.replaceChildren();
    $("#plan-offer").disabled = true;
    formError(form, error.message);
  }
}

function submit(formId, task) {
  const form = document.getElementById(formId);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitButton = $("button[type=submit]", form);
    if (submitButton.disabled) return;
    submitButton.disabled = true;
    formError(form, "");
    try {
      await task(form, formData(form));
      form.closest("dialog").close();
      renderState();
      if (view() === "mercado" && $("#legacy-details").open) loadMarket();
      if (isDecisionView(view())) loadDecision();
    } catch (error) {
      formError(form, error.message);
    } finally {
      submitButton.disabled = false;
    }
  });
}

for (const button of $$("[data-close]")) button.addEventListener("click", () => button.closest("dialog").close());
$("#open-settings").addEventListener("click", showSettings);
$("#legacy-details").addEventListener("toggle", (event) => {
  if (event.currentTarget.open) loadMarket();
});
$("#new-offer").addEventListener("click", () => showOffer());
$("#open-calculator").addEventListener("click", () => showDetail());
$("#refresh-market").addEventListener("click", loadMarket);
$("#prev").addEventListener("click", () => { page--; loadMarket(); });
$("#next").addEventListener("click", () => { page++; loadMarket(); });
for (const button of $$("[data-mode]")) {
  button.addEventListener("click", () => { setMode(button.dataset.mode); page = 1; loadMarket(); });
}
for (const filter of ["#membership", "#sort"]) $(filter).addEventListener("change", () => { page = 1; loadMarket(); });
$("#search").addEventListener("input", () => {
  if ($("#search").value && mode === "eligible") setMode("all");
  page = 1;
  clearTimeout(marketTimer);
  marketTimer = setTimeout(loadMarket, 220);
});
$("#market-rows").addEventListener("click", (event) => {
  const target = event.target.closest("[data-detail]");
  if (target) showDetail(items.find((item) => item.id === Number(target.dataset.detail)));
});
$("#offer-form").elements.side.addEventListener("change", offerSide);
$("#offer-form").elements.itemKey.addEventListener("change", offerSide);
$("#calculator-form").addEventListener("submit", (event) => { event.preventDefault(); calculate(); });
$("#calculator-form").addEventListener("input", () => {
  calcRequest++;
  $("#plan-offer").disabled = true;
  clearTimeout(calcTimer);
  calcTimer = setTimeout(calculate, 140);
});
$("#watch-item").addEventListener("click", async () => {
  const item = detailItem;
  if (!item || !state) return;
  const button = $("#watch-item");
  button.disabled = true;
  try {
    state = await api("/api/watchlist", { id: item.id, enabled: !state.watchlist.includes(item.id) });
    renderWatch();
    loadMarket();
  } catch (error) {
    formError($("#calculator-form"), error.message);
  } finally {
    button.disabled = false;
  }
});
$("#plan-offer").addEventListener("click", () => {
  const calc = formData($("#calculator-form"));
  dialogs["detail-dialog"].close();
  showOffer({ item: detailItem, qty: calc.qty, price: calc.buy });
});
for (const [id, field] of [["#copy-flip-buy", "buy"], ["#copy-flip-sell", "sell"]]) {
  $(id).addEventListener("click", (event) => copyPrice($("#calculator-form").elements[field], event.currentTarget));
}
$("#offers-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const { fill, cancel, collect } = button.dataset;
  if (fill) {
    showFill(Number(fill));
    return;
  }
  if (!cancel && !collect) return;
  if (cancel && !window.confirm("Você já cancelou esta oferta no Grand Exchange?")) return;
  button.disabled = true;
  try {
    state = await api(`/api/offers/${cancel || collect}`, { action: cancel ? "cancel" : "collect" });
    renderState();
  } catch (error) {
    notify(error.message);
  } finally {
    button.disabled = false;
  }
});
$("#positions-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-sell]");
  if (!button) return;
  const pos = state.positions[Number(button.dataset.sell)];
  showOffer({ side: "sell", key: pos.key, qty: pos.available });
});

submit("settings-form", async (form, data) => {
  data.capital = String(parseGp(data.capital));
  state = await api("/api/settings", data);
  notify("Configurações salvas.");
});
submit("offer-form", async (form, data) => {
  if (offerItem && data.side === "buy") data.itemId = offerItem.id;
  state = await api("/api/offers", data);
  location.hash = "ofertas";
  notify("Oferta registrada.");
});
submit("fill-form", async (form, data) => {
  state = await api(`/api/offers/${fillOffer.id}`, { ...data, action: "fill" });
  notify("Execução registrada. Registre a coleta depois de recolher no GE.");
});

window.addEventListener("hashchange", navigate);
window.addEventListener("resize", drawChart);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && isDecisionView(view())) loadDecision();
  if (!document.hidden && view() === "mercado" && $("#legacy-details").open) loadMarket();
});
setInterval(() => {
  if (!document.hidden && isDecisionView(view())) loadDecision();
  if (!document.hidden && view() === "mercado" && $("#legacy-details").open) loadMarket();
}, 180000);

api("/api/state").then((data) => {
  state = data;
  renderState();
  navigate();
}).catch((error) => notify(error.message));
