from __future__ import annotations

import argparse
import enum
import time

import numpy as np

from automation_common import MaaTemplateSession, TemplateSpec, require_templates
from maa_common import CAPTURE_DIR


TASK_ID = "event_gacha"


class State(enum.Enum):
    UNKNOWN = "UNKNOWN"
    GACHA_READY = "GACHA_READY"
    RESULT_LOOP = "RESULT_LOOP"
    FINISHED = "FINISHED"


TEMPLATES = {
    "gacha_ready_marker": TemplateSpec("gacha_ready_marker", "gacha_ready_marker.png", TASK_ID, threshold=0.8),
    "ten_pull_button": TemplateSpec("ten_pull_button", "ten_pull_button.png", TASK_ID, threshold=0.8),
    "result_ok_button": TemplateSpec("result_ok_button", "result_ok_button.png", TASK_ID, threshold=0.8),
}


class EventGachaRunner:
    def __init__(
        self,
        runs: int,
        poll_interval: float,
        run_timeout: float,
        no_match_timeout: float,
        click_wait: float,
        skip_animation_delay: float,
        initial_animation_wait: float,
        post_ok_ready_wait: float,
        skip_click: tuple[int, int],
    ):
        self.runs = runs
        self.poll_interval = poll_interval
        self.run_timeout = run_timeout
        self.no_match_timeout = no_match_timeout
        self.click_wait = click_wait
        self.skip_animation_delay = skip_animation_delay
        self.initial_animation_wait = initial_animation_wait
        self.post_ok_ready_wait = post_ok_ready_wait
        self.skip_click = skip_click
        self.completed_runs = 0
        self.session = MaaTemplateSession(TEMPLATES)

    def run(self) -> None:
        state = State.UNKNOWN
        run_started: float | None = None
        last_match = time.monotonic()
        next_skip_at: float | None = None
        ready_grace_until: float | None = None

        print(f"start event_gacha target_runs={self.runs}", flush=True)
        while state != State.FINISHED:
            image = self.session.screenshot()

            if state == State.UNKNOWN:
                if not self.detect_gacha_ready(image):
                    self.fail_with_debug(image, "UNKNOWN: gacha ready page was not detected.")
                self.transition(state, State.GACHA_READY)
                state = State.GACHA_READY
                continue

            if state == State.GACHA_READY:
                print("[GACHA_READY] click ten-pull", flush=True)
                self.session.click_template("ten_pull_button", image)
                self.transition(state, State.RESULT_LOOP)
                state = State.RESULT_LOOP
                run_started = time.monotonic()
                last_match = run_started
                next_skip_at = self.next_skip_time(self.initial_animation_wait)
                ready_grace_until = None
                time.sleep(self.click_wait)
                continue

            if state == State.RESULT_LOOP:
                now = time.monotonic()
                if run_started is not None and now - run_started > self.run_timeout:
                    self.fail_with_debug(image, "RESULT_LOOP: single run timed out.")

                if self.session.detect("result_ok_button", image, log_miss=False):
                    print("[RESULT_LOOP] click OK", flush=True)
                    self.session.click_template("result_ok_button", image)
                    last_match = time.monotonic()
                    next_skip_at = None
                    ready_grace_until = last_match + self.post_ok_ready_wait
                    time.sleep(self.click_wait)
                    continue

                if self.detect_gacha_ready(image, log=False):
                    self.completed_runs += 1
                    print(f"[RUN] completed {self.completed_runs}/{self.runs}", flush=True)
                    last_match = time.monotonic()
                    if self.completed_runs >= self.runs:
                        self.transition(state, State.FINISHED)
                        state = State.FINISHED
                    else:
                        self.transition(state, State.GACHA_READY)
                        state = State.GACHA_READY
                    next_skip_at = None
                    ready_grace_until = None
                    continue

                if ready_grace_until is not None:
                    if now < ready_grace_until:
                        time.sleep(self.poll_interval)
                        continue
                    next_skip_at = self.next_skip_time(self.skip_animation_delay)
                    ready_grace_until = None
                    continue

                if next_skip_at is not None and now >= next_skip_at:
                    self.skip_animation_once()
                    next_skip_at = None
                    last_match = time.monotonic()
                    time.sleep(self.click_wait)
                    continue

                if now - last_match > self.no_match_timeout:
                    self.fail_with_debug(image, "RESULT_LOOP: no OK button or gacha ready page detected.")

                time.sleep(self.poll_interval)

    def detect_gacha_ready(self, image: np.ndarray, log: bool = True) -> bool:
        marker_hit = self.session.detect("gacha_ready_marker", image, log_miss=log, quiet=not log)
        button_hit = self.session.detect("ten_pull_button", image, log_miss=log, quiet=not log)
        if log:
            print(f"[UNKNOWN] gacha_ready_marker={marker_hit} ten_pull_button={button_hit}", flush=True)
        return marker_hit and button_hit

    def fail_with_debug(self, image: np.ndarray, message: str) -> None:
        output = self.session.save_debug_screenshot(image, f"event_gacha_error_{int(time.time())}.png")
        print(f"[ERROR] {message}", flush=True)
        print(f"[ERROR] saved debug screenshot: {output}", flush=True)
        raise RuntimeError(message)

    def next_skip_time(self, delay: float) -> float | None:
        if delay < 0:
            return None
        return time.monotonic() + delay

    def skip_animation_once(self) -> None:
        x, y = self.skip_click
        print(f"[RESULT_LOOP] skip animation click at ({x}, {y})", flush=True)
        self.session.controller.post_click(x, y).wait()

    def transition(self, old: State, new: State) -> None:
        print(f"[{old.value}] -> [{new.value}]", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run event gacha ten-pull automation.")
    parser.add_argument("--runs", type=int, required=True, help="Number of completed ten-pull runs.")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--run-timeout", type=float, default=180.0)
    parser.add_argument("--no-match-timeout", type=float, default=30.0)
    parser.add_argument("--click-wait", type=float, default=0.8)
    parser.add_argument("--skip-animation-delay", type=float, default=1.0)
    parser.add_argument("--initial-animation-wait", type=float, default=2.0)
    parser.add_argument("--post-ok-ready-wait", type=float, default=1.2)
    parser.add_argument("--skip-click-x", type=int, default=792)
    parser.add_argument("--skip-click-y", type=int, default=360)
    args = parser.parse_args()

    if args.runs < 1:
        raise ValueError("--runs must be at least 1.")

    CAPTURE_DIR.mkdir(exist_ok=True)
    require_templates(TEMPLATES)
    EventGachaRunner(
        runs=args.runs,
        poll_interval=args.poll_interval,
        run_timeout=args.run_timeout,
        no_match_timeout=args.no_match_timeout,
        click_wait=args.click_wait,
        skip_animation_delay=args.skip_animation_delay,
        initial_animation_wait=args.initial_animation_wait,
        post_ok_ready_wait=args.post_ok_ready_wait,
        skip_click=(args.skip_click_x, args.skip_click_y),
    ).run()


if __name__ == "__main__":
    main()
