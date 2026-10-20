"""Entry point: python -m refiner [--dry-run] | --resume [DIRECTORY] | compare [DIRECTORY] [--reference FILE]."""
from refiner.cli import main

if __name__ == "__main__":
    raise SystemExit(main(open_overview=True))
