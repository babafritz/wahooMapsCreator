"""
functions and object for checking for up-to-date & downloading land_polygons file and OSM maps
"""
#!/usr/bin/python

# import official python packages
import glob
import os
import os.path
import sys
import time
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
import requests
from requests.adapters import HTTPAdapter

# import custom python packages
from wahoomc.geofabrik_json import GeofabrikJson
from wahoomc.timings import Timings

from wahoomc.constants import USER_DL_DIR
from wahoomc.constants import USER_MAPS_DIR
from wahoomc.constants import LAND_POLYGONS_PATH
from wahoomc.constants import GEOFABRIK_PATH
from wahoomc.constants import USER_DIR

log = logging.getLogger('main-logger')

# Cap parallel Geofabrik downloads. Geofabrik asks clients to share bandwidth
# fairly; four is a conservative ceiling that still gives a useful speed-up.
MAX_PARALLEL_DOWNLOADS = 4

# Module-level pooled session so every request reuses TCP connections + TLS
# handshakes. Set once at import; workers in this module all go through it.
_SESSION = requests.Session()
_adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=2)
_SESSION.mount('http://', _adapter)
_SESSION.mount('https://', _adapter)


def older_than_x_days(file_creation_timestamp, max_days_old):
    """
    check if given timestamp is older that given days
    """
    to_old_timestamp = time.time() - 60 * 60 * 24 * max_days_old

    return bool(file_creation_timestamp < to_old_timestamp)


def download_file(target_filepath, url, target_dir=""):
    """
    download given file and eventually unzip it
    """
    logging_filename = target_filepath.split(os.sep)[-1]
    log.info('-' * 80)
    log.info('# Downloading %s file', logging_filename)
    timings = Timings()
    if url.split('.')[-1] == 'zip':
        # build target-filepath based on last element of URL
        last_part = url.rsplit('/', 1)[-1]
        dl_file_path = os.path.join(USER_DL_DIR, last_part)
        # download URL to file
        download_url_to_file(url, dl_file_path)

        # if a target directory is given --> extract into that folder
        if target_dir:
            target_path = target_dir
        else:
            target_path = USER_DL_DIR

        # unpack it
        if os.path.basename(target_dir) == 'Osmosis':
            unzip_ignore_first_dir(dl_file_path, target_path)
        else:
            unzip(dl_file_path, target_path)

        os.remove(dl_file_path)
    else:
        # no zipping --> directly download to given target filepath
        download_url_to_file(url, target_filepath)
    # Check if file exists (if target file exists)
    if not os.path.isfile(target_filepath):
        log.error('! failed to find %s', target_filepath)
        sys.exit()
    else:
        log.info('+ Downloaded: %s, %s', target_filepath, timings.stop_and_return())


def build_osm_pbf_filepath(country):
    """
    build download filepath to countries' OSM file
    replace / to have no problem with directories
    """
    # build path to downloaded file with geofabrik country
    map_file_path = os.path.join(
        USER_MAPS_DIR, f'{country.replace("/", "_")}' + '-latest.osm.pbf')

    # return download filepath
    return map_file_path


def download_url_to_file(url, map_file_path):
    """
    download the content of a URL to file, using HTTP conditional requests
    when a previous copy exists so unchanged files transfer zero bytes
    """
    headers = {}
    etag_path = map_file_path + '.etag'

    # If the target already exists, ask the server whether it changed. Prefer
    # ETag (strongest) and fall back to If-Modified-Since from the file mtime.
    if os.path.isfile(map_file_path):
        try:
            with open(etag_path, 'r', encoding='utf-8') as etag_fh:
                stored_etag = etag_fh.read().strip()
            if stored_etag:
                headers['If-None-Match'] = stored_etag
        except FileNotFoundError:
            pass
        headers['If-Modified-Since'] = formatdate(
            timeval=os.path.getmtime(map_file_path), usegmt=True)

    # set timeout to 30 minutes (per file)
    response = _SESSION.get(
        url, allow_redirects=True, stream=True, timeout=1800, headers=headers)

    if response.status_code == 304:
        log.info('+ %s unchanged on server (304), skipping body transfer',
                 os.path.basename(map_file_path))
        # refresh the mtime so max_days_old checks don't re-trigger tomorrow
        os.utime(map_file_path, None)
        response.close()
        return

    if response.status_code != 200:
        log.error('! failed download URL: %s (status %s)', url, response.status_code)
        sys.exit()

    # stream to a .part file then atomically rename so an interrupted download
    # can't leave a half-written file that later looks up to date
    part_path = map_file_path + '.part'
    with open(part_path, mode='wb') as file_handle:
        for chunk in response.iter_content(chunk_size=1024 * 100):
            if chunk:
                file_handle.write(chunk)
    os.replace(part_path, map_file_path)

    etag = response.headers.get('ETag')
    if etag:
        with open(etag_path, 'w', encoding='utf-8') as etag_fh:
            etag_fh.write(etag)
    response.close()


def download_tooling():
    """
    Download the mapsforge mapwriter plugin if not present.
    check here for new mapwriter plugin version: https://github.com/mapsforge/mapsforge
    """
    map_writer_filename = 'mapsforge-map-writer-0.21.0-jar-with-dependencies.jar'
    mapwriter_plugin_url = 'https://search.maven.org/remotecontent?filepath=org/mapsforge/mapsforge-map-writer/0.21.0/' + map_writer_filename

    mapwriter_plugin_path = os.path.join(
        str(USER_DIR), '.openstreetmap', 'osmosis', 'plugins', map_writer_filename)

    if not os.path.isfile(mapwriter_plugin_path):
        log.info('# Need to download Osmosis mapwriter plugin')
        os.makedirs(os.path.dirname(mapwriter_plugin_path), exist_ok=True)
        download_file(mapwriter_plugin_path, mapwriter_plugin_url)

    download_geofabrik_file_if_not_existing()


def download_geofabrik_file_if_not_existing():
    """
    check geofabrik file if not existing
    if the file does not exist, download geofabrik file
    """
    if not os.path.isfile(GEOFABRIK_PATH):
        log.info('# Need to download geofabrik file')
        download_file(GEOFABRIK_PATH,
                      'https://download.geofabrik.de/index-v1.json')


def get_latest_pypi_version():
    """
    get latest wahoomc version available on PyPI
    """
    try:
        response = _SESSION.get(
            'https://pypi.org/pypi/wahoomc/json', timeout=1)
        return response.json()['info']['version']
    except (requests.ConnectionError, requests.Timeout):
        return None


def write_to_file(file_path, request):
    """
    write content of request into given file path
    """
    with open(file_path, mode='wb') as file_handle:
        for chunk in request.iter_content(chunk_size=1024*100):
            file_handle.write(chunk)


def unzip(source_filename, dest_dir):
    """
    unzip the given file into the given directory
    """
    with zipfile.ZipFile(source_filename, 'r') as zip_ref:
        zip_ref.extractall(dest_dir)


def unzip_ignore_first_dir(source_filename, dest_dir):
    """
    unzip the given file into the given directory without the first directory.
    made because of Osmosis was unzipped to Osmosis/osmosis-0.49.2
    """
    first_dir_processed = False
    with zipfile.ZipFile(source_filename) as zip_file:
        for zip_info in zip_file.infolist():
            if zip_info.is_dir() and not first_dir_processed:
                # ignore first dir in zip. for osmosis, this is 'osmosis-0.49.2' as of 14.10.2024
                first_dir_processed = True
                continue

            # cut out first part of the dir. for osmosis, this is 'osmosis-0.49.2' as of 14.10.2024
            dir_without_first_part = zip_info.filename.split('/', 1)[1]

            # set name where to save to the newly created dir name
            zip_info.filename = dir_without_first_part
            zip_file.extract(zip_info, dest_dir)


class Downloader:
    """
    This is the class to check and download maps / artifacts"
    """

    def __init__(self, max_days_old, force_download, border_countries=None):
        self.max_days_old = max_days_old
        self.force_download = force_download
        self.border_countries = border_countries

        # safety net if geofabrik file is not there
        # OsmData=>process_input_of_the_tool does it "correctly"
        download_geofabrik_file_if_not_existing()

        self.o_geofabrik_json = GeofabrikJson()

        self.need_to_dl = []

    def should_geofabrik_file_be_downloaded(self):
        """
        check geofabrik file if not existing or is not up-to-date

        # if geofabrik file needs to be downloaded, force-processing is set because there might be
        # a change in the geofabrik file
        """
        if self.check_file(GEOFABRIK_PATH) is True or \
                self.force_download is True:
            log.info('# Need to download geofabrik file')

            return True

        return False

    def download_geofabrik_file(self):
        """
        download geofabrik file
        """
        download_file(GEOFABRIK_PATH,
                      'https://download.geofabrik.de/index-v1.json')

        log.info('+ download geofabrik.json file: OK')

    def check_land_polygons_file(self):
        """
        check land_polygons file if not existing or are not up-to-date
        """

        if self.check_file(LAND_POLYGONS_PATH) is True or \
                self.force_download is True:
            log.info('+ Need to download land polygons file')
            self.need_to_dl.append('land_polygons')

    def download_files_if_needed(self):
        """
        check land_polygons and OSM map files if not existing or are not up-to-date
        and download if needed
        """
        if 'land_polygons' in self.need_to_dl:
            download_file(LAND_POLYGONS_PATH,
                          'https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip')

        # log.info('+ download land_polygons.shp file: OK')

        if 'osm_pbf' in self.need_to_dl:
            self.download_osm_pbf_file()

    def check_file(self, target_filepath):
        """
        check if given file is up-to-date. When force_download is set the
        existing copy is removed so the next GET fetches a full body;
        otherwise we keep the file in place and let the conditional GET in
        download_url_to_file send If-Modified-Since / If-None-Match so the
        server can reply 304 when nothing changed.
        """

        need_to_download = False
        logging_filename = target_filepath.rsplit('/', 1)[-1]

        log.info('-' * 80)
        log.info('# check %s file', logging_filename)

        try:
            if self.should_file_be_downloaded(target_filepath):
                if self.force_download:
                    log.info('+ Force-download: deleting old %s file', logging_filename)
                    os.remove(target_filepath)
                else:
                    log.info('+ %s is older than %d days; will revalidate',
                             logging_filename, self.max_days_old)
                need_to_download = True

        except FileNotFoundError:
            need_to_download = True

        if not os.path.exists(target_filepath) or \
                not os.path.isfile(target_filepath):
            need_to_download = True

            log.info('+ %s file needs to be downloaded', logging_filename)

        return need_to_download

    def check_osm_pbf_file(self):
        """
        check if the relevant countries' OSM files are up-to-date
        """

        log.info('-' * 80)
        log.info('# check countries .osm.pbf files')

        # Check for expired maps and delete them
        log.info('+ Checking for old maps and remove them')

        for country in self.border_countries:
            # check for already existing .osm.pbf file
            expected_map_location = build_osm_pbf_filepath(country)
            log.debug(
                ' Checking for map at filepath: %s',expected_map_location)
            map_file_path = glob.glob(expected_map_location)

            if len(map_file_path) != 1:
                map_file_path = glob.glob(
                    f'{USER_MAPS_DIR}/**/{country}-latest.osm.pbf')

            # mark .osm.pbf file for revalidation if out of date. Only delete
            # on force_download; otherwise the conditional GET will decide.
            if len(map_file_path) == 1 and os.path.isfile(map_file_path[0]):
                if self.should_file_be_downloaded(map_file_path[0]):
                    if self.force_download:
                        log.info('+ Force-download: deleting mapfile for %s', country)
                        os.remove(map_file_path[0])
                    else:
                        self.border_countries[country] = {
                            'map_file': map_file_path[0]}
                        log.info(
                            '+ mapfile for %s: stale, will revalidate', country)
                    self.need_to_dl.append('osm_pbf')
                else:
                    self.border_countries[country] = {
                        'map_file': map_file_path[0]}
                    log.info(
                        '+ mapfile for %s: up-to-date.', country)

            # mark country .osm.pbf file for download if there exists no file or it is no file
            map_file_path = self.border_countries[country].get('map_file')
            if map_file_path is None or (not os.path.isfile(map_file_path) or self.force_download):
                self.border_countries[country]['download'] = True
                self.need_to_dl.append('osm_pbf')

    def download_osm_pbf_file(self):
        """
        download countries' OSM files in parallel (capped to
        MAX_PARALLEL_DOWNLOADS to play nice with Geofabrik)
        """
        pending = []
        for country, item in self.border_countries.items():
            try:
                if item['download'] is True:
                    map_file_path = build_osm_pbf_filepath(country)
                    url = self.o_geofabrik_json.get_geofabrik_url(country)
                    pending.append((country, map_file_path, url))
            except KeyError:
                pass

        if not pending:
            return

        def _fetch(work):
            country, path, url = work
            download_file(path, url)
            return country, path

        max_workers = min(MAX_PARALLEL_DOWNLOADS, len(pending))
        if max_workers <= 1:
            for work in pending:
                country, path = _fetch(work)
                self.border_countries[country] = {'map_file': path}
            return

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for country, path in ex.map(_fetch, pending):
                self.border_countries[country] = {'map_file': path}

    def should_file_be_downloaded(self, file_path):
        """
        check if given file should be downloaded
        - older that max_days old OR
        - force_download is set
        """

        chg_time = os.path.getmtime(file_path)

        return bool(older_than_x_days(chg_time, self.max_days_old) or self.force_download is True)
