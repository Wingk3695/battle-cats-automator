from __future__ import annotations

from pathlib import Path

from maa.resource import Resource
from maa.tasker import Tasker

from maa_common import RESOURCE_DIR, make_adb_controller


ENTRY = "ClickTargetButton"
TEMPLATE = RESOURCE_DIR / "image" / "target_button.png"


def main() -> None:
    if not TEMPLATE.exists():
        raise FileNotFoundError(
            f"Missing template image: {TEMPLATE}. Crop it from captures/latest.png first."
        )

    controller = make_adb_controller()

    resource = Resource()
    resource.post_bundle(str(RESOURCE_DIR)).wait()

    tasker = Tasker()
    tasker.bind(resource, controller)
    if not tasker.inited:
        raise RuntimeError("Failed to initialize MaaFramework tasker.")

    detail = tasker.post_task(ENTRY).wait().get()
    print(detail)


if __name__ == "__main__":
    main()
