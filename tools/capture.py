from __future__ import annotations

from PIL import Image

from maa_common import CAPTURE_DIR, init_toolkit, make_adb_controller


def main() -> None:
    init_toolkit()
    controller = make_adb_controller()
    image_result = controller.post_screencap().wait().get()
    image = image_result.get() if hasattr(image_result, "get") else image_result
    if image.size == 0:
        raise RuntimeError("MaaFramework returned an empty screenshot.")

    CAPTURE_DIR.mkdir(exist_ok=True)
    output = CAPTURE_DIR / "latest.png"
    Image.fromarray(image[:, :, ::-1]).save(output)
    print(f"Saved screenshot: {output}")


if __name__ == "__main__":
    main()
