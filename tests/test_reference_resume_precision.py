from xml.etree import ElementTree as ET

import numpy as np
import pytest

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_resume_precision import promote_model_precision


@pytest.mark.parametrize("dtype", ["", "<dtype>float64</dtype>",
                                   "<dtype>float32</dtype><dtype>float32</dtype>"])
def test_precision_promotion_refuses_ambiguous_or_non_float32_model(tmp_path, dtype):
    source = tmp_path / "model.xml"
    source.write_text(f"<model>{dtype}<dimension>3</dimension></model>")
    destination = tmp_path / "new.xml"
    with pytest.raises(ConfigurationError, match="one float32"):
        promote_model_precision(source, destination)
    assert not destination.exists()


def test_float64_objective_can_resolve_positive_step_below_unchanged_tolerance():
    # Exercise the native q>0 and strict tolerance equations at a realistic scale.
    origin = np.float64(-44224.03125)
    previous = np.float64(-43290.0)
    current = previous + np.float64(0.0001)
    tolerance = 1e-6
    assert current - previous > 0
    assert abs(previous - current) < tolerance * abs(origin - current)
    single_previous, single_current = np.float32(previous), np.float32(current)
    assert single_previous == single_current  # The same positive step was unresolvable.
    assert abs(np.spacing(previous)) < tolerance * abs(origin - current)


def test_model_promotion_keeps_all_other_xml_values(tmp_path):
    source = tmp_path / "model.xml"
    source.write_text("<model><dtype>float32</dtype><dimension>3</dimension>"
                      "<deformation-parameters><number-of-timepoints>50</number-of-timepoints>"
                      "</deformation-parameters></model>")
    destination = tmp_path / "double.xml"
    before = source.read_bytes()
    promote_model_precision(source, destination)
    root = ET.parse(destination).getroot()
    assert root.find("dtype").text == "float64"
    assert root.find("deformation-parameters/number-of-timepoints").text == "50"
    assert source.read_bytes() == before
