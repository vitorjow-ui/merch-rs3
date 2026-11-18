"""Build the static edition for a GitHub Pages project site."""

from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dist" / "merch-rs3"


def build():
    engine = OUTPUT / "engine"
    engine.mkdir(parents=True, exist_ok=True)
    for name in ("application", "ledger", "market", "opportunities", "recipes"):
        copyfile(ROOT / f"{name}.py", engine / f"{name}.py")
    copyfile(ROOT / "pages" / "browser.py", engine / "browser.py")
    for name in ("styles.css", "app.js", "board.js"):
        copyfile(ROOT / "web" / name, OUTPUT / name)
    for name in ("hosted.js", "worker.js"):
        copyfile(ROOT / "pages" / name, OUTPUT / name)
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    index = index.replace('  <script src="./app.js" defer></script>',
                          '  <script src="./hosted.js" defer></script>\n'
                          '  <script src="./app.js" defer></script>', 1)
    index = index.replace('id="export-trades" href="/api/exports/trades.csv"', 'id="export-trades" href="#historico"', 1)
    index = index.replace("Merch RS3 · Painel local", "Merch RS3 · Histórico salvo neste navegador", 1)
    (OUTPUT / "index.html").write_text(index, encoding="utf-8")
    (OUTPUT / ".nojekyll").touch()


if __name__ == "__main__":
    build()
