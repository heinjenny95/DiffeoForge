"""Freeze the originally declared sine momenta once, with reference NumPy 1.24.4."""
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    if np.__version__ != "1.24.4":
        raise RuntimeError("Generate only in the frozen reference environment")
    momenta = np.sin(np.arange(81).reshape(27, 3) + 0.5) * 0.002
    root = Path(__file__).resolve().parents[1] / "reference/public-engine-pair-v1"
    root.mkdir(exist_ok=True)
    path = root / "momenta.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(momenta.tolist(), stream, indent=2, allow_nan=False)
        stream.write("\n")
    print("JSON:", hashlib.sha256(path.read_bytes()).hexdigest())
    print("float64:", hashlib.sha256(momenta.tobytes()).hexdigest())


if __name__ == "__main__":
    main()
