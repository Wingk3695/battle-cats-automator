from __future__ import annotations

import argparse
import time

from maa_common import make_adb_controller


DEFAULT_CLICK = (1240, 600)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast fixed-point clicker for event gacha.")
    parser.add_argument("--clicks", type=int, required=True, help="Number of clicks to send.")
    parser.add_argument("--interval", type=float, default=0.25, help="Delay between clicks in seconds.")
    parser.add_argument("--x", type=int, default=DEFAULT_CLICK[0])
    parser.add_argument("--y", type=int, default=DEFAULT_CLICK[1])
    args = parser.parse_args()

    if args.clicks < 1:
        raise ValueError("--clicks must be at least 1.")
    if args.interval < 0:
        raise ValueError("--interval must be non-negative.")

    controller = make_adb_controller()
    print(f"event_gacha fast click: point=({args.x}, {args.y}) clicks={args.clicks} interval={args.interval}", flush=True)

    for index in range(1, args.clicks + 1):
        controller.post_click(args.x, args.y).wait()
        print(f"[CLICK] {index}/{args.clicks}", flush=True)
        if index < args.clicks and args.interval:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
