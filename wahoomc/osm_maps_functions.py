"""
functions and object for managing OSM maps
"""
#!/usr/bin/python

# import official python packages
from datetime import datetime
from multiprocessing import Pool
from concurrent.futures import ThreadPoolExecutor
import glob
import multiprocessing
import os
import subprocess
import sys
import shutil
import logging

# import custom python packages
from wahoomc.file_directory_functions import read_json_file_generic, create_empty_directories, write_json_file_generic
from wahoomc.constants_functions import translate_tags_to_keep, \
    get_tag_wahoo_xml_path, TagWahooXmlNotFoundError

from wahoomc.setup_functions import read_earthexplorer_credentials

from wahoomc.constants import USER_WAHOO_MC
from wahoomc.constants import USER_OUTPUT_DIR
from wahoomc.constants import RESOURCES_DIR
from wahoomc.constants import LAND_POLYGONS_PATH
from wahoomc.constants import VERSION
from wahoomc.constants import USER_DL_DIR

from wahoomc.timings import Timings

log = logging.getLogger('main-logger')


def run_subprocess_and_log_output(cmd, error_message, cwd=""):
    """
    run given cmd-subprocess and issue error message if wished
    """
    if not cwd:
        process = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", check=False)

    else:
        process = subprocess.run(  # pylint: disable=consider-using-with
            cmd, capture_output=True, cwd=cwd, text=True, encoding="utf-8", check=False)


    if error_message and process.returncode != 0:  # 0 means success
        log.error('subprocess error output:')
        if process.stderr:
            log.error(process.stderr)

        log.error(error_message)
        sys.exit(process.returncode)

    elif process.stdout:
        log.debug('subprocess debug output:')
        log.debug(process.stdout)


def get_timestamp_last_changed(file_path):
    """
    returns the timestamp of the last-changed datetime of the given file
    """
    chg_time = os.path.getmtime(file_path)

    return datetime.fromtimestamp(chg_time).isoformat()


# ---------------------------------------------------------------------------
# per-tile worker functions (module-level so they're picklable for Pool)
# ---------------------------------------------------------------------------


def _is_edge_tile(tile):
    return tile["x"] in (0, 255) or tile["y"] in (0, 255)


def _tile_bbox(tile, pad=0.1):
    """Return (left, bottom, right, top) with padding for interior tiles."""
    p = 0 if _is_edge_tile(tile) else pad
    return tile["left"] - p, tile["bottom"] - p, tile["right"] + p, tile["top"] + p


def _worker_generate_land(args):
    tile, force_processing = args
    land_file = os.path.join(USER_OUTPUT_DIR,
                             f'{tile["x"]}', f'{tile["y"]}', 'land.shp')
    out_file_land1 = os.path.join(USER_OUTPUT_DIR,
                                  f'{tile["x"]}', f'{tile["y"]}', 'land')

    if not os.path.isfile(land_file) or force_processing is True:
        left, bottom, right, top = _tile_bbox(tile)
        cmd = ['ogr2ogr', '-overwrite', '-skipfailures',
               '-spat', f'{left:.6f}', f'{bottom:.6f}', f'{right:.6f}', f'{top:.6f}']
        cmd.append(land_file)
        cmd.append(LAND_POLYGONS_PATH)

        run_subprocess_and_log_output(
            cmd, f'! Error generating land for tile: {tile["x"]},{tile["y"]}')

    if not os.path.isfile(out_file_land1 + '1.osm') or force_processing is True:
        cmd = ['python', os.path.join(RESOURCES_DIR, 'shape2osm.py'),
               '-l', out_file_land1, land_file]
        run_subprocess_and_log_output(
            cmd, f'! Error creating land.osm for tile: {tile["x"]},{tile["y"]}')


def _worker_generate_sea(args):
    tile, force_processing, sea_template = args
    out_file_sea = os.path.join(USER_OUTPUT_DIR,
                                f'{tile["x"]}', f'{tile["y"]}', 'sea.osm')
    if os.path.isfile(out_file_sea) and force_processing is False:
        return

    left, bottom, right, top = _tile_bbox(tile)

    sea_data = (sea_template
                .replace('$LEFT', f'{left:.6f}')
                .replace('$BOTTOM', f'{bottom:.6f}')
                .replace('$RIGHT', f'{right:.6f}')
                .replace('$TOP', f'{top:.6f}'))
    with open(out_file_sea, mode='w', encoding="utf-8") as output_file:
        output_file.write(sea_data)


def _worker_generate_elevation(args):
    tile, force_processing, use_srtm1, hgt_path, username, password, phyghtmap_jobs = args
    out_file_elevation = os.path.join(
        USER_OUTPUT_DIR, f'{tile["x"]}', f'{tile["y"]}', 'elevation')

    if use_srtm1:
        existing = glob.glob(os.path.join(
            USER_OUTPUT_DIR, str(tile["x"]), str(tile["y"]), 'elevation*srtm1*.osm'))
        source = '--source=srtm1,view1,view3,srtm3'
    else:
        existing = glob.glob(os.path.join(
            USER_OUTPUT_DIR, str(tile["x"]), str(tile["y"]), 'elevation*view1*.osm'))
        source = '--source=view1,view3,srtm3'

    if (len(existing) == 1 and os.path.isfile(existing[0])) and force_processing is False:
        return

    cmd = ['phyghtmap']
    cmd.append('-a ' + f'{tile["left"]}' + ':' + f'{tile["bottom"]}' +
               ':' + f'{tile["right"]}' + ':' + f'{tile["top"]}')
    cmd.extend(['-o', f'{out_file_elevation}', '-s 10', '-c 100,50', source,
                f'--jobs={phyghtmap_jobs}', '--viewfinder-mask=1', '--start-node-id=20000000000',
                '--max-nodes-per-tile=0', '--start-way-id=2000000000', '--write-timestamp',
                '--no-zero-contour', '--hgtdir=' + hgt_path])
    cmd.append('--earthexplorer-user=' + username)
    cmd.append('--earthexplorer-password=' + password)
    run_subprocess_and_log_output(
        cmd, f'! Error in phyghtmap with tile: {tile["x"]},{tile["y"]}')


def _worker_split_tile_country(args):
    tile, country, filtered_file, filtered_file_names = args
    out_file = os.path.join(USER_OUTPUT_DIR,
                            f'{tile["x"]}', f'{tile["y"]}', f'split-{country}.osm.pbf')
    out_file_names = os.path.join(USER_OUTPUT_DIR,
                                  f'{tile["x"]}', f'{tile["y"]}', f'split-{country}-names.osm.pbf')
    bbox = f'{tile["left"]},{tile["bottom"]},{tile["right"]},{tile["top"]}'

    for src, dst in ((filtered_file, out_file),
                     (filtered_file_names, out_file_names)):
        cmd = ['osmium', 'extract', '-b', bbox, src,
               '-s', 'smart', '-o', dst, '--overwrite']
        run_subprocess_and_log_output(
            cmd, f'! Error in Osmium with country: {country}')


def _sort_land_files_for_tile(tile):
    """sort land*.osm files for a single tile; safe to call from a worker"""
    land_files = glob.glob(os.path.join(USER_OUTPUT_DIR,
                                        f'{tile["x"]}', f'{tile["y"]}', 'land*.osm'))
    for land in land_files:
        cmd = ['osmosis', '--read-xml', 'file=' + land, '--sort',
               '--write-xml', 'file=' + land]
        run_subprocess_and_log_output(
            cmd, f'Error in Osmosis with sorting land* osm files of tile: {tile["x"]},{tile["y"]}')


def _worker_merge_tile(args):
    (tile, border_country_set, process_border_countries, contour,
     workers, cleanup_intermediate) = args
    out_tile_dir = os.path.join(USER_OUTPUT_DIR,
                                f'{tile["x"]}', f'{tile["y"]}')
    out_file_merged = os.path.join(out_tile_dir, 'merged.osm.pbf')
    land_files = glob.glob(os.path.join(out_tile_dir, 'land*.osm'))
    elevation_files = glob.glob(os.path.join(out_tile_dir, 'elevation*.osm'))

    _sort_land_files_for_tile(tile)

    cmd = ['osmosis']

    loop = 0
    split_files = []
    for country in tile['countries']:
        if process_border_countries or country in border_country_set:
            split_file = os.path.join(out_tile_dir, f'split-{country}.osm.pbf')
            split_names = os.path.join(out_tile_dir, f'split-{country}-names.osm.pbf')
            cmd.extend(['--rbf', split_file, 'workers=' + workers])
            if loop > 0:
                cmd.append('--merge')
            cmd.extend(['--rbf', split_names, 'workers=' + workers, '--merge'])
            split_files.extend([split_file, split_names])
            loop += 1

    for land in land_files:
        cmd.extend(['--rx', 'file=' + land, '--s', '--m'])
    if contour:
        for elevation in elevation_files:
            cmd.extend(['--rx', 'file=' + elevation, '--s', '--m'])
    cmd.extend(['--rx', 'file=' + os.path.join(out_tile_dir, 'sea.osm'), '--s', '--m'])
    cmd.extend(['--tag-transform',
                'file=' + os.path.join(RESOURCES_DIR, 'tunnel-transform.xml'),
                '--wb', out_file_merged, 'omitmetadata=true'])

    run_subprocess_and_log_output(
        cmd, f'! Error in Osmosis with tile: {tile["x"]},{tile["y"]}')

    if cleanup_intermediate:
        for path in split_files:
            try:
                os.remove(path)
            except OSError:
                pass


def _worker_create_map(args):
    (tile, tag_wahoo_xml_path, hdd_mode,
     save_cruiser, mapwriter_threads) = args
    out_file_map = os.path.join(USER_OUTPUT_DIR,
                                f'{tile["x"]}', f'{tile["y"]}.map')
    merged_file = os.path.join(USER_OUTPUT_DIR,
                               f'{tile["x"]}', f'{tile["y"]}', 'merged.osm.pbf')

    cmd = ['osmosis', '--rb', merged_file, '--mw', 'file=' + out_file_map]
    cmd.append(f'bbox={tile["bottom"]:.6f},{tile["left"]:.6f},{tile["top"]:.6f},{tile["right"]:.6f}')
    cmd.append('zoom-interval-conf=12,0,17')
    cmd.append(f'threads={mapwriter_threads}')
    if hdd_mode:
        cmd.append('type=hd')
    cmd.append(f'tag-conf-file={tag_wahoo_xml_path}')
    run_subprocess_and_log_output(
        cmd, f'Error in creating map file via Osmosis with tile: {tile["x"]},{tile["y"]}. mapwriter plugin installed?')

    cmd = ['lzma', out_file_map, '-f']
    if save_cruiser:
        cmd.append('--keep')
    run_subprocess_and_log_output(
        cmd, f'! Error creating map files for tile: {tile["x"]},{tile["y"]}')

    with open(out_file_map + '.lzma.17', mode='wb'):
        pass


class OsmMaps:
    """
    This is a OSM data class
    """

    # Number of workers for the Osmosis read binary fast function
    workers = '1'

    def __init__(self, o_osm_data, jobs=0, cleanup_intermediate=False):
        self.o_osm_data = o_osm_data
        # cache for per-country .config.json reads; avoids re-parsing the same
        # file up to 4x per country during the filtering phase.
        # None = file missing or unreadable.
        self._country_config_cache = {}

        # 0 means auto: leave one core free for the OS.
        if jobs and jobs > 0:
            self.jobs = jobs
        else:
            self.jobs = max(1, (os.cpu_count() or 1) - 1)
        self.cleanup_intermediate = cleanup_intermediate

        create_empty_directories(
            USER_OUTPUT_DIR, self.o_osm_data.tiles, self.o_osm_data.border_countries)

    def _run_parallel(self, worker, tasks, label):
        """
        fan out a worker over tasks, respecting self.jobs and keeping ordered
        log output. Falls back to serial when jobs==1 or len(tasks)<=1.
        """
        tasks = list(tasks)
        total = len(tasks)
        pool_size = min(self.jobs, total) if total else 1
        if pool_size <= 1:
            for idx, task in enumerate(tasks, start=1):
                worker(task)
                log.info('+ (%s %d/%d) done', label, idx, total)
            return
        with Pool(pool_size) as pool:
            for idx, _ in enumerate(pool.imap_unordered(worker, tasks), start=1):
                log.info('+ (%s %d/%d) done', label, idx, total)

    def _get_country_config(self, country):
        """
        return the parsed .config.json for a country, reading from disk on
        first access and caching thereafter
        """
        if country in self._country_config_cache:
            return self._country_config_cache[country]
        try:
            cfg = read_json_file_generic(os.path.join(
                USER_OUTPUT_DIR, country, ".config.json"))
        except FileNotFoundError:
            cfg = None
        self._country_config_cache[country] = cfg
        return cfg

    def filter_tags_from_country_osm_pbf_files(self):
        """
        Filter tags from country osm.pbf files
        """

        log.info('-' * 80)
        log.info('# Filter tags from country osm.pbf files')
        timings = Timings()
        for key, val in self.o_osm_data.border_countries.items():
            country_dir = os.path.join(USER_OUTPUT_DIR, key)

            out_file_pbf_filtered = os.path.join(country_dir, 'filtered.o5m.pbf')
            out_file_pbf_filtered_names = os.path.join(country_dir, 'filtered_names.o5m.pbf')

            if not os.path.isfile(out_file_pbf_filtered) or not os.path.isfile(out_file_pbf_filtered_names) \
                    or self.o_osm_data.force_processing is True or self.tags_are_identical_to_last_run(key) is False \
                    or self.last_changed_is_identical_to_last_run(key) is False:
                log.info('+ Filtering unwanted map objects out of map of %s', key)

                # https://docs.osmcode.org/osmium/latest/osmium-tags-filter.html
                cmd = ['osmium', 'tags-filter', '--remove-tags']
                cmd.append(val['map_file'])
                cmd.extend(translate_tags_to_keep())
                cmd.extend(['-o', out_file_pbf_filtered])
                cmd.append('--overwrite')
                run_subprocess_and_log_output(cmd, f'! Error in Osmium with country: {key}')

                cmd = ['osmium', 'tags-filter', '--remove-tags']
                cmd.append(val['map_file'])
                cmd.extend(translate_tags_to_keep(name_tags=True))
                cmd.extend(['-o', out_file_pbf_filtered_names])
                cmd.append('--overwrite')
                run_subprocess_and_log_output(cmd, f'! Error in Osmium with country: {key}')

            val['filtered_file'] = out_file_pbf_filtered
            val['filtered_file_names'] = out_file_pbf_filtered_names

            self.write_country_config_file(key)

        log.info('+ Filter tags from country osm.pbf files: OK, %s', timings.stop_and_return())

    def generate_land(self):
        """
        Generate land for all tiles
        """

        log.info('-' * 80)
        log.info('# Generate land for each coordinate')
        timings = Timings()

        tasks = [(tile, self.o_osm_data.force_processing)
                 for tile in self.o_osm_data.tiles]
        self._run_parallel(_worker_generate_land, tasks, 'land')

        log.info('+ Generate land for each coordinate: OK, %s', timings.stop_and_return())

    def generate_sea(self):
        """
        Generate sea for all tiles
        """

        log.info('-' * 80)
        log.info('# Generate sea for each coordinate')
        timings = Timings()

        with open(os.path.join(RESOURCES_DIR, 'sea.osm'), encoding="utf-8") as sea_file:
            sea_template = sea_file.read()

        tasks = [(tile, self.o_osm_data.force_processing, sea_template)
                 for tile in self.o_osm_data.tiles]
        self._run_parallel(_worker_generate_sea, tasks, 'sea')

        log.info('+ Generate sea for each coordinate: OK, %s', timings.stop_and_return())

    def generate_elevation(self, use_srtm1):
        """
        Generate contour lines for all tiles
        """
        username, password = read_earthexplorer_credentials()

        log.info('-' * 80)
        log.info('# Generate contour lines for each coordinate')

        hgt_path = os.path.join(USER_DL_DIR, 'hgt')
        timings = Timings()

        # when running in a multi-process pool, let each phyghtmap use a single
        # thread to avoid (jobs * 8) oversubscription; otherwise keep the
        # previous default of 8.
        phyghtmap_jobs = 8 if self.jobs <= 1 else max(1, (os.cpu_count() or 1) // self.jobs)

        tasks = [(tile, self.o_osm_data.force_processing, use_srtm1,
                  hgt_path, username, password, phyghtmap_jobs)
                 for tile in self.o_osm_data.tiles]
        self._run_parallel(_worker_generate_elevation, tasks, 'elevation')

        log.info('+ Generate contour lines for each coordinate: OK, %s', timings.stop_and_return())

    def split_filtered_country_files_to_tiles(self):
        """
        Split filtered country files to tiles
        """

        log.info('-' * 80)
        log.info('# Split filtered country files to tiles')
        timings = Timings()

        tasks = []
        for tile in self.o_osm_data.tiles:
            for country, val in self.o_osm_data.border_countries.items():
                if country not in tile['countries']:
                    continue
                tasks.append((tile, country, val['filtered_file'],
                              val['filtered_file_names']))

        self._run_parallel(_worker_split_tile_country, tasks, 'split')

        log.info('+ Split filtered country files to tiles: OK, %s', timings.stop_and_return())

    def merge_splitted_tiles_with_land_and_sea(self, process_border_countries, contour):
        """
        Merge splitted tiles with land elevation and sea
        - elevation data only if requested
        """

        log.info('-' * 80)
        log.info('# Merge splitted tiles with land, elevation, and sea')
        timings = Timings()

        border_country_set = set(self.o_osm_data.border_countries)
        tasks = [(tile, border_country_set, process_border_countries, contour,
                  self.workers, self.cleanup_intermediate)
                 for tile in self.o_osm_data.tiles]

        self._run_parallel(_worker_merge_tile, tasks, 'merge')

        log.info('+ Merge splitted tiles with land, elevation, and sea: OK, %s', timings.stop_and_return())

    def create_map_files(self, save_cruiser, tag_wahoo_xml, hdd_mode):
        """
        Creating .map files
        """

        log.info('-' * 80)
        log.info('# Creating .map files for tiles')

        # Resolve the tag-wahoo xml path once; fail fast on bad input.
        try:
            tag_wahoo_xml_path = get_tag_wahoo_xml_path(tag_wahoo_xml)
        except TagWahooXmlNotFoundError:
            log.error(
                "The tag-wahoo xml file was not found: '%s'. Does the file exist and is your input correct?", tag_wahoo_xml)
            sys.exit(1)

        # Split the available cores between the process pool and the per-tile
        # mapwriter threads. With N parallel tiles each using threads=K we want
        # N*K ≈ cpu_count.
        total_threads = max(1, (os.cpu_count() or 1) - 1)
        mapwriter_threads = max(1, total_threads // max(1, self.jobs))

        timings = Timings()

        tasks = [(tile, tag_wahoo_xml_path, hdd_mode,
                  save_cruiser, mapwriter_threads)
                 for tile in self.o_osm_data.tiles]
        self._run_parallel(_worker_create_map, tasks, 'map')

        log.info('+ Creating .map files for tiles: OK, %s', timings.stop_and_return())

    def make_and_zip_files(self, extension, zip_folder):
        """
        make or make and zip .map or .map.lzma files
        extension: '.map.lzma' for Wahoo tiles
        extension: '.map' for Cruiser map files
        """
        # if country_name is longer than 50 characters, cut down to 50 for the folder name
        # that preserves crashing later on when creating the output folder
        folder_name = self.calculate_folder_name(extension)

        log.info('-' * 80)
        log.info('# Create: %s files', extension)
        log.info('+ Country: %s', self.o_osm_data.country_name)
        timings = Timings()

        self.o_osm_data.country_name = self.o_osm_data.country_name.split('/')[-1]

        # copy the needed tiles to the country folder
        log.info('+ Copying %s tiles to output folders', extension)
        copy_tasks = []
        for tile in self.o_osm_data.tiles:
            src = os.path.join(f'{USER_OUTPUT_DIR}',
                               f'{tile["x"]}', f'{tile["y"]}') + extension
            dst = os.path.join(
                f'{USER_WAHOO_MC}', folder_name, f'{tile["x"]}', f'{tile["y"]}') + extension
            copy_tasks.append((src, dst))
            if extension == '.map.lzma':
                copy_tasks.append((src + '.17', dst + '.17'))

        def _copy(pair):
            src, dst = pair
            self.copy_to_dst(extension, src, dst)

        if self.jobs > 1 and len(copy_tasks) > 1:
            with ThreadPoolExecutor(max_workers=min(self.jobs, len(copy_tasks))) as ex:
                list(ex.map(_copy, copy_tasks))
        else:
            for pair in copy_tasks:
                _copy(pair)

        if zip_folder:
            cmd = ['zip', '-r', folder_name + '.zip', folder_name]
            run_subprocess_and_log_output(
                cmd, f'! Error zipping map files for folder: {folder_name}', cwd=USER_WAHOO_MC)

            # Delete the country/region map folders after compression
            try:
                shutil.rmtree(os.path.join(
                    f'{USER_WAHOO_MC}', folder_name))
            except OSError:
                log.error(
                    '! Error, could not delete folder %s', os.path.join(USER_WAHOO_MC, folder_name))

            log.info('+ Zip %s files: OK', extension)

        log.info('+ Create %s files: OK, %s', extension, timings.stop_and_return())

    def calculate_folder_name(self, extension):
        """
        if country_name is longer than 50 characters, cut down to 50 for the folder name
        that preserves crashing later on when creating the output folder
        """
        # cut down to 100 (relevant if country_name is longer than 100 characters)
        if len(self.o_osm_data.country_name) > 50:
            country_name_50_chars = self.o_osm_data.country_name[:41] + '_and_more'
        else:
            country_name_50_chars = self.o_osm_data.country_name

        if extension == '.map.lzma':
            folder_name = country_name_50_chars
        else:
            folder_name = country_name_50_chars + '-maps'

        return folder_name

    def copy_to_dst(self, extension, src, dst):
        """
        Zip .map or .map.lzma files
        postfix: '.map.lzma' for Wahoo tiles
        postfix: '.map' for Cruiser map files
        """
        outdir = os.path.dirname(dst)

        # first create the to-directory if not already there
        os.makedirs(outdir, exist_ok=True)

        try:
            shutil.copy2(src, dst)
        except Exception as exception:  # pylint: disable=broad-except
            log.error(
                '! Error copying %s files for country %s: %s', extension, self.o_osm_data.country_name, exception)
            sys.exit(1)

    def write_country_config_file(self, country):
        """
        Write country config file into _tiles/{country} directory
        """
        # Data to be written
        configuration = {
            "version_last_run": VERSION,
            "changed_ts_map_last_run": get_timestamp_last_changed(self.o_osm_data.border_countries[country]['map_file']),
            "tags_last_run": translate_tags_to_keep(),
            "name_tags_last_run": translate_tags_to_keep(name_tags=True)
        }

        write_json_file_generic(os.path.join(
            USER_OUTPUT_DIR, country, ".config.json"), configuration)
        # invalidate cache so subsequent reads see the new file
        self._country_config_cache.pop(country, None)

    def tags_are_identical_to_last_run(self, country):
        """
        compare tags of this run with used tags from last run stored in _tiles/{country} directory
        """
        country_config = self._get_country_config(country)
        if country_config is None:
            return False
        try:
            return country_config["tags_last_run"] == translate_tags_to_keep() \
                and country_config["name_tags_last_run"] == translate_tags_to_keep(name_tags=True)
        except KeyError:
            return False

    def last_changed_is_identical_to_last_run(self, country):
        """
        compare tags of this run with used tags from last run stored in _tiles/{country} directory
        """
        country_config = self._get_country_config(country)
        if country_config is None:
            return False
        try:
            return country_config["changed_ts_map_last_run"] == get_timestamp_last_changed(self.o_osm_data.border_countries[country]['map_file'])
        except KeyError:
            return False

