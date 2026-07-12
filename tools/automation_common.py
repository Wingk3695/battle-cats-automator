from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from maa.pipeline import JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker

from maa_common import CAPTURE_DIR, RESOURCE_DIR, make_adb_controller


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    file_name: str
    task_id: str
    threshold: float = 0.8
    roi: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def path(self) -> Path:
        return RESOURCE_DIR / "image" / self.task_id / self.file_name

    @property
    def resource_name(self) -> str:
        return f"{self.task_id}/{self.file_name}"


class MaaTemplateSession:
    def __init__(self, templates: dict[str, TemplateSpec]):
        self.templates = templates
        self.controller = make_adb_controller()
        self.resource = Resource()
        self.resource.post_bundle(str(RESOURCE_DIR)).wait()
        self.tasker = Tasker()
        self.tasker.bind(self.resource, self.controller)
        if not self.tasker.inited:
            raise RuntimeError("Failed to initialize MaaFramework tasker.")

    def screenshot(self) -> np.ndarray:
        image_result = self.controller.post_screencap().wait().get()
        return image_result.get() if hasattr(image_result, "get") else image_result

    def recognize(self, key: str, image: np.ndarray | None = None, log_miss: bool = True, quiet: bool = False):
        spec = self.templates[key]
        if image is None:
            image = self.screenshot()

        job = self.tasker.post_recognition(
            "TemplateMatch",
            JTemplateMatch(
                template=[spec.resource_name],
                threshold=[spec.threshold],
                roi=spec.roi,
            ),
            image,
        ).wait()
        detail = recognition_detail_from_result(job.get())
        hit = bool(detail and detail.hit)
        score = best_score(detail)
        if quiet:
            return detail if hit else None
        if not hit and not log_miss:
            return None
        if score is None:
            print(f"[detect] {key}: hit={hit}", flush=True)
        else:
            print(f"[detect] {key}: hit={hit} score={score:.3f}", flush=True)
        return detail if hit else None

    def detect(
        self,
        key: str,
        image: np.ndarray | None = None,
        log_miss: bool = True,
        quiet: bool = False,
    ) -> bool:
        return self.recognize(key, image, log_miss, quiet) is not None

    def click_template(self, key: str, image: np.ndarray | None = None) -> None:
        detail = self.recognize(key, image)
        if detail is None or detail.box is None:
            raise RuntimeError(f"Cannot click template because it was not detected: {key}")

        x, y = rect_center(detail.box)
        print(f"[click] {key} at ({x}, {y})", flush=True)
        self.controller.post_click(x, y).wait()

    def save_debug_screenshot(self, image: np.ndarray, name: str) -> Path:
        debug_dir = CAPTURE_DIR / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        output = debug_dir / name
        Image.fromarray(image[:, :, ::-1]).save(output)
        return output


def require_templates(templates: dict[str, TemplateSpec]) -> None:
    missing = [spec.path for spec in templates.values() if not spec.path.exists()]
    if missing:
        lines = ["Missing templates:"]
        lines.extend(f"  - {path}" for path in missing)
        raise FileNotFoundError("\n".join(lines))


def recognition_detail_from_result(result):
    if isinstance(result, int):
        return None

    nodes = getattr(result, "nodes", None)
    if not nodes:
        return None

    for node in nodes:
        detail = getattr(node, "recognition", None)
        if detail is not None:
            return detail
    return None


def best_score(detail) -> float | None:
    if detail is None:
        return None
    best = getattr(detail, "best_result", None)
    if best is not None and hasattr(best, "score"):
        return float(best.score)

    all_results = getattr(detail, "all_results", None) or []
    scores = [float(item.score) for item in all_results if hasattr(item, "score")]
    return max(scores) if scores else None


def rect_center(rect) -> tuple[int, int]:
    return int(rect.x + rect.w / 2), int(rect.y + rect.h / 2)
