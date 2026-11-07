"""Run-local Deformetrica 4.3 Shooting grid adapter; native equations are unchanged.

compute_shooting does not pass the XML point count to Geodesic. Explicitly pass
its equivalent concentration, verify the actual grid and export physical t=1.
The adapter is copied into each immutable design, never into the native runtime.
"""

SITECUSTOMIZE = '''"""DiffeoForge verified Shooting grid v2 (native Python 3.8 compatible)."""
import hashlib
import importlib
import json
import os
import xml.etree.ElementTree as ET

try:
    import numpy as np
    module = importlib.import_module("deformetrica.launch.compute_shooting")
    Base = module.Geodesic
    count = int(ET.parse("engine/model.xml").getroot().findtext(
        "./deformation-parameters/number-of-timepoints"))
    if count < 2:
        raise RuntimeError("Invalid declared Shooting grid")

    class VerifiedEndpointGeodesic(Base):
        def __init__(self, *args, **kwargs):
            kwargs["concentration_of_time_points"] = count - 1
            super().__init__(*args, **kwargs)

        def write(self, root_name, objects_name, objects_extension, template,
                  template_data, output_dir, write_adjoint_parameters=False):
            times = np.asarray(self.get_times(), dtype=float)
            if (len(times) != count or times[0] != 0 or times[-1] != 1
                    or not np.allclose(times, np.linspace(0, 1, count), rtol=0, atol=1e-12)):
                raise RuntimeError("Native Shooting grid differs from declared grid")
            if len(objects_name) != 1 or objects_extension != [".vtk"]:
                raise RuntimeError("Verified endpoint export requires one VTK surface")
            field = self.momenta_t0.detach().cpu().numpy()
            data = template.get_deformed_data(self.get_template_points(1), template_data)
            template.write(output_dir, [root_name + "__endpoint.vtk"],
                           {k: v.detach().cpu().numpy() for k, v in data.items()})
            receipt = {"times": times.tolist(), "exported_time": 1,
                       "timepoints": count, "precision": str(field.dtype),
                       "momenta_sha256": hashlib.sha256(field.tobytes()).hexdigest()}
            with open(os.path.join(output_dir, root_name + "__grid.json"), "x") as f:
                json.dump(receipt, f, allow_nan=False)

    module.Geodesic = VerifiedEndpointGeodesic
except BaseException:
    import traceback
    traceback.print_exc()
    os._exit(1)
'''
