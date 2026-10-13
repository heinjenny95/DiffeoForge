"""Opt-in native frozen-basis worker routing; standalone Python 3.8 compatible.

This module changes resource placement only. The supported native ordered
Pool.map, contribution equations, gradient assembly and optimizer stay intact.
Deploy a protected copy beside a guarded native entry point; do not install it
globally into a shared Deformetrica environment.
"""
import json
import os
from pathlib import Path

_DEVICES_ENV = "DIFFEOFORGE_REFERENCE_WORKER_GPUS"
_RECEIPTS_ENV = "DIFFEOFORGE_REFERENCE_WORKER_RECEIPTS"
_CACHE_ENV = "DIFFEOFORGE_REFERENCE_KEOPS_CACHE"
_INSTALLED = False


def validate_devices(devices):
    devices = tuple(devices)
    if not 2 <= len(devices) <= 8:
        raise ValueError("Declare between two and eight distinct worker GPUs.")
    if any(type(x) is not int or x < 0 for x in devices) or len(set(devices)) != len(devices):
        raise ValueError("Worker GPU indices must be unique nonnegative integers.")
    return devices


def validate_model(model, devices, double_type, kernel_mode):
    if (model.name != "DeterministicAtlas" or model.number_of_processes != len(devices)
            or not model.freeze_template or not model.freeze_control_points
            or model.freeze_momenta or model.tensor_scalar_type != double_type
            or model.gpu_mode != kernel_mode):
        raise RuntimeError("Parallel routing requires a Float64 frozen-basis deterministic atlas.")


def validate_cache_topology(cache_directory, visible_count):
    """Legacy compiled GPU property tables are bound to visible-device count."""
    path = Path(cache_directory) / "device-topology.json"
    if not path.is_file():
        raise RuntimeError("A prospectively initialized multi-GPU cache is required.")
    record = json.loads(path.read_text())
    if record.get("visible_device_count") != visible_count:
        raise RuntimeError("Compiled cache GPU topology differs from the visible devices.")


class DeviceReduction:
    """Route the same KeOps reduction, including its native backward, to one GPU."""

    def __init__(self, operation, device):
        self.operation = operation
        self.device = device

    def __call__(self, *args, **kwargs):
        kwargs["backend"] = "GPU_1D"
        # Native kernel-mode tensors are hosted on CPU and pass device_id=-1.
        # Override that resource hint; it otherwise defaults every worker to GPU0.
        kwargs["device_id"] = self.device
        return self.operation(*args, **kwargs)


def route_kernels(kernels, device):
    count = 0
    seen = set()
    for kernel in kernels:
        if id(kernel) in seen:
            continue
        seen.add(id(kernel))
        for name in ("gaussian_convolve", "point_cloud_convolve", "varifold_convolve",
                     "gaussian_convolve_gradient_x"):
            operations = getattr(kernel, name, None)
            if not isinstance(operations, list) or not operations:
                raise RuntimeError("Unsupported native KeOps reduction layout.")
            if any(isinstance(op, DeviceReduction) for op in operations):
                raise RuntimeError("Duplicate worker kernel routing.")
            setattr(kernel, name, [DeviceReduction(op, device) for op in operations])
            count += len(operations)
    return count


def _identity():
    p = Path("/proc") / str(os.getpid())
    stat = (p / "stat").read_text().rsplit(")", 1)[1].split()
    argv = [x.decode() for x in (p / "cmdline").read_bytes().split(b"\0") if x]
    return dict(pid=os.getpid(), argv=argv,
                cwd=os.readlink(str(p / "cwd")), start_ticks=int(stat[19]),
                boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip())


def _receipt(name, value):
    directory = os.environ.get(_RECEIPTS_ENV)
    if directory:
        path = Path(directory) / name
        with path.open("x") as f:
            json.dump(value, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())


def initialize_worker(*args):
    """Spawn initializer used by the unchanged native process-pool setup."""
    try:
        import pykeops
        import torch
        from deformetrica.core.models import abstract_statistical_model as native

        # Spawn imports the original native module afresh. Avoid initializer
        # recursion if a deployment accidentally chose an unsafe start method.
        original = native._initializer
        if original is initialize_worker:
            raise RuntimeError("Native worker routing requires spawn, not fork.")
        devices = validate_devices(json.loads(os.environ[_DEVICES_ENV]))
        pykeops.set_bin_folder(os.environ[_CACHE_ENV])
        import sys
        sys.path.insert(0, pykeops.bin_folder)
        original(*args)
        rank = int(torch.multiprocessing.current_process().name.rsplit("-", 1)[1])
        if not 0 <= rank < len(devices):
            raise RuntimeError("Worker replacement/recycling is forbidden; stop the job.")
        device = devices[rank]
        torch.cuda.set_device(device)
        data = native.process_initial_data
        if (len(data) != 11 or not data[3] or not data[4] or data[5]
                or data[9] != torch.DoubleTensor):
            raise RuntimeError("Unexpected native frozen-basis worker context.")
        exponential, sobolev = data[6], data[7]
        kernels = [exponential.kernel, exponential.shoot_kernel, sobolev] + list(data[1].kernels)
        routed = route_kernels(kernels, device)
        _receipt(f"worker-{rank}.json", dict(process=_identity(), rank=rank, device=device,
            device_name=torch.cuda.get_device_name(device), routed_reductions=routed,
            tensor_precision="float64", native_equations_unchanged=True))
    except BaseException as error:
        _receipt(f"worker-failed-{os.getpid()}.json",
                 dict(error=repr(error), process=_identity()))
        raise


def install(devices, receipt_directory, cache_directory):
    """Explicitly enable routing for one qualified native frozen-basis process."""
    global _INSTALLED
    import torch
    from deformetrica.core import GpuMode
    from deformetrica.core.models import abstract_statistical_model as native

    if _INSTALLED:
        raise RuntimeError("Native worker routing is already installed.")
    devices = validate_devices(devices)
    if not torch.cuda.is_available() or max(devices) >= torch.cuda.device_count():
        raise RuntimeError("The declared worker GPUs are unavailable.")
    validate_cache_topology(cache_directory, torch.cuda.device_count())
    os.environ[_DEVICES_ENV] = json.dumps(devices)
    os.environ[_RECEIPTS_ENV] = str(receipt_directory)
    os.environ[_CACHE_ENV] = str(cache_directory)
    original_setup = native.AbstractStatisticalModel._setup_multiprocess_pool

    def setup(self, initargs=()):
        validate_model(self, devices, torch.DoubleTensor, GpuMode.KERNEL)
        if torch.multiprocessing.get_start_method() != "spawn":
            raise RuntimeError("Native multi-GPU execution requires spawn.")
        return original_setup(self, initargs=initargs)

    native._initializer = initialize_worker
    native.AbstractStatisticalModel._setup_multiprocess_pool = setup
    _INSTALLED = True
    return dict(devices=list(devices), workers=len(devices), native_ordered_pool_map=True,
                native_optimizer_unchanged=True, native_gradient_equations_unchanged=True)
