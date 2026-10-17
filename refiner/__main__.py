"""Spuštění: python -m refiner [--nanecisto] | --pokracovat [SLOZKA] | porovnat [SLOZKA] [--reference SOUBOR]."""
from refiner.cli import main

if __name__ == "__main__":
    raise SystemExit(main(otevrit_prehled=True))
