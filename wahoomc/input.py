"""
functions and object for processing input via CLI
"""
#!/usr/bin/python

# import official python packages
import argparse
import os
import sys

# import custom python packages
from wahoomc.geofabrik_json import CountyIsNoGeofabrikCountry
from wahoomc.geofabrik import CountryGeofabrik


def process_call_of_the_tool():
    """
    process CLI arguments
    """
    desc = "Create up-to-date maps for your Wahoo ELEMNT and Wahoo ELEMNT BOLT"
    parser = argparse.ArgumentParser(
        description=desc, formatter_class=argparse.RawTextHelpFormatter)

    # group: primary input parameters to create map for. One needs to be given
    primary_args = parser.add_argument_group(
        title='Primary input', description='Generate maps for...')
    primary_args_excl = primary_args.add_mutually_exclusive_group(required=True)
    primary_args_excl.add_argument(
        "-co", "--country",
        help="country to generate maps for.\nExample: -co malta, multiple countries separated by comma: -co malta,italy")
    primary_args_excl.add_argument(
        "-xy", "--xy_coordinates",
        help="x/y coordinates to generate maps for.\nExample: -xy 133/88, multiple xy coordinates separated by comma: -xy 133/88,134/89")

    # group: options for map generation
    options_args = parser.add_argument_group(
        title='Options', description='Options for map generation')
    options_args.add_argument('-md', '--maxdays', type=int, default=InputData().max_days_old,
                              help="maximum age of source maps and other files")
    options_args.add_argument('-nbc', '--bordercountries', action='store_false',
                              help="do not process border countries of tiles involving more than one country")
    options_args.add_argument('-con', '--contour', action='store_true',
                              help="process contour lines (elevation data)")
    options_args.add_argument('-srtm1', '--use_srtm1', action='store_true',
                              help="use srtm1 as source for contour lines (elevation data)")
    options_args.add_argument('-fd', '--forcedownload', action='store_true',
                              help="force download of files")
    options_args.add_argument('-fp', '--forceprocessing', action='store_true',
                              help="force processing of files")
    options_args.add_argument('-c', '--cruiser', action='store_true',
                              help="save uncompressed maps for Cruiser")
    options_args.add_argument('-tag', '--tag_wahoo_xml', default=InputData().tag_wahoo_xml,
                              help="file with tags to keep in the output")
    options_args.add_argument('-z', '--zip', action='store_true',
                              help="zip the country (and country-maps) folder")
    options_args.add_argument('-v', '--verbose', action='store_true',
                              help="output debug logger messages")
    options_args.add_argument('-hdd', '--hdd_mode', action='store_true',
                              help="use mapwriter hdd mode")
    options_args.add_argument('-j', '--jobs', type=int, default=InputData().jobs,
                              help="number of parallel workers for per-tile processing (0 = auto)")
    options_args.add_argument('-ci', '--cleanup_intermediate', action='store_true',
                              help="delete per-tile split-*.osm.pbf intermediates after merge")

    args = parser.parse_args()

    o_input_data = InputData()
    o_input_data.country = args.country
    o_input_data.xy_coordinates = args.xy_coordinates
    o_input_data.max_days_old = args.maxdays

    o_input_data.process_border_countries = args.bordercountries
    o_input_data.contour = args.contour
    o_input_data.use_srtm1 = args.use_srtm1

    o_input_data.force_download = args.forcedownload
    o_input_data.force_processing = args.forceprocessing

    o_input_data.tag_wahoo_xml = args.tag_wahoo_xml
    o_input_data.save_cruiser = args.cruiser
    o_input_data.zip_folder = args.zip

    o_input_data.verbose = args.verbose
    o_input_data.hdd_mode = args.hdd_mode
    o_input_data.jobs = args.jobs
    o_input_data.cleanup_intermediate = args.cleanup_intermediate

    return o_input_data


def cli_init():
    """
    Provides cli for initialization of user directory
    """

    parser = argparse.ArgumentParser(
        description='Copy config files to user directory')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="output debug logger messages")

    args = parser.parse_args()

    o_input_data = InputData()
    o_input_data.verbose = args.verbose

    return o_input_data


class InputData():  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """
    object with all parameters to process maps and default values
    """

    def __init__(self):
        self.country = ""
        self.xy_coordinates = ""
        self.max_days_old = 14

        self.force_download = False
        self.force_processing = False
        self.process_border_countries = True
        self.contour = False
        self.use_srtm1 = False

        self.tag_wahoo_xml = "tag-wahoo-poi.xml"
        self.zip_folder = False
        self.save_cruiser = False
        self.hdd_mode = False

        self.jobs = 0  # 0 means auto: max(1, cpu_count - 1)
        self.cleanup_intermediate = False

        self.verbose = False

    def is_required_input_given_or_exit(self, issue_message):
        """
        check that the minimal required arguments are given:
        - country, or
        - x/y coordinates
        """
        if (self.country in ('None', '') and self.xy_coordinates in ('None', '')):
            if issue_message:
                sys.exit("Nothing to do. Start with -h or --help to see command line options.")
            else:
                sys.exit()
        elif self.country and self.xy_coordinates:
            sys.exit(
                "Country and X/Y coordinates are given. Only one of both is allowed!")
        elif self.country:
            try:
                CountryGeofabrik.split_input_to_list(self.country)
            except CountyIsNoGeofabrikCountry as exception:
                sys.exit(exception)
            return True
        else:
            return True
