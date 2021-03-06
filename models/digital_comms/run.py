"""Digital demand dummy model
"""
import configparser
import csv
import os

import fiona  # type: ignore
import numpy as np  # type: ignore

from digital_comms.fixed_network.model import NetworkManager, Exchange
from digital_comms.runner import read_csv, read_assets, read_links

from typing import List

from digital_comms.fixed_network.adoption import update_adoption_desirability

from smif.model.sector_model import SectorModel  # type: ignore
from smif.data_layer import DataHandle

class DigitalCommsWrapper(SectorModel):
    """Digital model
    """
    def __init__(self, name):
        super().__init__(name)
        self.system = None # type: NetworkManager

    def before_model_run(self, data_handle : DataHandle):
        """Implement this method to conduct pre-model run tasks

        Arguments
        ---------
        data_handle: smif.data_layer.DataHandle
            Access parameter values (before any model is run, no dependency
            input data or state is guaranteed to be available)
        """
        self.system = self.load_network(data_handle)

    def load_network(self, data_handle: DataHandle) -> NetworkManager:
        """Implement this method to conduct pre-model run tasks

        Arguments
        ---------
        data_handle: smif.data_layer.DataHandle
            Access parameter values (before any model is run, no dependency
            input data or state is guaranteed to be available)
        """
        # Get wrapper configuration
        path_main = os.path.dirname(os.path.abspath(__file__))
        config = configparser.ConfigParser()
        config.read(os.path.join(path_main, 'wrapperconfig.ini'))
        data_path = config['PATHS']['path_local_data']

        # Get modelrun configuration
        read_only_parameters = data_handle.get_parameters()

        parameters = {}
        for name, data_array in read_only_parameters.items():
            parameters[name] = float(data_array.data)

        self.logger.debug(parameters)

        # Load assets
        assets = read_assets(data_path)

        # Load links
        links = read_links(data_path)

        return NetworkManager(assets, links, parameters)


    def update_adoption_desirability(self, data_handle):

        annual_adoption_rate = data_handle.get_data('adoption').data

        # get adoption desirability from previous timestep
        adoption_desirability = [
            distribution for distribution in self.system._distributions
            if distribution.adoption_desirability]

        adoption_desirability_percentage = (
            len([dist.total_prems for dist in adoption_desirability]) /
            len([dist.total_prems for dist in self.system._distributions]) * 100)

        percentage_annual_increase = float(annual_adoption_rate - \
            adoption_desirability_percentage)

        # update the number of premises wanting to adopt (adoption_desirability)
        desirability_ids = update_adoption_desirability(
            self.system._distributions, percentage_annual_increase)

        self.system.update_adoption_desirability(desirability_ids)


    def compute_spend(self):
        return 0


    def save_exchange_attribute(self,
                                technologies : List,
                                exchanges : List,
                                attribute : str):
        """Save an attribute of an Exchange object to smif results

        Arguments
        ---------
        technologies : list
            The list of technology names
        exchanges : list
            A list of exchange names
        attribute : str
            The attribute to get from the digital comms model and save to disk

        Returns
        -------
        numpy.ndarray
        """
        num_technologies = len(technologies)
        num_exchanges = len(exchanges)

        # Create an empty array of the correct dimensions
        array = np.zeros((num_technologies, num_exchanges), dtype=np.float)

        # Iterate through the technologies and exchanges and get the attribute
        for i, technology in enumerate(technologies):
            for j, exchange_id in enumerate(exchanges):
                xchange = [exchange for exchange in self.system._exchanges
                                       if exchange.id == exchange_id][0]

                value = getattr(xchange, attribute)[technology]
                array[i, j] = value
        return array

    def save_decision_metrics(self, data_handle : DataHandle):
        """Compute decision metrics for the current system and save to disk

        Expects outputs for this wrapper to be defined with the same name as the
        list of attributed below

        Arguments
        ---------
        data_handle
        """
        technologies = self.outputs['rollout_costs'].dim_coords('technology').ids
        exchanges = self.outputs['rollout_costs'].dim_coords('exchanges').ids

        attributes = ['rollout_costs',
                      'rollout_bcr',
                      'total_potential_benefit',
                      'total_potential_bcr']

        for attribute in attributes:
            data = self.save_exchange_attribute(technologies,
                                                exchanges,
                                                attribute)
            data_handle.set_results(attribute, data)

    def simulate(self, data_handle : DataHandle):
        """Implement smif.SectorModel simulate
        """
        # -----
        # Start
        # -----
        now = data_handle.current_timestep
        total_cost = 0

        interventions = data_handle.get_current_interventions()

        dc_assets = []

        for name, intervention in interventions.items():
            if intervention['build_year'] == now:
                technology = intervention['technology']
                asset_id = intervention['id']
                exchange = [exchange for exchange in self.system._exchanges
                            if exchange.id == asset_id][0]
                total_cost += exchange.rollout_costs[technology]

                asset = (intervention['id'],
                        intervention['technology'])
                dc_assets.append(asset)

        self.logger.debug(self.system.capacity('exchange'))

        data_handle.set_results('total_cost', total_cost)

        self.logger.debug("Upgrading dc assets with %s", dc_assets)
        self.system.upgrade(dc_assets)

        self.logger.debug(self.system.capacity('exchange'))

        adoption = self.update_adoption_desirability(data_handle)

        self.save_decision_metrics(data_handle)

        # -------------
        # Write outputs
        # -------------
        lad_names = self.outputs['lad_premises_with_fttp'].dim_coords('lad_uk_2016').ids
        num_lads = len(lad_names)
        num_fttp = np.zeros((num_lads))
        num_fttdp = np.zeros((num_lads))
        num_fttc = np.zeros((num_lads))
        num_adsl = np.zeros((num_lads))

        coverage = self.system.coverage()
        for i, lad in enumerate(lad_names):
            if lad not in coverage:
                continue
            stats = coverage[lad]
            num_fttp[i] = stats['num_fttp']
            num_fttdp[i] = stats['num_fttdp']
            num_fttc[i] = stats['num_fttc']
            num_adsl[i] = stats['num_adsl']

        data_handle.set_results('lad_premises_with_fttp', num_fttp)
        data_handle.set_results('lad_premises_with_fttdp', num_fttdp)
        data_handle.set_results('lad_premises_with_fttc', num_fttc)
        data_handle.set_results('lad_premises_with_adsl', num_adsl)

        aggregate_coverage = self.system.aggregate_coverage('lad')

        perc_fttp = np.zeros((num_lads))
        perc_fttdp = np.zeros((num_lads))
        perc_fttc = np.zeros((num_lads))
        perc_docsis3 = np.zeros((num_lads))
        perc_adsl = np.zeros((num_lads))
        sum_of_premises = np.zeros((num_lads))

        for i, lad in enumerate(lad_names):
            if lad not in aggregate_coverage:
                continue
            datum = aggregate_coverage[lad]
            perc_fttp[i] = datum['percentage_of_premises_with_fttp']
            perc_fttdp[i] = datum['percentage_of_premises_with_fttdp']
            perc_fttc[i] = datum['percentage_of_premises_with_fttc']
            perc_docsis3[i] = datum['percentage_of_premises_with_docsis3']
            perc_adsl[i] = datum['percentage_of_premises_with_adsl']
            sum_of_premises[i] = datum['sum_of_premises']

        data_handle.set_results('percentage_of_premises_connected_with_fttp', perc_fttp)
        data_handle.set_results('percentage_of_premises_connected_with_fttdp', perc_fttdp)
        data_handle.set_results('percentage_of_premises_connected_with_fttc', perc_fttc)
        data_handle.set_results('percentage_of_premises_connected_with_docsis3', perc_docsis3)
        data_handle.set_results('percentage_of_premises_connected_with_adsl', perc_adsl)

        # capacity = self.system.capacity('lad')
        # spend = self.compute_spend()
