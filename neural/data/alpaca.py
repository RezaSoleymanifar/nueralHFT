from datetime import datetime
from typing import (List, Tuple, Any)
import os

from alpaca.trading.enums import AssetClass, AssetStatus
import pandas as pd
import numpy as np

from alpaca.trading.enums import AssetClass, AssetStatus

from alpaca.data.requests import (
    CryptoBarsRequest,
    CryptoQuotesRequest,
    CryptoTradesRequest,
    StockBarsRequest,
    StockQuotesRequest,
    StockTradesRequest
)

from neural.common import logger
from neural.data.enums import DatasetType, DatasetMetadata
from neural.client.alpaca import AlpacaClient
from neural.tools.base import (progress_bar, to_timeframe, 
    create_column_schema, validate_path)
from neural.tools.base import Calendar
from neural.common.constants import HDF5_DEFAULT_MAX_ROWS
    

class AlpacaDataFetcher():

    """
    A class to download and process financial data using the Alpaca API.

    The AlpacaDataFetcher class handles validation of symbols and resolutions,
    data downloading, and data processing tasks. It works in conjunction with
    the AlpacaClient class to fetch the required data from the Alpaca API
    and process it for further use.
    """

    def __init__(
        self,
        client: AlpacaClient
    ) -> None:
        """
        Initializes the AlpacaDataFetcher class.

        Args:
            client (AlpacaClient): An instance of the AlpacaClient class.

        Returns:
            None
        """

        self.client = client

        return None

    def _validate_resolution(self, resolution):
        """
        Validates the resolution of the dataset.

        Parameters:
        resolution (str): The resolution of the dataset.

        Returns:
        None.

        Raises:
        ValueError: If the resolution is not one of the accepted resolutions.
        """

        accepted_resolutions = {'1Min', '5Min', '15Min', '30Min'}

        if resolution not in accepted_resolutions:
            raise ValueError(f'Accepted resolutions: {accepted_resolutions}.')

        return

    def _validate_symbols(self, symbols: List[str]):
        """
        Validates the list of symbols.

        Args:
        - symbols (List[str]): The list of symbols to validate.

        Returns:
        - str: The asset class of the symbols.

        Raises:
        - ValueError: If the symbols argument is an empty sequence.
                      If any symbols have duplicate values.
                      If any symbol is not a known symbol.
                      If any symbol is not a tradable symbol.
                      If any symbol is not an active symbol.
                      (warning only) if any symbol is not a fractionable symbol.
                      (warning only) if any symbol is not easy to borrow (ETB).
                      If the symbols are not of the same asset class.
        """

        if len(symbols) == 0:
            raise ValueError('symbols argument cannot be an empty sequence.')

        duplicate_symbols = [
            symbol for symbol in set(symbols) if symbols.count(symbol) > 1]

        if duplicate_symbols:
            raise ValueError(
                f'Symbols {duplicate_symbols} have duplicate values.')

        for symbol in symbols:

            symbol_data = self.client._AlpacaClient__symbols.get(symbol)

            if symbol_data is None:
                raise ValueError(f'Symbol {symbol} is not a known symbol.')

            if not symbol_data.tradable:
                raise ValueError(f'Symbol {symbol} is not a tradable symbol.')

            if symbol_data.status != AssetStatus.ACTIVE:
                raise ValueError(f'Symbol {symbol} is not an active symbol.')

            if not symbol_data.fractionable:
                logger.warning(
                    f'Symbol {symbol} is not a fractionable symbol.')

            if not symbol_data.easy_to_borrow:
                logger.warning(
                    f'Symbol {symbol} is not easy to borrow (ETB).')

        asset_classes = set(
            self.client._AlpacaClient__symbols.get(
                symbol).asset_class for symbol in symbols)

        # checks if symbols have the same asset class
        if len(asset_classes) != 1:
            raise ValueError('Symbols are not of the same asset class.')

        asset_class = asset_classes.pop()

        return asset_class

    def get_downloader_and_request(
        self,
        dataset_type: DatasetType,
        asset_class=AssetClass
    ) -> Tuple[Any, Any]:
        """
        Returns the appropriate data downloader and request object based on the provided dataset type
        and asset class.

        Parameters:
        -----------
        dataset_type: DatasetType
            The type of dataset being downloaded, one of ['BAR', 'QUOTE', 'TRADE'].
        asset_class: AssetClass, optional
            The asset class being downloaded, defaults to `AssetClass.US_EQUITY`.

        Returns:
        --------
        Tuple[Any, Any]
            A tuple containing the appropriate downloader and request objects.
        """

        client_map = {
            AssetClass.US_EQUITY: self.client.clients['stocks'],
            AssetClass.CRYPTO: self.client.clients['crypto']}

        client = client_map[asset_class]

        def safe_method_call(client, method_name):
            if hasattr(client, method_name):
                return getattr(client, method_name)
            else:
                raise AttributeError(
                    f"Client does not have method '{method_name}'")

        downloader_request_map = {
            DatasetType.BAR: {
                AssetClass.US_EQUITY: ('get_stock_bars', StockBarsRequest),
                AssetClass.CRYPTO: ('get_crypto_bars', CryptoBarsRequest)},
            DatasetType.QUOTE: {
                AssetClass.US_EQUITY: ('get_stock_quotes', StockQuotesRequest),
                AssetClass.CRYPTO: ('get_crypto_quotes', CryptoQuotesRequest)},
            DatasetType.TRADE: {
                AssetClass.US_EQUITY: ('get_stock_trades', StockTradesRequest),
                AssetClass.CRYPTO: ('get_crypto_trades', CryptoTradesRequest)}}

        downloader_method_name, request = downloader_request_map[dataset_type][asset_class]
        downloader = safe_method_call(
            client=client, method_name=downloader_method_name)

        return downloader, request

    def download_raw_dataset(
        self,
        dataset_type: DatasetType,
        symbols: List[str],
        asset_class: AssetClass,
        resolution: str,
        start: datetime,
        end: datetime,
    ) -> None:
        """
        Downloads raw dataset from the Alpaca API.

        Args:
            dataset_type (DatasetType): The type of dataset to download (bar, quote, or trade).
            symbols (List[str]): A list of symbols to download.
            asset_class (AssetClass): The asset class to download.
            resolution (str): The resolution of the dataset to download (e.g., "1Min").
            start (datetime): The start date and time of the dataset to download.
            end (datetime): The end date and time of the dataset to download.

        Returns:
            pd.DataFrame: The downloaded dataset as a pandas DataFrame.
        """

        resolution = to_timeframe(resolution)

        data_fetcher = AlpacaDataFetcher(self.client)

        downloader, request = data_fetcher.get_downloader_and_request(
            dataset_type=dataset_type,
            asset_class=asset_class)

        data = downloader(request(
            symbol_or_symbols=symbols,
            timeframe=resolution,
            start=start,
            end=end))

        try:
            data_df = data.df

        except KeyError:
            raise KeyError(f'No data in requested range {start}-{end}')

        return data.df

    def download_features_to_hdf5(
        self,
        file_path: str | os.PathLike,
        target_dataset_name: str,
        dataset_type: DatasetType,
        symbols: List[str],
        resolution: str,
        start_date: str | datetime,
        end_date: str | datetime
    ) -> DatasetMetadata:
        """
        Downloads financial features data for the given symbols and saves it in an HDF5 file format.
        
        Args:
            file_path (str | os.PathLike): The file path of the HDF5 file to save the data.
            target_dataset_name (str): The name of the dataset to create in the HDF5 file.
            dataset_type (DatasetType): The type of dataset to download. Either 'BAR', 'TRADE', or 'QUOTE'.
            symbols (List[str]): The list of symbol names to download features data for.
            resolution (str): The frequency at which to sample the data. One of '1Min', '5Min', '15Min', or '30Min'.
            start_date (str | datetime): The start date to download data for, inclusive. If a string, it should be in
                the format 'YYYY-MM-DD'.
            end_date (str | datetime): The end date to download data for, inclusive. If a string, it should be in
                the format 'YYYY-MM-DD'.
                
        Returns:
            metadata (DatasetMetadata): The metadata of the saved dataset.
        """

        validate_path(file_path=file_path)

        asset_class = self._validate_symbols(symbols)
        self._validate_resolution(resolution=resolution)

        calendar = Calendar(asset_class=asset_class)
        schedule = calendar.get_schedule(
            start_date=start_date, end_date=end_date)

        if len(schedule) == 0:
            raise ValueError(
                'No market hours in date range provided.')

        logger.info(
            f"Downloading dataset for {len(symbols)} symbols | resolution: {resolution} |"
            f" {len(schedule)} market days from {start_date} to {end_date}")

        # shows dataset download progress bar
        progress_bar_ = progress_bar(len(schedule))

        # fetches and saves data on a daily basis
        for market_open, market_close in schedule.values:

            raw_dataset = self.download_raw_dataset(
                dataset_type=dataset_type,
                symbols=symbols,
                asset_class=asset_class,
                resolution=resolution,
                start=market_open,
                end=market_close)

            # check for missing symbols
            dataset_symbols = raw_dataset.index.get_level_values(
                'symbol').unique().tolist()
            missing_symbols = set(dataset_symbols) ^ set(symbols)

            if missing_symbols:
                raise ValueError(
                    f'No data for symbols {missing_symbols} in {market_open}, {market_close} time range.')

            # reordering rows to symbols. API does not maintain symbol order.
            raw_dataset = raw_dataset.reindex(
                index=pd.MultiIndex.from_product([
                    symbols, raw_dataset.index.levels[1]]))

            # resets multilevel symbol index
            raw_dataset = raw_dataset.reset_index(level=0, names='symbol')

            processed_groups = list()
            # raw data is processed symbol by symbol
            for symbol, group in raw_dataset.groupby('symbol'):

                processed_group = DataProcessor.reindex_and_forward_fill(
                    data=group, open=market_open,
                    close=market_close, resolution=resolution)

                processed_groups.append(processed_group)

            features_df = pd.concat(processed_groups, axis=1)
            features_df = features_df.select_dtypes(include=np.number)

            column_schema = create_column_schema(data=features_df)

            features_np = features_df.to_numpy(dtype=np.float32)
            n_rows, n_columns = features_np.shape

            metadata = DatasetMetadata(
                dataset_type=[dataset_type],
                column_schema=column_schema,
                asset_class=asset_class,
                symbols=symbols,
                start=market_open,
                end=market_close,
                resolution=resolution,
                n_rows=n_rows,
                n_columns=n_columns,
            )

            DatasetIO.write_to_hdf5(
                file_path=file_path,
                data_to_write=features_np,
                metadata=metadata,
                target_dataset_name=target_dataset_name)

            progress_bar_.set_description(
                f"Density: {DataProcessor.running_dataset_density:.0%}")

            progress_bar_.update(1)

        progress_bar_.close()

        return None
