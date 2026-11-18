"use strict";

const boardKinds = {
  mercado: { key: "flip", label: "Flip", title: "Comprar e revender", action: "Detalhar flip" },
  crafting: { key: "craft", label: "Crafting", title: "Fabricar e vender", action: "Ver receita" },
};
const operationStatus = { ready: "Lote sugerido", check: "A confirmar", loss: "Margem negativa" };
const decisionPageSize = 8;
let decisionSnapshot;
let decisionPage = 1;
let decisionRequest = 0;
let budgetDirty = false;
let budgetOverride = null;
let craftOperation;
let craftRequest = 0;
let craftTimer;
const maxPlannerBudget = 9223372036854775807n;

try {
  const saved = JSON.parse(sessionStorage.getItem("merch-plan-budget"));
  if (saved && /^[0-9]{1,19}$/.test(saved.budget) && /^[0-9]{1,3}$/.test(saved.allocation)
      && BigInt(saved.budget) <= maxPlannerBudget && Number(saved.allocation) >= 1 && Number(saved.allocation) <= 100) {
    budgetOverride = saved;
  }
} catch {
  budgetOverride = null;
}

function isDecisionView(selected) {
  return selected === "visao" || Object.hasOwn(boardKinds, selected);
}

function showDecisionView(selected) {
  const visible = isDecisionView(selected);
  $("#decision-board").hidden = !visible;
  if (!visible) return;
  const overview = selected === "visao";
  $("#decision-round").hidden = !overview || !decisionSnapshot;
  $("#decision-overview").hidden = !overview;
  $("#decision-list").hidden = overview;
  if (!overview) {
    const kind = boardKinds[selected];
    $("#decision-list-title").textContent = kind.title;
    $("#decision-list-copy").textContent = kind.key === "craft"
      ? "Custo dos insumos, preço de venda e lucro por lote de cada receita."
      : "Preço de entrada, saída e resultado no mesmo item.";
  }
  decisionPage = 1;
  $("#decision-search").value = "";
  renderDecision();
  loadDecision();
}

function decisionError(message) {
  const error = $("#decision-error");
  error.textContent = message;
  error.hidden = !message;
}

async function loadDecision(force = false) {
  const request = ++decisionRequest;
  const settings = new URLSearchParams(budgetOverride || {});
  if (force) settings.set("refresh", "1");
  const button = $("#decision-refresh");
  decisionError("");
  button.disabled = true;
  try {
    const result = await api(`/api/opportunities?${settings}`);
    if (request !== decisionRequest) return;
    decisionSnapshot = result;
    renderDecision();
    return true;
  } catch (error) {
    if (request !== decisionRequest) return;
    $("#decision-status").className = "status offline";
    $("#decision-status").textContent = "Falha na atualização";
    decisionError(error.message);
    if (!decisionSnapshot) {
      $("#decision-overview").textContent = "O painel de oportunidades está indisponível.";
      $("#decision-rows").textContent = "O painel de oportunidades está indisponível.";
    }
  } finally {
    if (request === decisionRequest) button.disabled = false;
  }
}

function renderDecision() {
  if (!decisionSnapshot) {
    $("#decision-overview").innerHTML = '<p class="decision-loading">Buscando oportunidades no GE…</p>';
    $("#decision-rows").innerHTML = '<p class="empty">Buscando oportunidades no GE…</p>';
    return;
  }
  const board = decisionSnapshot;
  const source = board.simulation ? "Simulação" : "Caixa registrado";
  if (!budgetDirty) {
    $("#plan-budget").value = displayGpInput(board.budget);
    $("#plan-allocation").value = board.allocation;
  }
  $("#use-cash").hidden = !budgetOverride;
  $("#use-cash").textContent = state?.settings.capital === "0" ? "Voltar ao padrão" : "Usar caixa registrado";
  $("#budget-caption").innerHTML = `${source} · <strong>${money(board.budget)}</strong> · Teto de ${board.allocation}%`;
  const feed = $("#decision-status");
  feed.className = `status ${board.online ? "online" : "cached"}`;
  const feedText = board.online ? "Feed conectado" : board.lastSync ? "Dados em cache" : "Feed indisponível";
  feed.innerHTML = `<span class="dot"></span> ${feedText}`;
  if (board.lastSync) feed.title = `Última consulta: ${dateTime(board.lastSync)}`;
  if (view() === "visao") {
    renderRound();
    renderOverview();
  }
  else if (Object.hasOwn(boardKinds, view())) renderDecisionList();
}

function signal(operation) {
  const style = operation.status === "ready" ? "good" : operation.status === "check" ? "watch" : "";
  return `<span class="signal ${style}">${operationStatus[operation.status]}</span>`;
}

function operationButton(operation, label) {
  return `<button class="button secondary small" type="button" data-operation="${escape(operation.key)}">${label}</button>`;
}

function profitText(operation) {
  return money(operation.metrics?.profit, { plus: true });
}

function metricField(label, value, tone = "", layout = "") {
  return `<div class="${layout}"><span>${label}</span><strong class="${tone}">${value}</strong></div>`;
}

function renderRound() {
  const board = decisionSnapshot;
  const planned = board.round;
  $("#decision-round").hidden = false;
  $("#round-details").hidden = !planned.keys.length;
  $("#round-profit").innerHTML = planned.keys.length ? money(planned.profit, { plus: true }) : "—";
  $("#round-totals").innerHTML =
    metricField("Total a aplicar", money(planned.cost)) +
    metricField("Caixa após compras", money(planned.availableAfter)) +
    metricField("Com saída −2%", money(planned.stress), signedClass(planned.stress));
  $("#round-note").hidden = Boolean(planned.keys.length);
  if (!planned.keys.length) {
    $("#round-note").textContent = "Nenhum lote sugerido coube nos filtros, orçamento e slots atuais.";
    return;
  }
  const byKey = new Map([...board.flip, ...board.craft].map((operation) => [operation.key, operation]));
  const operations = planned.keys.map((key) => byKey.get(key));
  const groups = Object.values(boardKinds).map((kind) => {
    const chosen = operations.filter((operation) => operation.kind === kind.key);
    if (!chosen.length) return "";
    const profit = chosen.reduce((sum, operation) => sum + BigInt(operation.metrics.profit), 0n);
    return `<section class="round-group" aria-label="Operações de ${kind.label}">
      <h3>${kind.label} <span>${money(profit, { plus: true })}</span></h3>
      ${chosen.map((operation) => `<article class="round-row">
        <div class="round-item"><h4>${escape(operation.name)}</h4>
          <p>${gp(operation.quantity)} un. · ${escape(operation.route)}</p></div>
        ${metricField(operation.kind === "flip" ? "Compra / un." : "Insumos / un.", money(operation.buy), "", "round-buy")}
        ${metricField("Venda / un.", money(operation.sell), "", "round-sell")}
        ${metricField("Aplicar", money(operation.metrics.cost), "", "round-cost")}
        ${metricField("Lucro líquido", profitText(operation), signedClass(operation.metrics.profit), "round-gain")}
        ${operationButton(operation, kind.action)}
      </article>`).join("")}
    </section>`;
  }).join("");
  $("#round-summary").textContent = `Ver ${operations.length} ${operations.length === 1 ? "operação" : "operações"} · ${operations.length}/${board.slots} slots`;
  $("#round-operations").innerHTML = groups;
  const includesCraft = operations.some((operation) => operation.kind === "craft");
  const prefix = planned.mixed ? "Rodada mista com maior lucro entre os lotes sugeridos." :
    "Maior lucro entre os lotes sugeridos que cabem nesta rodada.";
  $("#round-assumptions").textContent = prefix + " Todos os lotes chegam pelo menos ao ponto de equilíbrio com a saída 2% menor."
    + (includesCraft ? " Compre os insumos de cada receita em sequência no mesmo slot." : "");
}

function renderOverview() {
  $("#decision-overview").innerHTML = Object.entries(boardKinds).map(([viewName, kind]) => {
    const options = decisionSnapshot[kind.key];
    const best = options.find((operation) => operation.status === "ready") ||
      options.find((operation) => Number(operation.metrics?.profit) > 0);
    if (!best) {
      return `<article class="decision-card ${kind.key}">
        <p class="card-label">${kind.label}</p><h2>${kind.title}</h2>
        <p class="card-copy">Nenhum lote com lucro calculável neste recorte.</p>
        <a class="button secondary" href="#${viewName}">Abrir ${kind.label}</a>
      </article>`;
    }
    const { metrics } = best;
    const line = best.status === "ready" ? "Lucro líquido estimado por lote" : "Lucro potencial a confirmar";
    return `<article class="decision-card ${kind.key}">
      <div class="decision-card-top"><p class="card-label">${kind.label}</p>${signal(best)}</div>
      <h2>${escape(best.name)}</h2>
      <div class="decision-profit"><strong class="${signedClass(metrics.profit)}">${profitText(best)}</strong><span>${line}</span></div>
      <div class="decision-card-stats">
        ${metricField("Investir", money(metrics.cost))}
        ${metricField("Quantidade", gp(best.quantity))}
        ${metricField("Com saída −2%", money(metrics.stressProfit), signedClass(metrics.stressProfit))}
      </div>
      <p class="card-copy">${escape(best.route)} · ${best.kind === "flip" ? "Compra" : "Insumos"} ${money(best.buy)} → venda ${money(best.sell)} por un.</p>
      <p class="card-copy">${escape(best.reason)}</p>
      <div class="decision-card-actions">
        ${operationButton(best, kind.action)}
        <a class="button quiet small" href="#${viewName}">Ver opções de ${kind.label}</a>
      </div>
    </article>`;
  }).join("");
}

function compareOperations(left, right) {
  const rank = { ready: 0, check: 1, loss: 2 };
  if (rank[left.status] !== rank[right.status]) return rank[left.status] - rank[right.status];
  const metric = $("#decision-sort").value;
  if (metric === "roi") return (right.metrics?.roi ?? -Infinity) - (left.metrics?.roi ?? -Infinity);
  if (metric === "cost" && Boolean(left.metrics) !== Boolean(right.metrics)) return left.metrics ? -1 : 1;
  const field = metric === "stress" ? "stressProfit" : metric;
  const a = BigInt(left.metrics?.[field] || 0);
  const b = BigInt(right.metrics?.[field] || 0);
  if (a === b) return left.name.localeCompare(right.name);
  const descending = a > b ? -1 : 1;
  return metric === "cost" ? -descending : descending;
}

function renderDecisionList() {
  const kind = boardKinds[view()];
  const query = $("#decision-search").value.trim().toLocaleLowerCase("pt-BR");
  const mode = $("#decision-filter").value;
  const filtered = decisionSnapshot[kind.key].filter((operation) =>
    (!query || `${operation.name} ${operation.route} ${operation.id}`.toLocaleLowerCase("pt-BR").includes(query)) &&
    (mode === "all" || (mode === "ready" ? operation.status === "ready" : Number(operation.metrics?.profit) > 0))
  ).sort(compareOperations);
  const maxPage = Math.max(1, Math.ceil(filtered.length / decisionPageSize));
  decisionPage = Math.min(maxPage, Math.max(1, decisionPage));
  const start = (decisionPage - 1) * decisionPageSize;
  const shown = filtered.slice(start, start + decisionPageSize);
  $("#decision-rows").innerHTML = shown.length ? shown.map((operation) => {
    const { metrics } = operation;
    const isFlip = operation.kind === "flip";
    const buyLabel = isFlip ? "Compra por un." : "Insumos por peça";
    return `<article class="decision-row">
      <div class="op-name">
        <h3>${escape(operation.name)}</h3>
        <p>${escape(operation.route)} · ${gp(operation.quantity)} un. ${operation.status === "ready" ? "no lote" : "na simulação"}</p>
        ${signal(operation)}
      </div>
      <div class="op-price">
        ${metricField(buyLabel, money(operation.buy))}
        ${metricField("Venda por un.", money(operation.sell))}
      </div>
      <div class="op-money">
        ${metricField("Lucro líquido por lote", profitText(operation), signedClass(metrics?.profit))}
        ${metricField("Investir", money(metrics?.cost))}
        ${metricField("Com saída −2%", money(metrics?.stressProfit), signedClass(metrics?.stressProfit))}
      </div>
      <div class="op-action">${operationButton(operation, kind.action)}</div>
      <p class="op-reason">${escape(operation.reason)}</p>
    </article>`;
  }).join("") : '<p class="empty">Nenhuma opção neste recorte. Escolha “Todas as opções” para consultar outras referências.</p>';
  const count = shown.length ? `${start + 1}–${start + shown.length} de ${gp(filtered.length)} · ` : "";
  $("#decision-count").textContent = count + (kind.key === "craft"
    ? `${decisionSnapshot.recipeCount} rotas cadastradas`
    : "Lotes sugeridos aparecem primeiro");
  $("#decision-prev").disabled = decisionPage === 1;
  $("#decision-next").disabled = decisionPage === maxPage;
}

function showCraft(operation) {
  craftOperation = operation;
  const form = $("#craft-form");
  $("#craft-title").textContent = operation.name;
  $("#craft-route").textContent = operation.route;
  $("#craft-requirements").textContent = operation.skill + (operation.tokens
    ? ` · ${gp(operation.tokens)} tokens de Dungeoneering por peça, calculados à parte`
    : "");
  $("#craft-notes").innerHTML = operation.notes.map((note) => `<li>${escape(note)}</li>`).join("");
  $("#craft-notes").hidden = operation.notes.length === 0;
  $("#craft-wiki").href = operation.source;
  $("#craft-inputs").innerHTML = operation.inputs.map((material) => `<tr>
    <td><label for="craft-price-${material.id}">${escape(material.name)}</label><small>
      ${gp(material.volume)} un. observadas em até 6 h · ${escape(age(material.time))}</small></td>
    <td>${gp(material.amount)}</td>
    <td><input id="craft-price-${material.id}" name="price-${material.id}" inputmode="numeric"
      pattern="[0-9]+" maxlength="19" value="${escape(material.price)}" required></td>
  </tr>`).join("");
  form.elements.qty.value = operation.quantity;
  form.elements.sell.value = operation.sell || "";
  form.elements.extra.value = "0";
  $("#craft-sale-reference").innerHTML = operation.instantSell
    ? `Última venda instantânea da peça · ${money(operation.instantSell)} · ${age(operation.lowTime)}.` : "";
  formError(form, "");
  $("#craft-results").replaceChildren();
  dialogs["craft-dialog"].showModal();
  projectCraft();
}

async function projectCraft() {
  const form = $("#craft-form");
  const revision = ++craftRequest;
  if (!craftOperation || !form.checkValidity()) {
    $("#craft-results").replaceChildren();
    formError(form, "");
    return;
  }
  const prices = Object.fromEntries(craftOperation.inputs.map(({ id }) =>
    [String(id), form.elements.namedItem(`price-${id}`).value]));
  const { qty, sell, extra } = formData(form);
  formError(form, "");
  try {
    const result = await api("/api/craft-projection", {
      recipe: craftOperation.key, qty, sell, extra, prices, instant: craftOperation.instantSell,
    });
    if (revision !== craftRequest || !dialogs["craft-dialog"].open) return;
    const metrics = [
      ["Total a investir", money(result.cost)],
      ["Receita após a tarifa", money(result.net)],
      ["Lucro líquido", money(result.profit), signedClass(result.profit)],
      ["Retorno sobre o custo", percent(result.roi), signedClass(result.roi)],
      ["Venda de equilíbrio", money(result.breakEven)],
      ["Lucro com saída −2%", money(result.stressProfit), signedClass(result.stressProfit)],
    ];
    if (result.instantProfit != null) {
      metrics.push(["Resultado à última saída instantânea", money(result.instantProfit), signedClass(result.instantProfit)]);
    }
    $("#craft-results").innerHTML = metrics.map(([label, value, color = ""]) =>
      `<div><small>${label}</small><strong class="${color}">${value}</strong></div>`).join("");
    if (BigInt(result.cost) > BigInt(craftOperation.budgetCap)) {
      formError(form, "Este lote ultrapassa o teto por operação do orçamento atual.");
    }
  } catch (error) {
    if (revision !== craftRequest) return;
    $("#craft-results").replaceChildren();
    formError(form, error.message);
  }
}

function setBudgetOpen(open) {
  const button = $("#toggle-budget");
  button.setAttribute("aria-expanded", String(open));
  button.textContent = open ? "Fechar edição" : "Editar orçamento";
  $("#budget-form").dataset.open = String(open);
}

$("#toggle-budget").addEventListener("click", (event) => {
  const open = event.currentTarget.getAttribute("aria-expanded") === "false";
  setBudgetOpen(open);
  if (open) $("#plan-budget").focus();
});

$("#budget-form").addEventListener("input", () => { budgetDirty = true; });
$("#budget-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const settings = formData(event.currentTarget);
  try {
    const entered = parseGp(settings.budget);
    if (entered > maxPlannerBudget) throw new Error("Informe um orçamento menor.");
    settings.budget = String(entered);
  } catch (error) {
    decisionError(error.message);
    return;
  }
  budgetOverride = settings;
  budgetDirty = false;
  sessionStorage.setItem("merch-plan-budget", JSON.stringify(budgetOverride));
  decisionPage = 1;
  const toggle = $("#toggle-budget");
  if (await loadDecision() && toggle.getAttribute("aria-expanded") === "true" && toggle.getClientRects().length) {
    setBudgetOpen(false);
    toggle.focus();
  }
});
$("#use-cash").addEventListener("click", () => {
  budgetOverride = null;
  budgetDirty = false;
  sessionStorage.removeItem("merch-plan-budget");
  loadDecision();
});
$("#decision-refresh").addEventListener("click", () => loadDecision(true));
for (const [id, event] of [["search", "input"], ["sort", "change"], ["filter", "change"]]) {
  $(`#decision-${id}`).addEventListener(event, () => {
    decisionPage = 1;
    if (decisionSnapshot) renderDecisionList();
  });
}
$("#decision-prev").addEventListener("click", () => { decisionPage--; renderDecisionList(); });
$("#decision-next").addEventListener("click", () => { decisionPage++; renderDecisionList(); });
$("#decision-board").addEventListener("click", (event) => {
  const key = event.target.closest("[data-operation]")?.dataset.operation;
  if (!key || !decisionSnapshot) return;
  const operation = decisionSnapshot.flip.find((item) => item.key === key) ||
    decisionSnapshot.craft.find((item) => item.key === key);
  if (!operation) return;
  if (operation.kind === "craft") showCraft(operation);
  else showDetail(operation);
});
$("#craft-form").addEventListener("input", () => {
  craftRequest++;
  clearTimeout(craftTimer);
  craftTimer = setTimeout(projectCraft, 160);
});
$("#craft-form").addEventListener("submit", (event) => { event.preventDefault(); projectCraft(); });
$("#copy-craft-sell").addEventListener("click", (event) => copyPrice($("#craft-form").elements.sell, event.currentTarget));
