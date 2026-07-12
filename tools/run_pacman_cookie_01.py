from __future__ import annotations

import argparse
import enum
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from maa.pipeline import JTemplateMatch
from maa.resource import Resource
from maa.tasker import Tasker

from maa_common import CAPTURE_DIR, RESOURCE_DIR, make_adb_controller


STAGE_ID = "pacman_cookie_01"
TEMPLATE_DIR = RESOURCE_DIR / "image" / STAGE_ID
CONFIG_PATH = RESOURCE_DIR / "config" / f"{STAGE_ID}.json"
CALIBRATION_PATH = Path(__file__).resolve().parents[1] / ".maa" / f"{STAGE_ID}_calibration.json"


class State(enum.Enum):
    UNKNOWN = "UNKNOWN"
    STAGE_READY = "STAGE_READY"
    BATTLE_LOADING = "BATTLE_LOADING"
    BATTLE = "BATTLE"
    WAIT_FOR_VICTORY = "WAIT_FOR_VICTORY"
    RESULT = "RESULT"
    FINAL_RESULT = "FINAL_RESULT"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    file_name: str
    threshold: float = 0.8
    roi: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def path(self) -> Path:
        return TEMPLATE_DIR / self.file_name

    @property
    def resource_name(self) -> str:
        return f"{STAGE_ID}/{self.file_name}"


TEMPLATES = {
    "stage_ready_marker": TemplateSpec("stage_ready_marker", "stage_ready_marker.png", threshold=0.8),
    "start_button": TemplateSpec("start_button", "start_button.png", threshold=0.8),
    "battle_ui_marker": TemplateSpec("battle_ui_marker", "battle_ui_marker.png", threshold=0.8),
    "victory": TemplateSpec("victory", "victory.png", threshold=0.8),
    "result_map_button": TemplateSpec("result_map_button", "result_map_button.png", threshold=0.8),
    "leadership_restore_dialog": TemplateSpec(
        "leadership_restore_dialog",
        "leadership_restore_dialog.png",
        threshold=0.8,
    ),
    "ex_stage_prompt": TemplateSpec("ex_stage_prompt", "ex_stage_prompt.png", threshold=0.8),
}

class BattleRunner:
    def __init__(
        self,
        poll_interval: float,
        loading_timeout: float,
        battle_timeout: float,
        result_timeout: float,
        click_interval: float,
        start_only: bool,
    ):
        self.poll_interval = poll_interval
        self.loading_timeout = loading_timeout
        self.battle_timeout = battle_timeout
        self.result_timeout = result_timeout
        self.click_interval = click_interval
        self.start_only = start_only
        config = {} if start_only else load_run_config()
        self.coordinate_calibration = load_coordinate_calibration()
        self.screen_size: tuple[int, int] | None = None
        self.slot5 = None if start_only else load_point(config, "slot5")
        self.result_safe_click = None if start_only else load_point(config, "result_safe_click")
        self.leadership_restore_yes = None if start_only else load_point(config, "leadership_restore_yes")
        self.ex_stage_yes = None if start_only else load_point(config, "ex_stage_yes")
        self.controller = make_adb_controller()
        self.resource = Resource()
        self.resource.post_bundle(str(RESOURCE_DIR)).wait()
        self.tasker = Tasker()
        self.tasker.bind(self.resource, self.controller)
        if not self.tasker.inited:
            raise RuntimeError("Failed to initialize MaaFramework tasker.")

    def run(self) -> None:
        state = State.UNKNOWN
        state_started = time.monotonic()
        self.log("start pacman_cookie_01")

        while state != State.FINISHED:
            image = self.screenshot()
            interrupted_state = self.handle_interrupts(image, state)
            if interrupted_state is not None:
                if interrupted_state != state:
                    self.transition(state, interrupted_state)
                    state = interrupted_state
                    state_started = time.monotonic()
                time.sleep(self.poll_interval)
                continue

            next_state = self.step_state(state, image, state_started)
            if next_state != state:
                self.transition(state, next_state)
                state = next_state
                state_started = time.monotonic()

            if state != State.FINISHED:
                time.sleep(self.poll_interval)

    def run_many(self, runs: int) -> None:
        for index in range(1, runs + 1):
            self.log(f"[RUN {index}/{runs}] start")
            self.run()
            self.log(f"[RUN {index}/{runs}] finished")

    def step_state(self, state: State, image: np.ndarray, state_started: float) -> State:
        if state == State.UNKNOWN:
            if not self.detect_stage_ready(image):
                raise RuntimeError(
                    "UNKNOWN: stage ready marker and start button were not both detected. "
                    "Put the phone on the target sortie page."
                )
            return State.STAGE_READY

        if state == State.STAGE_READY:
            self.log("[STAGE_READY] click start")
            self.click_template("start_button", image)
            return State.BATTLE_LOADING

        if state == State.BATTLE_LOADING:
            if self.start_only:
                self.log("[BATTLE_LOADING] start-only mode: stop after entering battle")
                return State.FINISHED
            if self.detect("battle_ui_marker", image):
                return State.BATTLE
            if time.monotonic() - state_started > 2.0 and self.detect_stage_ready(image):
                self.log("[BATTLE_LOADING] still on stage page; retry start")
                return State.UNKNOWN
            if time.monotonic() - state_started > self.loading_timeout:
                raise TimeoutError("BATTLE_LOADING: battle UI marker was not detected before timeout.")
            return state

        if state == State.BATTLE:
            self.click_slot5_once()
            return State.WAIT_FOR_VICTORY

        if state == State.WAIT_FOR_VICTORY:
            if self.detect("victory", image):
                self.log("[WAIT_FOR_VICTORY] victory detected")
                return State.RESULT
            if time.monotonic() - state_started > self.battle_timeout:
                raise TimeoutError("WAIT_FOR_VICTORY: victory was not detected before timeout.")
            return state

        if state == State.RESULT:
            if self.detect("result_map_button", image):
                return State.FINAL_RESULT
            if time.monotonic() - state_started > self.result_timeout:
                raise TimeoutError("RESULT: result map button was not detected before timeout.")
            self.close_result_overlay_once()
            return state

        if state == State.FINAL_RESULT:
            self.log("[FINAL_RESULT] click map button")
            self.click_template("result_map_button", image)
            self.confirm_back_to_stage_ready()
            return State.FINISHED

        return state

    def click_slot5_once(self) -> None:
        if self.slot5 is None:
            raise RuntimeError("slot5 is not configured.")

        x, y = self.map_point(self.slot5)
        self.log("[BATTLE] click slot 5")
        self.controller.post_click(x, y).wait()

    def close_result_overlay_once(self) -> None:
        if self.result_safe_click is None:
            raise RuntimeError("result_safe_click is not configured.")

        x, y = self.map_point(self.result_safe_click)
        self.log("[RESULT] close overlay attempt")
        self.controller.post_click(x, y).wait()

    def confirm_back_to_stage_ready(self) -> None:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            image = self.screenshot()
            interrupted_state = self.handle_interrupts(image, State.FINAL_RESULT)
            if interrupted_state is not None:
                time.sleep(self.poll_interval)
                continue
            if self.detect_stage_ready(image):
                self.log("[FINISHED] returned to stage ready")
                return
            time.sleep(self.poll_interval)
        raise TimeoutError("FINISHED: stage ready page was not detected after clicking map button.")

    def handle_interrupts(self, image: np.ndarray, state: State) -> State | None:
        if not self.start_only and self.detect("leadership_restore_dialog", image, log_miss=False):
            return self.resolve_leadership_restore()

        if not self.start_only and self.detect("ex_stage_prompt", image, log_miss=False):
            return self.resolve_ex_stage_prompt()

        return None

    def resolve_leadership_restore(self) -> State:
        if self.leadership_restore_yes is None:
            raise RuntimeError("leadership_restore_yes is not configured.")

        self.log("[INTERRUPT] leadership shortage detected")
        self.log("[INTERRUPT] click restore: yes")
        self.controller.post_click(*self.map_point(self.leadership_restore_yes)).wait()
        self.wait_until_template_gone("leadership_restore_dialog", timeout=8.0)
        self.log("[INTERRUPT] resolved")
        return State.UNKNOWN

    def resolve_ex_stage_prompt(self) -> State:
        if self.ex_stage_yes is None:
            raise RuntimeError("ex_stage_yes is not configured.")

        self.log("[INTERRUPT] ex stage prompt detected")
        self.log("[INTERRUPT] click ex stage: yes")
        self.controller.post_click(*self.map_point(self.ex_stage_yes)).wait()
        self.wait_until_template_gone("ex_stage_prompt", timeout=8.0)
        self.log("[INTERRUPT] resolved")
        return State.BATTLE_LOADING

    def wait_until_template_gone(self, key: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image = self.screenshot()
            if not self.detect(key, image, log_miss=False):
                return
            time.sleep(self.poll_interval)
        raise TimeoutError(f"INTERRUPT: {key} did not disappear before timeout.")

    def detect(self, key: str, image: np.ndarray | None = None, log_miss: bool = True) -> bool:
        return self.recognize(key, image, log_miss) is not None

    def recognize(self, key: str, image: np.ndarray | None = None, log_miss: bool = True):
        spec = TEMPLATES[key]
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
        result = job.get()
        detail = recognition_detail_from_result(result)
        hit = bool(detail and detail.hit)
        score = best_score(detail)
        if not hit and not log_miss:
            return None
        if score is None:
            self.log(f"[detect] {key}: hit={hit}")
        else:
            self.log(f"[detect] {key}: hit={hit} score={score:.3f}")
        return detail if hit else None

    def detect_stage_ready(self, image: np.ndarray | None = None) -> bool:
        marker_hit = self.detect("stage_ready_marker", image)
        button_hit = self.detect("start_button", image)
        self.log(f"[UNKNOWN] stage_ready_marker={marker_hit} start_button={button_hit}")
        return marker_hit and button_hit

    def click_template(self, key: str, image: np.ndarray | None = None) -> None:
        detail = self.recognize(key, image)
        if detail is None or detail.box is None:
            raise RuntimeError(f"Cannot click template because it was not detected: {key}")

        x, y = rect_center(detail.box)
        self.log(f"[click] {key} at ({x}, {y})")
        self.controller.post_click(x, y).wait()

    def screenshot(self) -> np.ndarray:
        image_result = self.controller.post_screencap().wait().get()
        image = image_result.get() if hasattr(image_result, "get") else image_result
        self.screen_size = (int(image.shape[1]), int(image.shape[0]))
        return image

    def map_point(self, point: tuple[int, int]) -> tuple[int, int]:
        calibration = self.coordinate_calibration
        if calibration is None:
            return point
        if self.screen_size is None:
            self.screenshot()
        assert self.screen_size is not None
        reference_width, reference_height = calibration["reference_size"]
        device_width, device_height = self.screen_size
        scale = device_height / reference_height
        x = device_width / 2 + (point[0] - reference_width / 2) * scale
        y = device_height / 2 + (point[1] - reference_height / 2) * scale
        mapped = (
            min(device_width - 1, max(0, round(x))),
            min(device_height - 1, max(0, round(y))),
        )
        self.log(f"[coordinate-map] {point} -> {mapped} scale={scale:.4f}")
        return mapped

    def transition(self, old: State, new: State) -> None:
        self.log(f"[{old.value}] -> [{new.value}]")

    def log(self, message: str) -> None:
        print(message, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fixed pacman_cookie_01 battle loop.")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--loading-timeout", type=float, default=45.0)
    parser.add_argument("--battle-timeout", type=float, default=240.0)
    parser.add_argument("--result-timeout", type=float, default=60.0)
    parser.add_argument("--click-interval", type=float, default=2.0)
    parser.add_argument("--runs", type=int, default=1, help="Number of full battle runs to execute.")
    parser.add_argument(
        "--start-only",
        action="store_true",
        help="Only verify STAGE_READY and click the sortie button. Do not require battle/result templates.",
    )
    args = parser.parse_args()
    if args.runs < 1:
        raise ValueError("--runs must be at least 1.")

    CAPTURE_DIR.mkdir(exist_ok=True)
    required_keys = ("stage_ready_marker", "start_button") if args.start_only else tuple(TEMPLATES)
    require_assets(required_keys=required_keys, require_slot=not args.start_only)
    runner = BattleRunner(
        poll_interval=args.poll_interval,
        loading_timeout=args.loading_timeout,
        battle_timeout=args.battle_timeout,
        result_timeout=args.result_timeout,
        click_interval=args.click_interval,
        start_only=args.start_only,
    )
    runner.run_many(args.runs)


def require_assets(required_keys: tuple[str, ...], require_slot: bool) -> None:
    missing = [TEMPLATES[key].path for key in required_keys if not TEMPLATES[key].path.exists()]
    messages: list[str] = []
    if missing:
        messages.append("Missing templates:")
        messages.extend(f"  - {path}" for path in missing)
        messages.extend(
            [
                "",
                "Crop them from screenshots:",
                "  - stage_ready_marker.png: stable stage-name marker on the sortie page",
                "  - start_button.png: yellow sortie button",
                "  - battle_ui_marker.png: stable battle UI element after loading",
                "  - victory.png: complete-victory text",
                "  - result_map_button.png: top-right result map button",
            ]
        )

    if require_slot and not CONFIG_PATH.exists():
        if messages:
            messages.append("")
        messages.extend(
            [
                f"Missing slot config: {CONFIG_PATH}",
                "Create it after taking a battle screenshot:",
                "{",
                '  "slot5": { "x": 0, "y": 0 }',
                '  "result_safe_click": { "x": 0, "y": 0 },',
                '  "leadership_restore_yes": { "x": 0, "y": 0 },',
                '  "ex_stage_yes": { "x": 0, "y": 0 }',
                "}",
            ]
        )

    if messages:
        raise FileNotFoundError("\n".join(messages))

    if require_slot:
        config = load_run_config()
        load_point(config, "slot5")
        load_point(config, "result_safe_click")
        load_point(config, "leadership_restore_yes")
        load_point(config, "ex_stage_yes")


def load_run_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_coordinate_calibration() -> dict | None:
    if not CALIBRATION_PATH.exists():
        return None
    with CALIBRATION_PATH.open("r", encoding="utf-8") as file:
        calibration = json.load(file)
    if calibration.get("mapping") != "screen_center_height_scale":
        raise ValueError(f"Unsupported coordinate mapping in {CALIBRATION_PATH}.")
    size = calibration.get("reference_size")
    if not isinstance(size, list) or len(size) != 2 or min(size) <= 0:
        raise ValueError(f"Invalid reference_size in {CALIBRATION_PATH}.")
    return calibration


def load_point(config: dict, key: str) -> tuple[int, int]:
    point = config.get(key, {})
    x = int(point.get("x", 0))
    y = int(point.get("y", 0))
    if x <= 0 or y <= 0:
        raise ValueError(f"Invalid {key} coordinates in {CONFIG_PATH}: x and y must be positive.")
    return x, y


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


if __name__ == "__main__":
    main()
