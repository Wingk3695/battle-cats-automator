from __future__ import annotations

import argparse
from pathlib import Path

from template_builder_common import build_templates_from_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "resource" / "config" / "pacman_cookie_01_crops.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pacman_cookie_01 templates from full source screenshots.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    build_templates_from_config(ROOT, args.config)


if __name__ == "__main__":
    main()
