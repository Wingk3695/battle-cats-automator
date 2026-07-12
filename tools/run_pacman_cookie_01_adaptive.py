from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw
from maa.pipeline import JTemplateMatch

import run_pacman_cookie_01 as base


ADAPTIVE_DIR_NAME = "_adaptive"


def scale_values(min_scale: float, max_scale: float, step: float) -> list[float]:
    if min_scale <= 0 or max_scale < min_scale or step <= 0:
        raise ValueError("Require 0 < --min-scale <= --max-scale and --scale-step > 0.")
    count = int(round((max_scale - min_scale) / step))
    values = [min_scale + index * step for index in range(count + 1)]
    if not values or values[-1] < max_scale - 1e-6:
        values.append(max_scale)
    values.append(1.0)
    return sorted({round(value, 4) for value in values if min_scale <= value <= max_scale})


def build_scaled_templates(scales: list[float], keys: tuple[str, ...]) -> dict[str, list[str]]:
    output_dir = base.TEMPLATE_DIR / ADAPTIVE_DIR_NAME
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    resources: dict[str, list[str]] = {}
    for key in keys:
        spec = base.TEMPLATES[key]
        with Image.open(spec.path) as source:
            source = source.convert("RGB")
            names: list[str] = []
            for index, scale in enumerate(scales):
                width = max(8, round(source.width * scale))
                height = max(8, round(source.height * scale))
                image = source if (width, height) == source.size else source.resize(
                    (width, height), Image.Resampling.LANCZOS
                )
                file_name = f"{key}_{index:02d}_{scale:.4f}.png"
                image.save(output_dir / file_name)
                names.append(f"{base.STAGE_ID}/{ADAPTIVE_DIR_NAME}/{file_name}")
            resources[key] = names
    return resources


class AdaptiveBattleRunner(base.BattleRunner):
    def __init__(self, *, adaptive_resources: dict[str, list[str]], **kwargs):
        self.adaptive_resources = adaptive_resources
        super().__init__(**kwargs)

    def recognize(self, key: str, image=None, log_miss: bool = True):
        spec = base.TEMPLATES[key]
        if image is None:
            image = self.screenshot()
        templates = self.adaptive_resources[key]
        job = self.tasker.post_recognition(
            "TemplateMatch",
            JTemplateMatch(
                template=templates,
                threshold=[spec.threshold] * len(templates),
                roi=spec.roi,
            ),
            image,
        ).wait()
        detail = base.recognition_detail_from_result(job.get())
        hit = bool(detail and detail.hit)
        score = base.best_score(detail)
        if not hit and not log_miss:
            return None

        scale_text = ""
        if hit and detail.box is not None:
            with Image.open(spec.path) as template:
                scale_x = detail.box.w / template.width
                scale_y = detail.box.h / template.height
            scale_text = (
                f" scale=({scale_x:.3f},{scale_y:.3f})"
                f" box=({detail.box.x},{detail.box.y},{detail.box.w},{detail.box.h})"
            )
        if score is None:
            self.log(f"[detect-adaptive] {key}: hit={hit}{scale_text}")
        else:
            self.log(f"[detect-adaptive] {key}: hit={hit} score={score:.3f}{scale_text}")
        return detail if hit else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run pacman_cookie_01 with bounded multi-scale template matching."
    )
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--loading-timeout", type=float, default=45.0)
    parser.add_argument("--battle-timeout", type=float, default=240.0)
    parser.add_argument("--result-timeout", type=float, default=60.0)
    parser.add_argument("--click-interval", type=float, default=2.0)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--start-only", action="store_true")
    parser.add_argument(
        "--calibrate-only",
        action="store_true",
        help="Detect the stage marker and start button once, save a preview, and do not click.",
    )
    parser.add_argument("--min-scale", type=float, default=0.80)
    parser.add_argument("--max-scale", type=float, default=1.25)
    parser.add_argument("--scale-step", type=float, default=0.05)
    args = parser.parse_args()
    if args.runs < 1:
        raise ValueError("--runs must be at least 1.")

    base.CAPTURE_DIR.mkdir(exist_ok=True)
    limited_mode = args.start_only or args.calibrate_only
    required_keys = ("stage_ready_marker", "start_button") if limited_mode else tuple(base.TEMPLATES)
    base.require_assets(required_keys=required_keys, require_slot=not limited_mode)
    scales = scale_values(args.min_scale, args.max_scale, args.scale_step)
    print(f"[adaptive] template scales: {', '.join(f'{value:.2f}' for value in scales)}", flush=True)
    resources = build_scaled_templates(scales, required_keys)
    runner = AdaptiveBattleRunner(
        adaptive_resources=resources,
        poll_interval=args.poll_interval,
        loading_timeout=args.loading_timeout,
        battle_timeout=args.battle_timeout,
        result_timeout=args.result_timeout,
        click_interval=args.click_interval,
        start_only=limited_mode,
    )
    if args.calibrate_only:
        image = runner.screenshot()
        preview = Image.fromarray(image[:, :, ::-1])
        draw = ImageDraw.Draw(preview)
        colors = {"stage_ready_marker": "lime", "start_button": "red"}
        hits = 0
        detected_centers: dict[str, tuple[float, float]] = {}
        for key in required_keys:
            detail = runner.recognize(key, image)
            if detail is None or detail.box is None:
                continue
            hits += 1
            box = detail.box
            detected_centers[key] = (box.x + box.w / 2, box.y + box.h / 2)
            draw.rectangle((box.x, box.y, box.x + box.w, box.y + box.h), outline=colors[key], width=4)
            draw.text((box.x, max(0, box.y - 14)), key, fill=colors[key])
        output = base.CAPTURE_DIR / "pacman_cookie_01_adaptive_calibration.png"
        preview.save(output)
        validation = validate_center_mapping(detected_centers, runner.screen_size)
        if hits == len(required_keys) and validation["accepted"]:
            base.CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
            with base.CALIBRATION_PATH.open("w", encoding="utf-8") as file:
                json.dump(validation, file, ensure_ascii=False, indent=2)
                file.write("\n")
            print(f"[adaptive] coordinate calibration saved: {base.CALIBRATION_PATH}", flush=True)
        elif hits == len(required_keys):
            print("[adaptive] center mapping rejected: residual is too large; calibration not saved", flush=True)
        print(f"[adaptive] calibration hits={hits}/{len(required_keys)} preview={output}", flush=True)
        return
    runner.run_many(args.runs)


def validate_center_mapping(
    detected_centers: dict[str, tuple[float, float]],
    device_size: tuple[int, int] | None,
) -> dict:
    if device_size is None:
        raise RuntimeError("Screenshot size is unavailable during calibration.")
    with (base.RESOURCE_DIR / "config" / "pacman_cookie_01_crops.json").open(
        "r", encoding="utf-8"
    ) as file:
        crop_config = json.load(file)
    reference_width, reference_height = crop_config["target_size"]
    device_width, device_height = device_size
    scale = device_height / reference_height
    residuals = {}
    max_error = 0.0
    for key, actual in detected_centers.items():
        x, y, width, height = crop_config["templates"][key]["bbox"]
        source_center = (x + width / 2, y + height / 2)
        predicted = (
            device_width / 2 + (source_center[0] - reference_width / 2) * scale,
            device_height / 2 + (source_center[1] - reference_height / 2) * scale,
        )
        error = (actual[0] - predicted[0], actual[1] - predicted[1])
        max_error = max(max_error, abs(error[0]), abs(error[1]))
        residuals[key] = {
            "predicted_center": [round(predicted[0], 2), round(predicted[1], 2)],
            "detected_center": [round(actual[0], 2), round(actual[1], 2)],
            "error": [round(error[0], 2), round(error[1], 2)],
        }
        print(
            f"[adaptive] center-map {key}: predicted=({predicted[0]:.1f},{predicted[1]:.1f}) "
            f"detected=({actual[0]:.1f},{actual[1]:.1f}) error=({error[0]:+.1f},{error[1]:+.1f})",
            flush=True,
        )
    tolerance = max(12.0, device_height * 0.03)
    accepted = len(residuals) >= 2 and max_error <= tolerance
    print(
        f"[adaptive] center-map validation: accepted={accepted} "
        f"max_error={max_error:.1f}px tolerance={tolerance:.1f}px",
        flush=True,
    )
    return {
        "mapping": "screen_center_height_scale",
        "reference_size": [reference_width, reference_height],
        "calibrated_device_size": [device_width, device_height],
        "accepted": accepted,
        "max_error_px": round(max_error, 2),
        "tolerance_px": round(tolerance, 2),
        "validation": residuals,
    }


if __name__ == "__main__":
    main()
