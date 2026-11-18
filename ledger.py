"""Registro local de ofertas e execuções do Grand Exchange."""

import sqlite3
import time
from contextlib import closing, contextmanager

MAX_GP = 2**63 - 1
MAX_QUANTITY = 2**31 - 1
WINDOW = 4 * 60 * 60


def integer(value, label, minimum=1, maximum=MAX_GP):
    raw = str(value)
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 19:
        raise ValueError(f"Informe {label} em números inteiros, sem separadores.")
    result = int(raw)
    if not minimum <= result <= maximum:
        raise ValueError(f"O valor de {label} está fora da faixa permitida.")
    return result


def is_bond(name):
    return name.strip().casefold() in {"bond", "runescape bond"}


def tax(price, exempt=False):
    return 0 if exempt else price // 50


def occupies_slot(offer):
    return offer["status"] == "open" or offer["items_due"] > 0 or int(offer["cash_due"]) > 0


def economics(buy, sell, quantity, exempt=False):
    fee = tax(sell, exempt)
    spread = sell - fee - buy
    break_even = buy if exempt else buy + (buy - 1) // 49
    stress_sale = max(1, sell * 98 // 100)
    return {
        "fee": str(fee), "margin": str(spread), "breakEven": str(break_even),
        "cost": str(quantity * buy), "profit": str(quantity * spread),
        "roi": round(spread / buy * 100, 3),
        "stressProfit": str(quantity * (stress_sale - tax(stress_sale, exempt) - buy)),
    }


class Ledger:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as db:
            db.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    capital TEXT NOT NULL DEFAULT '0',
                    profile TEXT NOT NULL DEFAULT 'members',
                    allocation INTEGER NOT NULL DEFAULT 20
                );
                INSERT OR IGNORE INTO settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY, item_key TEXT NOT NULL, name TEXT NOT NULL,
                    side TEXT NOT NULL, qty INTEGER NOT NULL, target TEXT NOT NULL,
                    created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                    remaining INTEGER NOT NULL, cash_due TEXT NOT NULL DEFAULT '0',
                    items_return INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY, offer_id INTEGER NOT NULL REFERENCES offers(id),
                    qty INTEGER NOT NULL, price TEXT NOT NULL, fee TEXT NOT NULL,
                    cost TEXT NOT NULL, created INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lots (
                    fill_id INTEGER PRIMARY KEY REFERENCES fills(id),
                    remaining INTEGER NOT NULL, collected INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS offers_by_item ON offers(item_key, side, status);
                CREATE INDEX IF NOT EXISTS fills_by_offer ON fills(offer_id, id);
                CREATE TABLE IF NOT EXISTS watchlist (item_id INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS feed_cache (
                    key TEXT PRIMARY KEY, fetched INTEGER NOT NULL, payload TEXT NOT NULL
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def write(self):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def summary(self, db):
        config = dict(db.execute("SELECT capital, profile, allocation FROM settings").fetchone())
        offers = [dict(row) for row in db.execute("SELECT * FROM offers ORDER BY id DESC")]
        fills = [dict(row) for row in db.execute("""
            SELECT f.*, o.name, o.side, o.item_key, o.created AS opened
            FROM fills f JOIN offers o ON o.id = f.offer_id ORDER BY f.id DESC
        """)]
        reserved = sum(int(o["target"]) * o["remaining"] for o in offers
                       if o["status"] == "open" and o["side"] == "buy")
        due = sum(int(o["cash_due"]) for o in offers)
        spent = sum(f["qty"] * int(f["price"]) for f in fills if f["side"] == "buy")
        received = sum(f["qty"] * int(f["price"]) - int(f["fee"])
                       for f in fills if f["side"] == "sell")
        profit = sum(f["qty"] * int(f["price"]) - int(f["fee"]) - int(f["cost"])
                     for f in fills if f["side"] == "sell")
        available = int(config["capital"]) - spent + received - reserved - due
        positions = {}
        for row in db.execute("""
            SELECT o.item_key, o.name, f.price, l.remaining, l.collected, f.offer_id
            FROM lots l JOIN fills f ON f.id = l.fill_id JOIN offers o ON o.id = f.offer_id
            WHERE l.remaining > 0 ORDER BY f.id
        """):
            pos = positions.setdefault(row["item_key"], {
                "key": row["item_key"], "name": row["name"], "qty": 0, "available": 0,
                "cost": 0, "pending": 0,
            })
            pos["qty"] += row["remaining"]
            pos["cost"] += row["remaining"] * int(row["price"])
            if row["collected"]:
                pos["available"] += row["remaining"]
            else:
                pos["pending"] += row["remaining"]
        pending = {row["offer_id"]: row["qty"] for row in db.execute("""
            SELECT f.offer_id, SUM(l.remaining) AS qty FROM lots l
            JOIN fills f ON f.id = l.fill_id WHERE l.collected = 0 GROUP BY f.offer_id
        """)}
        exposure = {key: pos["cost"] for key, pos in positions.items()}
        pending_buys = {}
        for offer in offers:
            key = offer["item_key"]
            offer["items_due"] = pending.get(offer["id"], 0) + offer["items_return"]
            if offer["status"] == "open" and offer["side"] == "sell":
                positions[key]["available"] -= offer["remaining"]
            if offer["items_return"]:
                positions[key]["available"] -= offer["items_return"]
                positions[key]["pending"] += offer["items_return"]
            if offer["status"] == "open" and offer["side"] == "buy":
                exposure[key] = exposure.get(key, 0) + offer["remaining"] * int(offer["target"])
                pending_buys[key] = pending_buys.get(key, 0) + offer["remaining"]

        windows = {}
        now = int(time.time())
        for fill in reversed(fills):
            if fill["side"] != "buy":
                continue
            key = fill["item_key"]
            if key not in windows or fill["created"] >= windows[key]["reset"]:
                windows[key] = {"used": 0, "reset": fill["created"] + WINDOW}
            windows[key]["used"] += fill["qty"]
        return {
            "settings": config, "available": str(available), "reserved": str(reserved),
            "due": str(due), "stock": str(sum(p["cost"] for p in positions.values())),
            "profit": str(profit), "offers": offers, "fills": fills,
            "slots": sum(occupies_slot(offer) for offer in offers),
            "positions": [{**p, "cost": str(p["cost"])} for p in positions.values()],
            "exposure": {k: str(v) for k, v in exposure.items()},
            "pendingBuys": pending_buys,
            "windows": {key: value for key, value in windows.items() if value["reset"] > now},
            "watchlist": [row[0] for row in db.execute("SELECT item_id FROM watchlist")],
        }

    def state(self):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return self.summary(db)

    def settings(self, data):
        capital = integer(data.get("capital"), "o capital", minimum=0)
        profile = data.get("profile")
        if profile not in {"free", "members"}:
            raise ValueError("Selecione um perfil válido.")
        allocation = integer(data.get("allocation"), "o teto por item", maximum=100)
        with self.write() as db:
            state = self.summary(db)
            old_capital = int(state["settings"]["capital"])
            if capital - old_capital + int(state["available"]) < 0:
                raise ValueError("Esse capital deixaria o caixa livre negativo diante das operações registradas.")
            if profile == "free" and state["slots"] > 3:
                raise ValueError("Finalize ou cancele ofertas até ficar com no máximo três slots ocupados.")
            db.execute("UPDATE settings SET capital=?, profile=?, allocation=?",
                       (str(capital), profile, allocation))

    def new_offer(self, data, catalogue):
        name = str(data.get("name", "")).strip()
        item_id = data.get("itemId")
        item_key = data.get("itemKey")
        if item_id is not None:
            item_id = integer(item_id, "o ID do item")
            info = catalogue.get(str(item_id))
            if info:
                name = info["name"]
            item_key = str(item_id)
        side = data.get("side")
        if side not in {"buy", "sell"}:
            raise ValueError("Selecione compra ou venda.")
        if side == "buy" and (not name or len(name) > 120):
            raise ValueError("Informe o nome do item (até 120 caracteres).")
        quantity = integer(data.get("qty"), "a quantidade", maximum=MAX_QUANTITY)
        price = integer(data.get("price"), "o preço por unidade")
        with self.write() as db:
            state = self.summary(db)
            if state["slots"] >= (
                8 if state["settings"]["profile"] == "members" else 3
            ):
                raise ValueError("Todos os slots configurados do GE estão ocupados.")
            if side == "buy":
                if quantity * price > int(state["available"]):
                    raise ValueError("A oferta ultrapassa o GP disponível.")
                if item_id is not None and not catalogue.get(str(item_id)):
                    raise ValueError("Selecione um item do catálogo ou registre pelo nome.")
                normalized = name.casefold()
                matches = [key for key, item in catalogue.items() if item["name"].casefold() == normalized]
                if item_id is None:
                    existing = {o["item_key"]: o["name"] for o in state["offers"]
                                if o["name"].casefold() == normalized}
                    if len(existing) > 1 or len(matches) > 1:
                        raise ValueError("Selecione o item pelo catálogo para distinguir nomes iguais.")
                    item_key = matches[0] if matches else next(iter(existing), f"manual:{normalized}")
                    name = existing.get(item_key, name)
                info = catalogue.get(item_key)
                if info and info["members"] and state["settings"]["profile"] == "free":
                    raise ValueError("Este item requer uma conta membro.")
                if len(matches) == 1:
                    db.execute("UPDATE offers SET item_key=?, name=? WHERE item_key=?",
                               (item_key, name, f"manual:{normalized}"))
            else:
                pos = next((p for p in state["positions"] if p["key"] == item_key), None)
                if not pos or quantity > pos["available"]:
                    raise ValueError("A quantidade supera o estoque coletado e livre deste item.")
                name = pos["name"]
            db.execute("""
                INSERT INTO offers(item_key, name, side, qty, target, created, remaining)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (item_key, name, side, quantity, str(price), int(time.time()), quantity))

    def change_offer(self, offer_id, data):
        with self.write() as db:
            offer = db.execute("SELECT * FROM offers WHERE id=?", (offer_id,)).fetchone()
            if offer is None:
                raise ValueError("Oferta não encontrada.")
            action = data.get("action")
            if action == "collect":
                db.execute("UPDATE offers SET cash_due='0', items_return=0 WHERE id=?", (offer_id,))
                db.execute("""
                    UPDATE lots SET collected=1 WHERE fill_id IN
                    (SELECT id FROM fills WHERE offer_id=?)
                """, (offer_id,))
                return
            if offer["status"] != "open":
                raise ValueError("Essa oferta já foi encerrada.")
            due = int(offer["cash_due"])
            if action == "cancel":
                if offer["side"] == "buy":
                    due += offer["remaining"] * int(offer["target"])
                returned = offer["remaining"] if offer["side"] == "sell" else 0
                db.execute("UPDATE offers SET status='cancelled', cash_due=?, items_return=? WHERE id=?",
                           (str(due), returned, offer_id))
                return
            if action != "fill":
                raise ValueError("Ação inválida.")
            self.record_fill(db, offer, data, due)

    def record_fill(self, db, offer, data, due):
        qty = integer(data.get("qty"), "a quantidade executada", maximum=offer["remaining"])
        price = integer(data.get("price"), "o preço executado")
        target = int(offer["target"])
        buying = offer["side"] == "buy"
        if (buying and price > target) or (not buying and price < target):
            raise ValueError("O preço executado não respeita o limite da oferta registrada.")
        if buying:
            fee = 0
            cost = qty * price
            due += qty * (target - price)
        else:
            fee = (integer(data["fee"], "a taxa total", 0, min(qty * price, MAX_GP))
                   if data.get("fee") not in {None, ""} else tax(price, is_bond(offer["name"])) * qty)
            cost = 0
            left = qty
            lots = db.execute("""
                SELECT l.fill_id, l.remaining, f.price FROM lots l
                JOIN fills f ON l.fill_id = f.id JOIN offers o ON o.id = f.offer_id
                WHERE o.item_key=? AND l.collected=1 AND l.remaining>0 ORDER BY l.fill_id
            """, (offer["item_key"],)).fetchall()
            for lot in lots:
                if not left:
                    break
                taken = min(left, lot["remaining"])
                cost += taken * int(lot["price"])
                left -= taken
                db.execute("UPDATE lots SET remaining=remaining-? WHERE fill_id=?",
                           (taken, lot["fill_id"]))
            if left:
                raise ValueError("Estoque insuficiente para registrar a venda.")
            due += qty * price - fee
        fill = db.execute("""
            INSERT INTO fills(offer_id,qty,price,fee,cost,created) VALUES (?,?,?,?,?,?)
        """, (offer["id"], qty, str(price), str(fee), str(cost), int(time.time())))
        if buying:
            db.execute("INSERT INTO lots(fill_id, remaining) VALUES (?,?)", (fill.lastrowid, qty))
        remaining = offer["remaining"] - qty
        db.execute("UPDATE offers SET remaining=?, status=?, cash_due=? WHERE id=?",
                   (remaining, "open" if remaining else "completed", str(due), offer["id"]))

    def watch(self, item_id, enabled):
        with self.write() as db:
            if enabled:
                db.execute("INSERT OR IGNORE INTO watchlist VALUES (?)", (item_id,))
            else:
                db.execute("DELETE FROM watchlist WHERE item_id=?", (item_id,))
