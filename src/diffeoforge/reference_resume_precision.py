"""Explicit, immutable promotion of the reference model's arithmetic precision."""

from pathlib import Path
from xml.etree import ElementTree

from diffeoforge.config import ConfigurationError


def promote_model_precision(source: Path, destination: Path) -> None:
    """Change only the model dtype; retain every geometry and model setting."""
    tree = ElementTree.parse(source)
    nodes = tree.getroot().findall("dtype")
    if len(nodes) != 1 or nodes[0].text != "float32":
        raise ConfigurationError("Precision promotion requires one float32 model dtype.")
    nodes[0].text = "float64"
    tree.write(destination, encoding="utf-8", xml_declaration=True)
