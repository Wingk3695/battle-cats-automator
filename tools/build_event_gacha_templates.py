from __future__ import annotations

import argparse
from pathlib import Path

from maa_common import ROOT
from template_builder_common import build_templates_from_config


CONFIG_PATH = ROOT / "resource" / "config" / "event_gacha_crops.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build event_gacha templates from full source screenshots.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    build_templates_from_config(ROOT, args.config)


if __name__ == "__main__":
    main()
