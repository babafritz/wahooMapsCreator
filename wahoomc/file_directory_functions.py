"""
constants, functions and object for file-system operations
"""
#!/usr/bin/python

# import official python packages
import json
import os
from os.path import isfile, join
import logging
import shutil

# import custom python packages

log = logging.getLogger('main-logger')


def create_empty_directories(parent_dir, tiles_from_json, border_countries):
    """
    create empty directories for each tile and each country
    """
    for tile in tiles_from_json:
        outdir = os.path.join(parent_dir,
                              f'{tile["x"]}', f'{tile["y"]}')
        os.makedirs(outdir, exist_ok=True)

    for country in border_countries:
        outdir = os.path.join(parent_dir, country)
        os.makedirs(outdir, exist_ok=True)


def read_json_file_generic(json_file_path):
    """
    reads content of given .json file
    """
    try:
        with open(json_file_path, encoding="utf-8") as json_file:
            return json.load(json_file)
    except FileNotFoundError:
        return {}


def write_json_file_generic(json_file_path, json_content):
    """
    writes content to .json file
    """
    # Serializing json
    json_content = json.dumps(json_content, indent=4)

    # Writing to file
    with open(json_file_path, "w", encoding="utf-8") as json_file:
        json_file.write(json_content)


def get_files_in_folder(folder):
    """
    return filenames of given folder without path as list
    """
    onlyfiles = [f for f in os.listdir(folder) if isfile(join(folder, f))]

    return onlyfiles


def copy_or_move_files_and_folder(from_path, to_path, delete_from_dir=False):
    """
    copy content from source directory to destination directory
    optionally delete source directory afterwards

    similar function to move_content but with user-request when overwriting and support for files
    """
    # check if from path/file exists at all
    if os.path.exists(from_path):

        # given path is a directory
        if os.path.isdir(from_path):
            # first create the to-directory if not already there
            os.makedirs(to_path, exist_ok=True)

            for item in os.listdir(from_path):
                from_item = os.path.join(from_path, item)
                to_item = os.path.join(to_path, item)

                # copy directory
                if os.path.isdir(from_item):
                    copy_directory_w_user_input(from_item, to_item)

                # copy file
                else:
                    copy_file_w_user_input(from_item, to_item)

        # given path is a file
        else:
            copy_file_w_user_input(from_path, to_path)

        # directory
        if delete_from_dir:
            shutil.rmtree(from_path)


def copy_directory_w_user_input(from_item, to_item):
    """
    copy content from source directory to destination directory
    """
    if not os.path.isdir(to_item):
        shutil.copytree(from_item, to_item)
    else:
        val = input(f"{to_item} exists already. Overwrite? (y/n):")
        if val == 'y':
            shutil.copytree(from_item, to_item)
            log.info('! %s overwritten', to_item)
        else:
            log.debug('! %s not copied, exists already.', to_item)


def copy_file_w_user_input(from_item, to_item):
    """
    copy source file to destination file
    """
    if not os.path.isfile(to_item):
        shutil.copy2(from_item, to_item)
    else:
        val = input(f"{to_item} exists already. Overwrite? (y/n):")
        if val == 'y':
            shutil.copy2(from_item, to_item)
            log.info('! %s overwritten', to_item)
        else:
            log.debug('! %s not copied, exists already.', to_item)
