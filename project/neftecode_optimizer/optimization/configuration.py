"""YAML loading with duplicate-key rejection (including nested controls)."""

from pathlib import Path
import yaml
from yaml.constructor import ConstructorError


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise ValueError("YAML mapping keys must be scalar") from error
        if duplicate:
            raise ConstructorError(
                "mapping", node.start_mark, f"duplicate key: {key}", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping
)


def load_yaml_mapping(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        raw = yaml.load(stream, Loader=UniqueKeyLoader)
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a YAML mapping, not empty or a list")
    return raw
