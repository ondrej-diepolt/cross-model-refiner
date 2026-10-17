"""Spuštění: python -m refiner [--nanecisto] | --pokracovat [SLOZKA]."""
from refiner.cli import main

if __name__ == "__main__":
    raise SystemExit(main(otevrit_prehled=True))
