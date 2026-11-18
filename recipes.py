"""Rotas com receitas verificadas e saída negociável no Grand Exchange."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    key: str
    output: int
    route: str
    inputs: tuple[tuple[int, int], ...]
    skill: str
    wiki: str
    tokens: int = 0

    @property
    def source(self):
        return f"https://runescape.wiki/w/{self.wiki}"


RECIPES = (
    Recipe("tectonic-mask", 43166, "Essências do GE",
           ((28608, 1), (43165, 140), (28628, 1), (50345, 2)),
           "Runecrafting 91", "Elite_tectonic_armour"),
    Recipe("tectonic-top", 43169, "Essências do GE",
           ((28611, 1), (43165, 420), (28628, 3), (50345, 5)),
           "Runecrafting 93", "Elite_tectonic_robe_top", 100_000),
    Recipe("tectonic-top-virtus", 43169, "Extração de Virtus",
           ((28611, 1), (43165, 420), (28628, 3), (20163, 1)),
           "Runecrafting 99 e acesso à Dragonkin anvil", "Elite_tectonic_robe_top", 100_000),
    Recipe("tectonic-top-base", 43169, "Fabricar a base e extrair Virtus",
           ((28627, 42), (43165, 420), (28628, 6), (20163, 1)),
           "Runecrafting 99 e acesso à Dragonkin anvil", "Elite_tectonic_robe_top", 100_000),
    Recipe("tectonic-bottom", 43172, "Essências do GE",
           ((28614, 1), (43165, 280), (28628, 2), (50345, 3)),
           "Runecrafting 92", "Elite_tectonic_armour"),
    Recipe("tectonic-bottom-virtus", 43172, "Extração de Virtus",
           ((28614, 1), (43165, 280), (28628, 2), (20167, 1)),
           "Runecrafting 99 e acesso à Dragonkin anvil", "Elite_tectonic_armour"),
    Recipe("sirenic-mask", 43155, "Essências do GE",
           ((29854, 1), (43164, 140), (29864, 1), (50347, 2)),
           "Crafting 91", "Elite_sirenic_armour"),
    Recipe("sirenic-hauberk", 43158, "Essências do GE",
           ((29857, 1), (43164, 420), (29864, 3), (50347, 5)),
           "Crafting 93", "Elite_sirenic_hauberk", 100_000),
    Recipe("sirenic-hauberk-pernix", 43158, "Extração de Pernix",
           ((29857, 1), (43164, 420), (29864, 3), (20151, 1)),
           "Crafting 99 e acesso à Dragonkin anvil", "Elite_sirenic_hauberk", 100_000),
    Recipe("sirenic-chaps", 43161, "Essências do GE",
           ((29860, 1), (43164, 280), (29864, 2), (50347, 3)),
           "Crafting 92", "Elite_sirenic_chaps"),
    Recipe("sirenic-chaps-pernix", 43161, "Extração de Pernix",
           ((29860, 1), (43164, 280), (29864, 2), (20155, 1)),
           "Crafting 99 e acesso à Dragonkin anvil", "Elite_sirenic_chaps"),
    Recipe("sirenic-patch", 50349, "Patch de reparo",
           ((43164, 7), (29863, 1), (43979, 2), (47506, 2)),
           "Crafting 91", "Elite_sirenic_repair_patch"),
    Recipe("tectonic-patch", 50350, "Patch de reparo",
           ((43165, 7), (28627, 1), (43975, 2), (47506, 2)),
           "Runecrafting 91", "Elite_tectonic_repair_patch"),
    Recipe("eldritch", 47470, "Montar as três peças",
           ((47490, 1), (47492, 1), (47494, 1)),
           "Fletching 96", "Eldritch_crossbow"),
    Recipe("staff", 51772, "Montar as três peças",
           ((51776, 1), (51779, 1), (51782, 1)),
           "Crafting 95", "Fractured_Staff_of_Armadyl"),
    Recipe("last-guardian", 53338, "Montar as três peças",
           ((53332, 1), (53334, 1), (53336, 1)),
           "Fletching 95", "Bow_of_the_Last_Guardian"),
    Recipe("ek-zekkil", 52511, "Montar as três peças",
           ((52505, 1), (52507, 1), (52509, 1)),
           "Smithing 95", "Ek-ZekKil"),
) + tuple(
    Recipe(f"dracolich-{output}", output, "Upgrade com Vorkath’s scale",
           ((base, 1), (56321, 1)), "Crafting 92", "Elite_dracolith_armour")
    for output, base in ((56114, 56090), (56128, 56104), (56132, 56108), (56124, 56100), (56120, 56096))
)

BY_KEY = {recipe.key: recipe for recipe in RECIPES}
