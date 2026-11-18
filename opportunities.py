"""Projeções de compra, transformação e venda para a tela de decisão."""

from collections import defaultdict
from dataclasses import dataclass

from ledger import MAX_QUANTITY, economics, integer, is_bond, tax
from recipes import BY_KEY, RECIPES


@dataclass
class Activity:
    sold: int = 0
    bought: int = 0
    low_total: int = 0
    high_total: int = 0

    @property
    def low(self):
        return (self.low_total + self.sold - 1) // self.sold if self.sold else None

    @property
    def high(self):
        return self.high_total // self.bought if self.bought else None

    @property
    def acquisition(self):
        return (self.high_total + self.bought - 1) // self.bought if self.bought else None


def aggregate(windows):
    activity = defaultdict(Activity)
    for window in windows:
        for key, row in window["data"].items():
            current = activity[key]
            for price, volume, count, total in (
                ("avgLowPrice", "lowPriceVolume", "sold", "low_total"),
                ("avgHighPrice", "highPriceVolume", "bought", "high_total"),
            ):
                value, quantity = row.get(price), row.get(volume)
                if value and quantity:
                    setattr(current, count, getattr(current, count) + quantity)
                    setattr(current, total, getattr(current, total) + round(value * quantity))
    return activity


class PlanningContext:
    def __init__(self, data, state, budget=None, allocation=None):
        self.data = data
        self.state = state
        self.simulation = budget is not None or state["settings"]["capital"] == "0"
        self.capital = (budget if budget is not None else
                        1_000_000_000 if self.simulation else int(state["available"]))
        self.allocation = allocation if self.simulation and allocation is not None else state["settings"]["allocation"]
        self.ceiling = (self.capital if self.simulation else int(state["settings"]["capital"])) * self.allocation // 100
        self.slots = (8 if state["settings"]["profile"] == "members" else 3)
        if not self.simulation:
            self.slots -= state["slots"]
        self.profile = state["settings"]["profile"]

    def item_budget(self, item):
        exposure = 0 if self.simulation else sum(
            int(self.state["exposure"].get(key, 0)) for key in self.keys(item))
        return max(0, min(self.capital, self.ceiling - exposure))

    def keys(self, item):
        return str(item["id"]), f"manual:{item['name'].casefold()}"

    def buy_remaining(self, item):
        limit = item.get("limit") or 0
        if self.simulation:
            return limit
        used = sum(self.state["windows"].get(key, {}).get("used", 0)
                   + self.state["pendingBuys"].get(key, 0) for key in self.keys(item))
        return max(0, limit - used)

    def is_recent(self, timestamp, seconds):
        return bool(timestamp and -60 <= self.data["now"] - timestamp <= seconds)

    def can_trade(self, item):
        return self.profile == "members" or not item["members"]


def operation_metrics(unit_cost, sell, quantity, exempt=False, instant=None):
    result = economics(unit_cost, sell, quantity, exempt)
    result["net"] = str(quantity * (sell - int(result["fee"])))
    if instant:
        result["instantProfit"] = str(quantity * (instant - tax(instant, exempt) - unit_cost))
    return result


def flip_opportunities(context, hourly, recent, last_hour):
    data = context.data
    result = []
    broad_coverage = len(data["hourly"]) >= 5
    quick_coverage = len(data["recent"]) >= 5 and bool(
        data["hourly"] and data["hourly"][0]["timestamp"] == data["latestHour"])
    for key, item in data["catalogue"].items():
        if not context.can_trade(item):
            continue
        quote = data["latest"].get(key, {})
        low, high = quote.get("low"), quote.get("high")
        low_at, high_at = quote.get("lowTime"), quote.get("highTime")
        if (not low or not high or high <= low
                or not all(context.is_recent(stamp, 24 * 3600) for stamp in (low_at, high_at))):
            continue
        pattern = "Giro rápido" if low < 5_000_000 else "Equipamento e alto valor"
        if low < 5_000_000:
            short, hour = recent[key], last_hour[key]
            activity = hour
            liquid = min(hour.sold, hour.bought) // 10
            liquid = min(liquid, min(short.sold, short.bought) // 5)
            backed = (quick_coverage and short.low and short.high and hour.low and hour.high
                      and min(hour.sold, hour.bought) >= 20
                      and abs(low_at - high_at) <= 20 * 60
                      and all(context.is_recent(stamp, 1800) for stamp in (low_at, high_at))
                      and int(economics(hour.low, hour.high, 1, is_bond(item["name"]))["margin"]) > 0)
            price_activity = short
            reason = "Confira os dois lados e o giro nas janelas de 30 min e 1 h."
            volume_window = "1 h"
        else:
            activity = price_activity = hourly[key]
            smaller_side = min(activity.sold, activity.bought)
            liquid = min(4, max(1, smaller_side // 5)) if smaller_side >= 3 else 0
            backed = (broad_coverage and smaller_side >= 3 and abs(low_at - high_at) <= 3 * 3600
                      and all(context.is_recent(stamp, 6 * 3600) for stamp in (low_at, high_at)))
            reason = "Confira o giro dos dois lados e os preços recentes no GE."
            volume_window = "até 6 h"
        buy = max(low, price_activity.low or low)
        sell = min(high, price_activity.high or high)
        unit = operation_metrics(buy, sell, 1, is_bond(item["name"]))
        if int(unit["profit"]) <= 0:
            continue
        remaining = context.buy_remaining(item)
        capacity = min(context.item_budget(item) // buy, remaining, liquid)
        proposed = bool(backed and data["online"] and capacity and context.slots > 0 and unit["roi"] <= 60)
        if not proposed:
            if not data["online"]:
                reason = "Os preços estão em cache. Atualize o feed antes de operar."
            elif not backed or unit["roi"] > 60 or not liquid:
                reason = "A margem precisa de confirmação de preço e volume nos dois lados."
            elif not remaining:
                reason = "Confira o limite de compra disponível no GE."
            elif context.item_budget(item) < buy:
                reason = "O item ultrapassa o caixa ou o teto por operação."
            elif context.slots <= 0:
                reason = "Libere um slot no GE para abrir a oferta."
            else:
                reason = "A quantidade disponível precisa de confirmação no GE."
        qty = capacity if proposed else 1
        result.append({
            "key": f"flip-{key}", "kind": "flip", "id": item["id"], "name": item["name"],
            "members": item["members"], "route": pattern, "status": "ready" if proposed else "check",
            "reason": reason, "quantity": qty, "buy": str(buy), "sell": str(sell),
            "metrics": operation_metrics(buy, sell, qty, is_bond(item["name"]), instant=low),
            "high": str(high), "low": str(low), "lowTime": low_at, "highTime": high_at,
            "limit": item.get("limit"), "limitLeft": remaining, "liquidityLimit": liquid,
            "hourHighVolume": activity.bought, "hourLowVolume": activity.sold, "volumeWindow": volume_window,
            "simulation": context.simulation,
        })
    return result


def craft_opportunity(recipe, context, hourly):
    data = context.data
    catalogue = data["catalogue"]
    output_key = str(recipe.output)
    product = catalogue.get(output_key)
    if not product:
        return None
    sale = data["latest"].get(output_key, {})
    demand = hourly[output_key]
    sell = sale.get("high")
    if sell and demand.high:
        sell = min(sell, demand.high)
    flags = []
    capacity = max(1, demand.bought // 5) if demand.bought >= 2 else 0
    rows = []
    for item_id, amount in recipe.inputs:
        key = str(item_id)
        item = catalogue.get(key)
        quote = data["latest"].get(key, {})
        price = quote.get("high")
        volume = hourly[key].bought
        if price and hourly[key].acquisition:
            price = max(price, hourly[key].acquisition)
        qty_ge = context.buy_remaining(item) if item else 0
        name = item["name"] if item else f"Item {item_id}"
        if not price or not context.is_recent(quote.get("highTime"), 6 * 3600):
            flags.append(f"Preço de compra de {name} a confirmar")
        if volume < amount:
            flags.append(f"{name}: {volume} de {amount} unidades negociadas no lado comprador")
        if qty_ge < amount:
            flags.append(f"Limite de compra estimado insuficiente para {name}")
        liquid = max(amount, volume // 4) // amount if volume >= amount else 0
        capacity = min(capacity, qty_ge // amount, liquid)
        rows.append({"id": item_id, "name": name, "amount": amount, "price": str(price) if price else None,
                     "time": quote.get("highTime"), "volume": volume, "limit": qty_ge})
    if not data["online"] or len(data["hourly"]) < 5:
        flags.insert(0, "O feed ainda não tem registros suficientes da janela de até 6 h")
    if demand.bought < 2 or not context.is_recent(sale.get("highTime"), 6 * 3600):
        flags.insert(0, f"Saída a confirmar · {demand.bought} unidades no lado comprador")
    if recipe.tokens:
        flags.append(f"Confirme {recipe.tokens:,}".replace(",", ".") + " tokens de Dungeoneering por peça")
    if not context.can_trade(product):
        flags.insert(0, "A receita exige uma conta membro")
    if context.slots <= 0:
        flags.append("Libere um slot no GE para comprar os insumos")
    cost = sum(row["amount"] * int(row["price"]) for row in rows) if all(row["price"] for row in rows) else 0
    cap = context.item_budget(product)
    if cost > cap:
        flags.insert(0, "O custo de uma peça ultrapassa o caixa ou o teto por operação")
    if cost:
        capacity = min(capacity, cap // cost)
    unit = operation_metrics(cost, sell, 1) if cost and sell else None
    if not unit:
        flags.insert(0, "Complete os preços para projetar o resultado")
    status = "check"
    if unit and int(unit["profit"]) <= 0:
        status = "loss"
        flags.insert(0, "A venda estimada não cobre o custo e a tarifa")
    elif unit and capacity > 0 and not flags:
        status = "ready"
    qty = capacity if status == "ready" else 1
    return {
        "key": recipe.key, "kind": "craft", "id": recipe.output, "name": product["name"], "route": recipe.route,
        "status": status, "reason": flags[0] if flags else "Confira os requisitos da receita e as ofertas no GE.",
        "notes": list(dict.fromkeys(flags)), "quantity": qty,
        "buy": str(cost) if cost else None, "sell": str(sell) if sell else None,
        "metrics": operation_metrics(cost, sell, qty, instant=sale.get("low")) if unit else None,
        "inputs": rows, "tokens": recipe.tokens, "skill": recipe.skill, "source": recipe.source, "budgetCap": str(cap),
        "instantSell": str(sale["low"]) if sale.get("low") else None,
        "lowTime": sale.get("lowTime"), "highTime": sale.get("highTime"), "volume": demand.bought,
    }


@dataclass(frozen=True)
class RoundLot:
    key: str
    kind: str
    output: int
    cost: int
    profit: int
    stress: int
    purchases: tuple[tuple[int, int, int], ...]


def round_lot(row):
    qty = row["quantity"]
    if row["kind"] == "flip":
        purchases = ((row["id"], qty, min(row["limitLeft"], row["liquidityLimit"])),)
    else:
        purchases = tuple(
            (item["id"], item["amount"] * qty, min(item["limit"], max(item["amount"], item["volume"] // 4)))
            for item in row["inputs"]
        )
    metrics = row["metrics"]
    return RoundLot(row["key"], row["kind"], row["id"], int(metrics["cost"]),
                    int(metrics["profit"]), int(metrics["stressProfit"]), purchases)


def reserve_purchases(lot, current):
    updated = current.copy()
    for item, quantity, limit in lot.purchases:
        used, previous_limit = updated.get(item, (0, limit))
        cap = min(limit, previous_limit)
        if used + quantity > cap:
            return None
        updated[item] = used + quantity, cap
    return updated


def suggested_round(rows, budget, slots):
    # Prices and quantities are those of the displayed lots. A crafting lot can
    # purchase its ingredients sequentially using the slot reserved for that lot.
    lots = [round_lot(row) for row in rows if row["status"] == "ready"
            and int(row["metrics"]["profit"]) > 0 and int(row["metrics"]["stressProfit"]) >= 0
            and int(row["metrics"]["cost"]) <= budget]
    lots.sort(key=lambda lot: (-lot.profit, -lot.stress, lot.key))
    flips = [lot for lot in lots if lot.kind == "flip"]
    crafts = [lot for lot in lots if lot.kind == "craft"]
    mixed = slots >= 2 and any(
        flip.output != craft.output and flip.cost + craft.cost <= budget
        and reserve_purchases(flip, reserve_purchases(craft, {})) is not None
        for craft in crafts for flip in flips
    )
    prefix = [0]
    for lot in lots:
        prefix.append(prefix[-1] + lot.profit)
    remaining_kinds = [set() for _ in range(len(lots) + 1)]
    next_kind = [{} for _ in range(len(lots) + 1)]
    for index in range(len(lots) - 1, -1, -1):
        remaining_kinds[index] = remaining_kinds[index + 1] | {lots[index].kind}
        next_kind[index] = {**next_kind[index + 1], lots[index].kind: index}
    best = []
    best_profit = -1

    def search(start, picked, cost, profit, purchases, outputs, kinds):
        nonlocal best, best_profit
        short = {"flip", "craft"} - kinds if mixed else set()
        remaining = slots - len(picked)
        if len(short) > remaining or not short <= remaining_kinds[start]:
            return
        if not short and profit > best_profit:
            best_profit, best = profit, picked
        if not remaining:
            return
        for index in range(start, len(lots)):
            end = min(len(lots), index + remaining)
            upper = profit + prefix[end] - prefix[index]
            if upper <= best_profit:
                break
            if not short <= remaining_kinds[index]:
                break
            for kind in short:
                required = next_kind[index][kind]
                if required >= end:
                    upper += lots[required].profit - lots[end - 1].profit
            if upper <= best_profit:
                continue
            lot = lots[index]
            if lot.output in outputs or cost + lot.cost > budget:
                continue
            updated = reserve_purchases(lot, purchases)
            if updated is None:
                continue
            search(index + 1, picked + [lot], cost + lot.cost, profit + lot.profit,
                   updated, outputs | {lot.output}, kinds | {lot.kind})

    search(0, [], 0, 0, {}, set(), set())
    spend = sum(lot.cost for lot in best)
    return {
        "keys": [lot.key for lot in best], "mixed": mixed, "cost": str(spend),
        "profit": str(sum(lot.profit for lot in best)), "stress": str(sum(lot.stress for lot in best)),
        "availableAfter": str(budget - spend),
    }


def decision_board(market, ledger, filters):
    budget = integer(filters["budget"], "o orçamento", minimum=0) if "budget" in filters else None
    allocation = integer(filters["allocation"], "o teto por operação", maximum=100) if "allocation" in filters else None
    data = market.decision_data(force=filters.get("refresh") == "1")
    context = PlanningContext(data, ledger.state(), budget, allocation)
    recent = aggregate(data["recent"])
    hourly = aggregate(data["hourly"])
    last_hour = aggregate(data["hourly"][:1])
    flips = flip_opportunities(context, hourly, recent, last_hour)
    crafts = [row for recipe in RECIPES if (row := craft_opportunity(recipe, context, hourly))]

    def order(row):
        status = {"ready": 0, "check": 1, "loss": 2}[row["status"]]
        profit = int(row["metrics"]["profit"]) if row["metrics"] else 0
        return status, -profit, row["name"]

    flips.sort(key=order)
    crafts.sort(key=order)
    shown_flips = flips[:150]
    return {
        "flip": shown_flips, "craft": crafts, "flipCount": len(flips), "recipeCount": len(RECIPES),
        "budget": str(context.capital), "allocation": context.allocation, "simulation": context.simulation,
        "slots": context.slots, "profile": context.profile, "lastSync": data["latestAt"], "online": data["online"],
        "hours": len(data["hourly"]), "recentBlocks": len(data["recent"]),
        "round": suggested_round(shown_flips + crafts, context.capital, context.slots),
    }


def craft_projection(data):
    key = data.get("recipe")
    recipe = BY_KEY.get(key) if isinstance(key, str) else None
    if not recipe:
        raise ValueError("Receita não encontrada.")
    prices = data.get("prices")
    if not isinstance(prices, dict):
        raise ValueError("Informe os preços dos insumos.")
    quantity = integer(data.get("qty"), "a quantidade", maximum=MAX_QUANTITY)
    sell = integer(data.get("sell"), "a saída")
    extra = integer(data.get("extra", "0"), "os custos extras", minimum=0)
    unit_cost = sum(amount * integer(prices.get(str(item_id)), "o preço do insumo")
                    for item_id, amount in recipe.inputs) + extra
    instant = integer(data["instant"], "a saída instantânea") if data.get("instant") else None
    return operation_metrics(unit_cost, sell, quantity, instant=instant)
