from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def build_templates_from_config(root: Path, config_path: Path) -> None:
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    target_size = tuple(config["target_size"])
    images = {}
    previews = {}
    draws = {}
    font = ImageFont.load_default()

    for source_name, source_config in config["sources"].items():
        source_path = root / source_config["source"]
        imported_path = Path(source_config["import"])
        if imported_path.exists():
            source_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(imported_path, source_path)
        elif not source_path.exists():
            raise FileNotFoundError(f"Source screenshot not found: {source_path}")

        image = Image.open(source_path).convert("RGB")
        if image.size != target_size:
            image = image.resize(target_size, Image.Resampling.LANCZOS)

        normalized_path = root / source_config["normalized_source"]
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(normalized_path)
        print(f"{source_name}.normalized_source: {normalized_path}")

        images[source_name] = image
        previews[source_name] = image.copy()
        draws[source_name] = ImageDraw.Draw(previews[source_name])

    colors = ["red", "lime", "cyan", "yellow", "magenta", "orange"]
    for index, (name, item) in enumerate(config["templates"].items()):
        source_name = item["source"]
        image = images[source_name]
        draw = draws[source_name]
        x, y, width, height = item["bbox"]
        output_path = root / item["output"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.crop((x, y, x + width, y + height)).save(output_path)

        color = colors[index % len(colors)]
        draw.rectangle((x, y, x + width, y + height), outline=color, width=4)
        draw.text((x, max(0, y - 16)), name, fill=color, font=font)
        print(f"{name}: source={source_name} bbox=({x}, {y}, {width}, {height}) -> {output_path}")

    for source_name, preview in previews.items():
        preview_path = root / config["sources"][source_name]["preview"]
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview.save(preview_path)
        print(f"{source_name}.preview: {preview_path}")
