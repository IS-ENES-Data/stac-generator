# encoding: utf-8
"""

"""
__author__ = "Richard Smith"
__date__ = "08 Jun 2021"
__copyright__ = "Copyright 2018 United Kingdom Research and Innovation"
__license__ = "BSD - see LICENSE file in top-level package directory"
__contact__ = "richard.d.smith@stfc.ac.uk"

import collections
import logging
import re

# Python imports
from datetime import datetime
from pathlib import Path
from string import Template

# Typing imports
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

# Third party imports
from dateutil.parser import parse

from stac_generator.core.exceptions import NoPluginsError
from stac_generator.core.handler_picker import HandlerPicker

LOGGER = logging.getLogger(__name__)

NumType = Union[float, int]

DATE_TEMPLATE = Template("${year}-${month}-${day}T${hour}:${minute}:${second}")


class Coordinates:
    """
    Takes care of coordinate transformations
    """

    def __init__(self, minlon, maxlon, minlat, maxlat):
        self.minlon = minlon
        self.maxlon = maxlon
        self.minlat = minlat
        self.maxlat = maxlat

    @classmethod
    def from_geojson(cls, coordinates: List[List[NumType]]) -> "Coordinates":
        """
        GeoJSON formatted coordinates are in the form:

        [[minLon, maxLat],[maxLon, minLat]]

        :param coordinates: GeoJSON formatted coordinates from elasticsearch
        """

        minlon = coordinates[0][0]
        maxlon = coordinates[1][0]
        minlat = coordinates[1][1]
        maxlat = coordinates[0][1]

        return cls(minlon, maxlon, minlat, maxlat)

    @classmethod
    def from_wgs84(cls, coordinates: List) -> "Coordinates":
        """
        WGS84 formatted coordinates are in the form:

        [minLon, minLat, maxLon, maxLat]

        :param coordinates: WGS84 formatted coordinates
        """

        minlon = coordinates[0]
        maxlon = coordinates[2]
        minlat = coordinates[1]
        maxlat = coordinates[3]

        return cls(minlon, maxlon, minlat, maxlat)

    def to_wgs84(self) -> List[NumType]:
        """
        Exports the coordinates in WGS84 format

        [minLon, minLat, maxLon, maxLat]
        """

        return [self.minlon, self.minlat, self.maxlon, self.maxlat]

    def to_geojson(self) -> List[List[NumType]]:
        """
        Exports the coordinates in GeoJSON format

        [[minLon, maxLat],[maxLon, minLat]]
        """

        return [[self.minlon, self.maxlat], [self.maxlon, self.minlat]]


class Stats:
    @classmethod
    def from_boto(cls, s3: dict) -> dict:
        return dict(
            size=s3.get("ContentLength"),
            last_modified=s3.get("LastModified"),
            content_type=s3.get("ContentType"),
            Etag=s3.get("Etag"),
        )


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
        except Exception:
            LOGGER.error(f'Failed to load plugin: {plugin_conf["name"]}', exc_info=True)

    if not loaded_plugins:
        raise NoPluginsError(f"No plugins were successfully loaded from {conf_section}")

    return loaded_plugins


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
            merge_dct = {
                key: merge_dct[key] for key in set(rtn_dct).intersection(set(merge_dct))
            }

        for k, v in merge_dct.items():

            # This is a new key. Add as is.
            if not rtn_dct.get(k):
                rtn_dct[k] = v

            # This is an existing key with mismatched types
            elif k in rtn_dct and not isinstance(v, type(rtn_dct[k])):
                if isinstance(v, list) and rtn_dct[k] in v:
                    rtn_dct[k] = v
                elif isinstance(rtn_dct[k], list) and v in rtn_dct[k]:
                    rtn_dct[k] = rtn_dct[k]
                else:
                    raise TypeError(
                        f"Overlapping keys exist with different types: original: {type(rtn_dct[k])}, new value: {type(v)} for key: {k}"
                    )

            # Recursive merge the next level
            elif isinstance(rtn_dct[k], dict) and isinstance(
                merge_dct[k], collections.abc.Mapping
            ):
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
    parts = key.split(".")
    tail = parts.pop()

    # Create the new key
    key = ".".join(parts)

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


def load_description_files(path: str) -> List[str]:
    """
    Load the yaml description files recursively under the root path

    :param path: Root path for the description files
    """

    exts = [".yml", ".yaml"]
    return [p for p in Path(path).rglob("*") if p.suffix in exts]


DATE_TEMPLATE = Template("${year}-${month}-${day}T${hour}:${minute}:${second}")


def is_remote_uri(path: str) -> bool:
    """Finds URLs of the form protocol:// or protocol::
    This also matches for http[s]://, which were the only remote URLs
    supported in <=v0.16.2.
    """
    return bool(re.search(r"^[a-z][a-z0-9]*(\://|\:\:)", path))


def isoformat_date(date_string: str, format=None) -> Tuple[Optional[str], bool]:
    """
    Return the date string in ISO 8601 format.

    :param date_string: date string to parse
    :param format: Optional format string to try against the date string
    :return:
        possible return values:
            - None, True: Format string supplied. Unable to parse date using format string or dateutil.parser.parse
            - None, False: No format string supplied. Tried dateutil.parser.parse and failed
            - str, True: Format string supplied and failed to parse date. Date successfully parsed by dateutil.parser.parse
            - str, False: Either the format string or date parser worked successfully.
    """

    output_date = None
    format_errors = False

    try:
        # If there is a specified format, try that. Else
        # use generic parser
        if format:
            output_date = datetime.strptime(date_string, format).isoformat()
        else:
            output_date = parse(date_string).isoformat()
    except ValueError as e:
        if format:
            format_errors = True
            LOGGER.warning(
                f"Could not parse {date_string} with format {format}. {e}\n"
                f"Trying dateutil..."
            )
        else:
            LOGGER.error(f"Error parsing {date_string} with dateutil. {e}")

    # Tried specific format but this failed. Try generic parser.
    if format_errors:
        try:
            output_date = parse(date_string).isoformat()
        except ValueError as e:
            LOGGER.error(f"Error parsing {date_string} with dateutil. {e}")

    return output_date, format_errors
