# encoding: utf-8
"""

"""
__author__ = 'Richard Smith'
__date__ = '08 Jun 2021'
__copyright__ = 'Copyright 2018 United Kingdom Research and Innovation'
__license__ = 'BSD - see LICENSE file in top-level package directory'
__contact__ = 'richard.d.smith@stfc.ac.uk'

from asset_scanner.core.exceptions import NoPluginsError
from asset_scanner.core.handler_picker import HandlerPicker

# Third party imports
import yaml

# Python imports
import logging
import hashlib
import collections

# Typing imports
from typing import List, Any, Dict, Optional

LOGGER = logging.getLogger(__name__)


def load_plugins(conf: dict, entry_point: str, conf_section: str) -> List:
    """
    Load plugins from the entry points

    :param conf: Configuration dict
    :param entry_point: The name of the collection of entry points
    :param conf_section: The name for the section in the config file
    which applies to these plugins.

    Exceptions:
        NoPluginsError: Triggered if no plugins are successfully loaded

    :return: List of loaded plugins
    """

    loaded_plugins = []

    plugins = HandlerPicker(entry_point)

    for plugin_conf in conf[conf_section]:
        try:
            loaded_plugin = plugins.get_processor(**plugin_conf)
            loaded_plugins.append(loaded_plugin)
        except Exception as e:
            LOGGER.error(f'Failed to load plugin: {plugin_conf["name"]} {e}')

    if not loaded_plugins:
        raise NoPluginsError(f'No plugins were successfully loaded from {conf_section}')

    return loaded_plugins


def generate_id(path):
    return hashlib.md5(path.encode('utf-8')).hexdigest()


def load_yaml(path):
    with open(path) as reader:
        return yaml.safe_load(reader)


def dict_merge(*args, add_keys=True) -> dict:
    assert len(args) >= 2, "dict_merge requires at least two dicts to merge"

    # Make a copy of the root dict
    rtn_dct = args[0].copy()

    merge_dicts = args[1:]

    for merge_dct in merge_dicts:

        if add_keys is False:
            merge_dct = {key: merge_dct[key] for key in set(rtn_dct).intersection(set(merge_dct))}

        for k, v in merge_dct.items():

            # This is a new key. Add as is.
            if not rtn_dct.get(k):
                rtn_dct[k] = v

            # This is an existing key with mismatched types
            elif k in rtn_dct and type(v) != type(rtn_dct[k]):
                raise TypeError(f"Overlapping keys exist with different types: original is {type(rtn_dct[k])}, new value is {type(v)}")

            # Recursive merge the next level
            elif isinstance(rtn_dct[k], dict) and isinstance(merge_dct[k], collections.abc.Mapping):
                rtn_dct[k] = dict_merge(rtn_dct[k], merge_dct[k], add_keys=add_keys)

            # If the item is a list, append items avoiding duplictes
            elif isinstance(v, list):
                for list_value in v:
                    if list_value not in rtn_dct[k]:
                        rtn_dct[k].append(list_value)
            else:
                rtn_dct[k] = v

    return rtn_dct


def dot2dict(key: str, val: Any) -> Dict[str, Any]:
    """
    Convert a dot separated string into
    a dictionary construct. Can work with
    single layer or multi-layer strings.

    Recursively creates from bottom up.

    :param key: Key value. Can be single layer. e.g. ``properties`` or
                multi-level e.g. ``properties.start_time``
    :param val: The value associated with the key

    :return: dict
    """
    if not key:
        return val

    # Split on .
    parts = key.split('.')
    tail = parts.pop()

    # Create the new key
    key = '.'.join(parts)

    val = {tail: val}
    return dot2dict(key, val)


def nested_get(key_list: List, input_dict: Dict) -> Optional[Any]:
    """
    Takes an iterable of keys and returns none if not found or the value
    :param key_list: List of keys to try against the dict
    :param input_dict: Dict to extract key from

    :return: Value found at the key location or None
    """

    last_key = key_list[-1]
    dict_nest = input_dict

    for key in key_list:
        if key != last_key:
            dict_nest = dict_nest.get(key, {})
        else:
            return dict_nest.get(key)