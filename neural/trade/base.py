from abc import ABC
from typing import List
import pickle
import tarfile

import numpy as np
import torch
from torch import nn

from neural.client.alpaca import AbstractTradeClient, AbstractDataClient
from neural.data.base import DatasetMetadata
from neural.data.base import AsyncDataFeeder
from neural.env.base import TradeMarketEnv, TrainMarketEnv
from neural.meta.pipe import AbstractPipe
from neural.meta.agent import Agent



class AbstractTrader(ABC):

    """
    Abstract base class for defining a trader that can execute orders based on model actions.
    This trader requires a client to connect to a trading environment, a model to generate
    actions, a data pipe to feed data to the model, and metadata for the dataset being used
    to create aggregated data stream matching the training data.
    """  

    def __init__(self,
        trade_client: AbstractTradeClient,
        data_client: AbstractDataClient,
        agent: Agent,
        warmup_env: TrainMarketEnv = None):

        """
        Initializes an AbstractTrader object.

        Args:
            client (AbstractClient): An instance of the client to connect to the trading environment.
            model (nn.Module): A PyTorch model used to generate actions for the trader.
            pipe (AbstractPipe): An instance of the data pipe used to feed data to the model.
            dataset_metadata (DatasetMetadata): Metadata for the dataset being used for training and validation.
        """

        self.trade_client = trade_client
        self.data_client = data_client
        self.agent = agent
        self.data_feeder = self._get_data_feeder()


        return None


    def _get_data_feeder(self):

        stream_metadata = self.agent.dataset_metadata.stream
        data_feeder = AsyncDataFeeder(stream_metadata, self.data_client)

        return data_feeder


    def apply_rules(self, *args, **kwargs):

        """
        Applies trading rules to the trades. Override this method to apply custom rules
        before placing orders. This allows rule based trading to complement the model based
        trading. For example, a rule could be to only buy a stock if it has a positive
        sentiment score. Or execute a techinical analysis strategy whenever a condition is met
        to override the normal behavior of the model.

        Raises:
            NotImplementedError: This method must be implemented by a subclass.
        """

        raise NotImplementedError
    

    def no_short(self, quantities: np.ndarray):

        # Due to rounding errors it is is possible that short positions are created
        # with a very small fractional amount however it will have the same ramifications
        # as a normal short position. This method will modify quantities at order time
        # to ensure that not short positions are created.

        held_quantities = self.trade_client.asset_quantities
        available_quantities = np.where(held_quantities <= 0, 0, held_quantities)
        quantities = min(abs(quantities), available_quantities)

        return quantities
    
    def no_margin(self, quantities: np.ndarray, cash_ratio_threshold: float = 0.1):

        # due to slippage it is possible that margin trading can happen, even when 
        # no margin occurrs that time of placing orders.the way to 
        # prevent this practically is to allow a minimum amount of cash to be held
        # at all times. This method will modify quantities at order time to ensure
        # that if cash falls below a certain threshold all buy orders will be nullified
        # Note if margin trading is a concern, it is recommended to set the margin
        # parameter to a relatively high value.

        cash_ratio = self.trade_client.cash/self.data_client.net_worth
        if cash_ratio < cash_ratio_threshold:
            quantities = np.where(quantities > 0, 0, quantities)
        
        return quantities


    def place_orders(
        self, 
        actions: np.ndarray, 
        *args, 
        **kwargs):
        """
        Takes actions from the model and places relevant orders.

        Args:
            actions (np.ndarray): A 2D numpy array of actions generated by the model.

        Raises:
            NotImplementedError: This method must be implemented by a subclass.
        """
        # Get the list of symbols from the dataset metadata

        symbols = self.agent.dataset_metadata.symbols

        # Loop over the symbols and actions and place orders for each symbol
        for symbol, quantity in zip(symbols, actions):
            self.trade_client.place_order(symbol, actions, *args, **kwargs)


    def trade(self):

        """
        Starts the trading process by creating a trading environment and executing
        actions from the model.

        Raises:
            NotImplementedError: This method must be implemented by a subclass.
        """

        self.trade_market_env = TradeMarketEnv(trader=self)
        self._get_data_feeder()
        self.agent.trade(self.trade_market_env)

        return None