"""Digital demand dummy model
"""
import configparser
import csv
import os


import fiona  # type: ignore
import numpy as np  # type: ignore

from digital_comms.fixed_network.model import NetworkManager
from digital_comms.fixed_network.interventions import decide_interventions
from digital_comms.fixed_network.adoption import update_adoption_desirability
from digital_comms.runner import read_csv, read_assets, read_links

from smif.model.sector_model import SectorModel  # type: ignore
import smif


# configure profiling with environment variable
PROFILE = False
if 'PROFILE_DC' in os.environ and os.environ['PROFILE_DC'] == "1":
    PROFILE = True
    try:
        from memory_profiler import profile
        from pyinstrument import Profiler
    except ImportError:
        pass


def memprofile(func):
    """Decorator - profile memory usage if profiling is enabled
    """
    def wrapper(*args, **kwargs):
        if PROFILE:
            profile(func, precision=1)(*args, **kwargs)
        else:
            func(*args, **kwargs)
    return wrapper


def cpuprofile(func):
    """Decorator - profile cpu usage
    """
    def wrapper(*args, **kwargs):
        if PROFILE:
            profiler = Profiler()
            profiler.start()
        func(*args, **kwargs)
        if PROFILE:
            profiler.stop()
            print(profiler.output_text(unicode=False, color=True))
    return wrapper


class DigitalCommsWrapper(SectorModel):
    """Digital model
    """
    def __init__(self, name):
        super().__init__(name)
        self.system = None

    @cpuprofile
    @memprofile
    def before_model_run(self, data_handle : smif.data_layer.DataHandle):
        """Implement this method to conduct pre-model run tasks

        Arguments
        ---------
        data_handle: smif.data_layer.DataHandle
            Access parameter values (before any model is run, no dependency
            input data or state is guaranteed to be available)
        """
        print('before model run')

        # Get wrapper configuration
        path_main = os.path.dirname(os.path.abspath(__file__))
        config = configparser.ConfigParser()
        config.read(os.path.join(path_main, 'wrapperconfig.ini'))
        data_path = config['PATHS']['path_local_data']

        # Get modelrun configuration
        read_only_parameters = data_handle.get_parameters()

        parameters = {}
        for name, dataarray in read_only_parameters.items():
            parameters[name] = dataarray.data

        self.logger.debug(parameters)

        # Load assets
        assets = read_assets(data_path)

        # Load links
        links = read_links(data_path)

        self.logger.info("DigitalCommsWrapper - Intitialise system")
        self.system = NetworkManager(assets, links, parameters)

        print('only distribution points with a benefit cost ratio > 1 can be upgraded')
        print('model rollout is constrained by the adoption desirability set by scenario')

    @cpuprofile
    @memprofile
    def simulate(self, data_handle : smif.data_layer.DataHandle):
        """Implement smif.SectorModel simulate
        """
        # -----
        # Start
        # -----
        data_handle = data_handle
        now = data_handle.current_timestep
        self.logger.info("DigitalCommsWrapper received inputs in %s", now)

        # Set global parameters
        technology_strategy = data_handle.get_parameter('technology_strategy').data

        # -----------------------
        # Get scenario adoption rate
        # -----------------------
        annual_adoption_rate = data_handle.get_data('adoption')
        adoption_desirability = [
            premise
            for premise in self.system._premises
            if premise.adoption_desirability is True
        ]
        total_premises = [premise for premise in self.system._premises]
        adoption_desirability_percentage = (
            len(adoption_desirability) / len(total_premises) * 100)
        percentage_annual_increase = annual_adoption_rate - adoption_desirability_percentage
        percentage_annual_increase = round(float(percentage_annual_increase), 1)

        # -----------------------
        # Run fixed network model
        # -----------------------
        self.logger.info("DigitalCommsWrapper - Update adoption status on premises")
        self.system.update_adoption_desirability = update_adoption_desirability(
            self.system, percentage_annual_increase)
        premises_adoption_desirability_ids = self.system.update_adoption_desirability

        adoption_cap = len(premises_adoption_desirability_ids) + \
            sum(getattr(premise, technology) for premise in self.system._premises)

        # TODO: Move this into decision module
        self.logger.info("DigitalCommsWrapper - Decide interventions")
        interventions = decide_interventions(
            self.system,
            now,
            technology,
            policy,
            data_handle.get_parameter('annual_budget'),
            adoption_cap,
            data_handle.get_parameter('subsidy'),
            data_handle.get_parameter('telco_match_funding'),
            data_handle.get_parameter('service_obligation_capacity'),
        )

        self.logger.info("DigitalCommsWrapper - Upgrading system")
        self.system.upgrade(interventions)

        # -------------
        # Write outputs
        # -------------
        # TODO: Change this into set_results calls
        interventions_lut = {intervention[0]: intervention for intervention in interventions}

        distribution_upgrades = np.empty(
            (self.system.number_of_assets['distributions'], 1))
        distribution_names = data_handle.get_region_names('broadband_distributions')
        for idx, distribution in enumerate(distribution_names):
            distribution_upgrades[idx, 0] = \
                interventions_lut[distribution][2] if distribution in interventions_lut else 0
        data_handle.set_results('distribution_upgrades', distribution_upgrades)

        premises_by_distribution = np.empty((self.system.number_of_assets['distributions'], 1))
        for idx, distribution in enumerate(self.system.assets['distributions']):
            premises_by_distribution[idx, 0] = len(distribution._clients)
        data_handle.set_results('premises_by_distribution', premises_by_distribution)

        print("* {} premises adoption desirability is {}".format(
            technology, (len(premises_adoption_desirability_ids))))
        premises_wanting_to_adopt = np.empty((1, 1))
        premises_wanting_to_adopt[0, 0] = len(premises_adoption_desirability_ids)
        data_handle.set_results('premises_adoption_desirability', premises_wanting_to_adopt)

        distribution_upgrade_costs = ('distribution_upgrade_costs_' + str(technology))
        distribution_upgrade_costs = np.empty(
            (self.system.number_of_assets['distributions'], 1))
        for idx, distribution in enumerate(self.system.assets['distributions']):
            distribution_upgrade_costs[idx, 0] = distribution.upgrade_costs[technology]
        data_handle.set_results(('distribution_upgrade_costs_' +
                                 str(technology)), distribution_upgrade_costs)

        upgrade_cost_per_premises = ('upgrade_cost_per_premises_' + str(technology))
        upgrade_cost_per_premises = np.empty(
            (self.system.number_of_assets['distributions'], 1))
        for idx, distribution in enumerate(self.system.assets['distributions']):
            if distribution._clients:
                upgrade_cost_per_premises[idx, 0] = \
                    distribution.upgrade_costs[technology] / len(distribution._clients)
            else:
                upgrade_cost_per_premises[idx, 0] = 0
        data_handle.set_results(('premises_upgrade_costs_' + str(technology)),
                                upgrade_cost_per_premises)

        # premises passed
        premises_passed = ('premises_passed_with_' + str(technology))
        premises_passed = np.empty((1, 1))
        premises_passed[0, 0] = sum(getattr(premise, technology)
                                    for premise in self.system._premises)
        print("* {} premises passed {}".format(technology, premises_passed))
        data_handle.set_results(('premises_passed_with_' + str(technology)), premises_passed)

        percentage_of_premises_passed = ('percentage_of_premises_passed_with_' + str(technology))
        percentage_of_premises_passed = np.empty((1, 1))
        percentage_of_premises_passed[0, 0] = round(
            (
                sum(getattr(premise, technology) for premise in self.system._premises)
                / len(self.system._premises)
                * 100
            ),
            2)
        print("* {} percentage of premises passed {}".format(
            technology, percentage_of_premises_passed))
        data_handle.set_results(
            'percentage_of_premises_passed_with_' + str(technology),
            percentage_of_premises_passed)

        # premises connected
        premises_connected = ('premises_connected_with_' + str(technology))
        premises_connected = np.empty((1, 1))
        premises_connected[0, 0] = sum(
            getattr(premise, technology)
            for premise in self.system._premises
            if premise.adoption_desirability
        )
        print("* {} premises connected {}".format(technology, premises_connected))
        data_handle.set_results(('premises_connected_with_' + str(technology)), premises_connected)

        percentage_of_premises_connected = (
            'percentage_of_premises_connected_with_' + str(technology))
        percentage_of_premises_connected = np.empty((1, 1))
        percentage_of_premises_connected[0, 0] = round(
            (
                sum(
                    getattr(premise, technology)
                    for premise in self.system._premises
                    if premise.adoption_desirability
                )
                / len(self.system._premises)
                * 100
            ),
            2)
        print("* {} percentage of premises connected {}".format(
            technology, percentage_of_premises_connected))
        data_handle.set_results(('percentage_of_premises_connected_with_' + str(technology)),
                                percentage_of_premises_connected)

        # Regional output
        lad_names = self.get_region_names('lad2016')
        num_lads = len(lad_names)
        num_fttp = np.zeros((num_lads, 1))
        num_fttdp = np.zeros((num_lads, 1))
        num_fttc = np.zeros((num_lads, 1))
        num_adsl = np.zeros((num_lads, 1))

        coverage = self.system.coverage()
        for i, lad in enumerate(lad_names):
            if lad not in coverage:
                continue
            stats = coverage[lad]
            num_fttp[i, 0] = stats['num_fttp']
            num_fttdp[i, 0] = stats['num_fttdp']
            num_fttc[i, 0] = stats['num_fttc']
            num_adsl[i, 0] = stats['num_adsl']

        data_handle.set_results('lad_premises_with_fttp', num_fttp)
        data_handle.set_results('lad_premises_with_fttdp', num_fttdp)

        # get cambridge exchange data
        if policy == 'fttp_rollout_per_distribution' and technology == 'fttp':

            path_main = os.path.dirname(os.path.abspath(__file__))
            config = configparser.ConfigParser()
            config.read(os.path.join(path_main, 'wrapperconfig.ini'))
            base_path = config['PATHS']['path_export_data']

            def csv_writer(data, filename, fieldnames):
                with open(os.path.join(base_path, filename), 'w') as csv_file:
                    writer = csv.DictWriter(csv_file, fieldnames, lineterminator='\n')
                    writer.writeheader()
                    writer.writerows(data)

            def write_out_upgrades(data):
                export_data = []
                for datum in data:
                    export_data.append({
                        'id': datum.id,
                        'upgrade': datum.fttp,
                        'year': now
                    })
                return export_data

            # get exchanges
            exchange = [
                exchange
                for exchange in self.system._exchanges
                if exchange.id == 'exchange_EACAM'
            ][0]

            # get cabinets
            cabinets = exchange._clients
            cabinet_export_data = write_out_upgrades(cabinets)

            # get distributions
            distributions = []
            for cabinet in cabinets:
                distributions.extend(cabinet._clients)
            distribution_export_data = write_out_upgrades(distributions)

            # get premises
            premises = []
            for distribution in distributions:
                premises.extend(distribution._clients)

            premises_export_data = []
            for premise in premises:
                premises_export_data.append({
                    'id': premise.id,
                    'adoption_desirability': premise.adoption_desirability,
                    'premises_passed': premise.fttp,
                    'year': now
                })

            # get exchange to cabinet links
            exchange_to_cabinet_links = [
                link
                for link in self.system._links_from_cabinets
                if link.dest == 'exchange_EACAM'
            ]

            # get cabinet to dist point links
            cab_to_dist_point_links = exchange_to_cabinet_links.origin

            # get distributions
            cab_to_dist_point_links = []
            for link in cab_to_dist_point_links:
                cab_to_dist_point_links.extend(link.origin)
            print(cab_to_dist_point_links)

            # set fieldnames
            generic_fieldnames = ['id', 'upgrade', 'year']
            premises_fieldnames = ['id', 'adoption_desirability', 'premises_passed', 'year']

            # write out
            csv_writer(
                cabinet_export_data,
                'cabinet_data{}.csv'.format(now),
                generic_fieldnames)
            csv_writer(
                distribution_export_data,
                'distribution_data{}.csv'.format(now),
                generic_fieldnames)
            csv_writer(
                premises_export_data,
                'premises_data{}.csv'.format(now),
                premises_fieldnames)

        # ----
        # Exit
        # ----
        self.logger.info("DigitalCommsWrapper produced outputs in %s", now)


def read_shapefile(file):
    """Read properties for all features in a shapefile
    """
    with fiona.open(file, 'r') as source:
        return [f['properties'] for f in source]
