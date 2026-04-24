"""
functions and object for constants
"""
#!/usr/bin/python

# import official python packages
import logging
import os
from functools import lru_cache

# import custom python packages
from wahoomc.constants import RESOURCES_DIR
from wahoomc.constants import USER_CONFIG_DIR
from wahoomc.file_directory_functions import read_json_file_generic

log = logging.getLogger('main-logger')


class TagWahooXmlNotFoundError(Exception):
    """Raised when the specified tag-wahoo xml file does not exist"""


class TagsToKeepNotFoundError(Exception):
    """Raised when the specified tags to keep .json file does not exist"""


@lru_cache(maxsize=4)
def translate_tags_to_keep(name_tags=False, use_repo=False):
    """
    translates the given tags to a list suitable for osmium tags-filter.
    """
    tags_modif = []

    # evaluate path: user-dir takes priority over PyPI installation
    if not use_repo:
        for path in get_absolute_dir_user_or_repo('', file='tags-to-keep.json'):
            if os.path.exists(path):
                break
    else:
        path = get_absolute_dir_user_or_repo('', file='tags-to-keep.json')[1]

    tags_from_json = read_json_file_generic(path)

    if not tags_from_json:
        raise TagsToKeepNotFoundError

    if not name_tags:
        universal_tags = tags_from_json['TAGS_TO_KEEP_UNIVERSAL']
    else:
        universal_tags = tags_from_json['NAME_TAGS_TO_KEEP_UNIVERSAL']

    for tag, value in universal_tags.items():
        tags_modif.append(_transl_tag_value(tag, value))

    return tags_modif


def _transl_tag_value(tag, value):
    """
    translates one tag with value(s) to osmium tags-filter format
    """
    if isinstance(value, list):
        for iteration, sing_val in enumerate(value):
            if iteration == 0:
                to_append = f'{tag}={sing_val}'
            else:
                to_append = f'{to_append}, {sing_val}'
    elif value:
        to_append = f'{tag}={value}'
    else:
        to_append = tag

    return to_append


def get_tag_wahoo_xml_path(tag_wahoo_xml):
    """
    return path to tag-wahoo xml file if the file exists
    - from the user directory "USER_WAHOO_MC/_config/tag_wahoo_adjusted/tag_wahoo_xml"
    - 2ndly from the PyPI installation: "RESOURCES_DIR/tag_wahoo_adjusted/tag_wahoo_xml"
    """

    for path in get_absolute_dir_user_or_repo("tag_wahoo_adjusted", tag_wahoo_xml):
        if os.path.exists(path):
            return path

    raise TagWahooXmlNotFoundError


def get_absolute_dir_user_or_repo(folder, file=''):
    """
    return the absolute path to the folder (and file) in this priorization
    1. user dir
    2. wahoomc package dir

    Priorization is important later on because user- should always be used in favor of repo-dir!
    """
    absolute_paths = []
    if file:
        absolute_paths.append(os.path.join(
            USER_CONFIG_DIR, folder, file))
        absolute_paths.append(os.path.join(
            RESOURCES_DIR, folder, file))
    else:
        absolute_paths.append(os.path.join(USER_CONFIG_DIR, folder))
        absolute_paths.append(os.path.join(
            RESOURCES_DIR, folder))

    return absolute_paths
