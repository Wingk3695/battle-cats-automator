from __future__ import annotations

import argparse
import statistics
import time

from maa.controller import AdbController
from maa.define import MaaAdbInputMethodEnum, MaaAdbScreencapMethodEnum
from maa.toolkit import Toolkit

from maa_common import find_adb_path, format_screencap_methods, init_toolkit


METHODS = (
    MaaAdbScreencapMethodEnum.EncodeToFileAndPull,
    MaaAdbScreencapMethodEnum.Encode,
    MaaAdbScreencapMethodEnum.RawWithGzip,
    MaaAdbScreencapMethodEnum.RawByNetcat,
    MaaAdbScreencapMethodEnum.MinicapDirect,
    MaaAdbScreencapMethodEnum.MinicapStream,
    MaaAdbScreencapMethodEnum.EmulatorExtras,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark MaaFramework ADB screencap methods.")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument(
        "--all-methods",
        action="store_true",
        help="Try every Maa method, including methods MaaToolkit did not advertise.",
    )
    args = parser.parse_args()
    if args.samples < 1:
        raise ValueError("--samples must be at least 1.")

    init_toolkit()
    adb_path = find_adb_path()
    devices = Toolkit.find_adb_devices(adb_path) if adb_path else Toolkit.find_adb_devices()
    if not devices:
        raise RuntimeError("No ADB device found.")
    device = devices[args.device_index]
    advertised = int(device.screencap_methods)
    print(f"device: {device.name} {device.address}")
    print(f"advertised mask: {advertised} ({format_screencap_methods(advertised)})")
    print(f"samples per method: {args.samples}")

    candidates = METHODS if args.all_methods else tuple(method for method in METHODS if advertised & int(method))
    if not candidates:
        raise RuntimeError("MaaToolkit did not advertise any screencap method; retry with --all-methods.")

    results: list[tuple[float, str]] = []
    for method in candidates:
        outcome = benchmark_method(device, method, args.samples)
        if outcome is not None:
            results.append((outcome, method.name))

    print("\nranking:")
    for rank, (average, name) in enumerate(sorted(results), start=1):
        print(f"  {rank}. {name}: {average * 1000:.1f} ms average")


def benchmark_method(device, method: MaaAdbScreencapMethodEnum, samples: int) -> float | None:
    print(f"\n[{method.name}] value={int(method)}")
    controller = AdbController(
        adb_path=device.adb_path,
        address=device.address,
        screencap_methods=method,
        input_methods=MaaAdbInputMethodEnum.AdbShell,
        config=device.config,
    )
    connected_started = time.perf_counter()
    try:
        controller.post_connection().wait()
    except Exception as error:
        connection_time = time.perf_counter() - connected_started
        print(f"  unavailable after {connection_time:.3f}s: {type(error).__name__}: {error}")
        return None
    connection_time = time.perf_counter() - connected_started
    if not controller.connected:
        print(f"  unavailable (connection test failed after {connection_time:.3f}s)")
        return None

    try:
        controller.post_screencap().wait().get()  # warm up
        timings = []
        size = None
        for _ in range(samples):
            started = time.perf_counter()
            image_result = controller.post_screencap().wait().get()
            image = image_result.get() if hasattr(image_result, "get") else image_result
            timings.append(time.perf_counter() - started)
            size = (int(image.shape[1]), int(image.shape[0]))
    except Exception as error:
        print(f"  failed: {type(error).__name__}: {error}")
        return None

    average = statistics.mean(timings)
    print(f"  connection: {connection_time:.3f}s")
    print(f"  image size: {size[0]}x{size[1]}")
    print(
        f"  screenshot: avg={average * 1000:.1f}ms "
        f"median={statistics.median(timings) * 1000:.1f}ms "
        f"min={min(timings) * 1000:.1f}ms max={max(timings) * 1000:.1f}ms"
    )
    return average


if __name__ == "__main__":
    main()
