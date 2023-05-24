
"""
pipes.py

This module defines pipes for market environments.
"""
from abc import abstractmethod, ABC
from typing import Callable

from neural.wrapper.base import (MarginAccountMetaDataWrapper,
                                 ConsoleTearsheetRenderWrapper)

from neural.wrapper.action import (
    MinTradeSizeActionWrapper, IntegerAssetQuantityActionWrapper,
    PositionCloseActionWrapper, InitialMarginActionWrapper,
    ExcessMarginActionWrapper, ShortingActionWrapper,
    EquityBasedFixedUniformActionParser, ActionClipperWrapper)

from neural.wrapper.observation import (ObservationStackerWrapper,
                                        ObservationBufferWrapper,
                                        FlattenToNUmpyObservationWrapper,
                                        ObservationNormalizerWrapper)

from neural.wrapper.reward import (RewardNormalizerWrapper,
                                   RewardGeneratorWrapper,
                                   LiabilityInterstRewardWrapper)


class AbstractPipe(ABC):
    """
    Abstract class for environment pipes, which add extended
    functionality to an existing environment by applying wrappers
    successively. A pipe is a stack of wrappers applied in a
    non-conflicting way. Use wrappers to customize the base market env,
    manipulate actions and observations, impose trading logic, etc.
    according to your specific needs. Wrappers are intantiated every
    time the pipe method is called. If you need to restore state of some
    wrappers, you can make that state a constructor argument of both
    wrapper class and and the pipe and set the argument passed to
    wrapper equal to state of wrapper. If both satate are immutable, the
    values will be synchronized pointing at same memory space. This way
    When saving the pipe, the state of the wrappers will be saved as
    well. The pipe class is an abstract class and must be subclassed.

    Methods:
    --------
        pipe(env):
            Applies a stack of market wrappers successively to an
            environment.
    Notes:
    -----
        Pipes can be combined to create more complex pipes. For example,
        you can save and reuse a predefined set of wrappers as a pipe
        for convenience.
    """

    @abstractmethod
    def pipe(self, env):
        """
        Abstract method for piping an environment. Wrappers
        are added successively akin to layers in PyTorch.
        By calling pipe, the environment is wrapped in a stack
        of wrappers.
        """

        raise NotImplementedError


class RewardPipe(AbstractPipe):
    """
    This pipe adds reward generation, interest on debt, and
    normalization to the base market environment. The pipe adds the
    following functionality to the base environment:
        - Reward generation:
            This will be the change in equity of the account.
        - Interest on debt
            Reduces reward by amount of interest on debt. Computed at 
            end of day.
        - Reward normalization:
            Ensures that the reward distribution has zero mean and unit.
    
    Attributes:
    -----------
        reward_generator (RewardGeneratorWrapper):
            reward generator wrapper. Set to RewardGeneratorWrapper at
            construction.
        interest (LiabilityInterstRewardWrapper):
            interest on debt wrapper. Set to
            LiabilityInterstRewardWrapper at construction.
        reward_normalizer (RewardNormalizerWrapper):
            reward normalizer wrapper. Set to RewardNormalizerWrapper at
            construction.

    Methods:
    --------
        pipe(env):
            Applies a stack of market wrappers successively to an
            environment.
    """
    def __init__(self) -> None:
        """
        Initializes the reward pipe.
        """

        self.reward_generator = RewardGeneratorWrapper
        self.interest = LiabilityInterstRewardWrapper
        self.reward_normalizer = RewardNormalizerWrapper

    def pipe(self, env):
        """
        A method for piping an environment. Applies a stack of market
        wrappers successively to an environment:
            1. Reward generation
            2. Interest on debt
            3. Reward normalization
        """
        env = self.reward_generator(env)
        env = self.interest(env)
        env = self.reward_normalizer(env)

        return env

class ObservationPipe(AbstractPipe):
    """
    Observation pipe for market environments. The pipe adds the
    following functionality to the base environment:
        - Observation flattening:
            If numpy array, flattens the observation to a 1D array. If 
            dict, flattens the observation to a 1D array for each key.
            then joins the arrays into a single 1D array.
        - Observation buffering:
            Buffers the last n observations. If numpy array, buffers the
            last n observations in a deque. If dict, buffers the last n
            observations in a deque for each key.
        - Observation stacking:
            
        - Observation normalization (dict/numpy array)
    
    Attributes:
    -----------
        buffer_size (int):
            size of the buffer for buffering observations. Set to 10 at
            construction.
        stack_size (int):
            size of the stack for stacking observations. Set to None at
            construction. If None, the stack size will be set to the
            buffer size.
        observation_statistics (RunningStatistics):
            statistics of the observation distribution. Set to None at
            construction. If track_statistics is True, the statistics
            will be synchronized with the statistics of the observation
            normalizer wrapper. This will be reused with the wrapper
            when the pipe is saved and loaded.
        track_statistics (bool):
            whether to track and update the observation statistics
            during training. If False, the statistics will not be
            tracked and updated during training. If yes statistics are
            tracked as pipe attribute and can be saved and loaded with
            the pipe object.
    
    Methods:
    --------
        pipe(env):
            Applies a stack of market wrappers successively to an
            environment.
    """
    def __init__(self,
                 buffer_size: int = 10,
                 stack_size: int = None,
                 track_statistics: bool = True) -> None:
        """
        Initializes the observation pipe.

        Args:
        ------
        buffer_size (int):
            size of the buffer for buffering observations. Set to 10 at
            construction.
        stack_size (int):
            size of the stack for stacking observations. Set to None at 
            construction. If None, the stack size will be set to the
            buffer size.
        track_statistics (bool):
            whether to track and update the observation statistics
            during training. If False, the statistics will not be
            tracked and updated during training. If yes statistics are
            tracked as pipe attribute and can be saved and loaded with
            the pipe object.
        """
        self.buffer_size = buffer_size
        self.stack_size = stack_size
        self.observation_statistics = None
        self.track_statistics = track_statistics

        self.flatten = FlattenToNUmpyObservationWrapper
        self.buffer = ObservationBufferWrapper
        self.stacker = ObservationStackerWrapper
        self.normalize_observation = ObservationNormalizerWrapper

    def pipe(self, env):
        env = self.flatten(env)
        env = self.buffer(env, buffer_size=self.buffer_size)
        env = self.stacker(env, stack_size=self.stack_size)

        env = self.normalize_observation(
            env,
            observation_statistics=self.observation_statistics,
            track_statistics=self.track_statistics)

        return env


class ActionPipe(AbstractPipe):
    """
    Action pipe for market environments. The pipe adds the following
    functionality to the base environment:
        - Minimum trade size
        - Integer asset quantity
        - Position close
        - Shorting

    Minimum trade size ensures that the notional value of a trade is
    greater than a minimum value. Integer asset quantity ensures that
    the number of assets traded is an integer. Position close ensures
    that the agent can close positions, before flipping the sign of the
    quantity. Shorting ensures that the agent short actions map to
    integer asset quantities.

    Attributes:
    -----------
        min_trade (float):
            minimum trade size in terms of notional value of base
            currency. Set to 1 at construction.
        integer (bool):
            whether to modify notional value of trades to match integer
            number of assets. Set to False at construction.
    
    Methods:
    --------
        pipe(env):
            Applies a stack of market wrappers successively to an
            environment.
    """
    def __init__(self, min_trade: float = 1, integer: bool = False) -> None:
        """
        Initializes the action pipe.

        Args:
        ------
        min_trade (float):
            minimum trade size in terms of notional value of base
            currency. Set to 1 at construction.
        integer (bool):
            whether to modify notional value of trades to match integer
            number of assets. Set to False at construction.
        """
        self.min_trade = min_trade
        self.integer = integer

        self.min_trade = MinTradeSizeActionWrapper
        self.integer_quantity = IntegerAssetQuantityActionWrapper
        self.position_close = PositionCloseActionWrapper
        self.shorting = ShortingActionWrapper

    def pipe(self, env):
        env = self.min_trade(env, min_trade=self.min_trade)
        env = self.integer_quantity(env, integer=self.integer)
        env = self.position_close(env)
        env = self.shorting(env)

        return env

class HeadActionPipe(AbstractPipe):
    """
    This pipe is responsible for parsing the immediate actions of the model,
    hence the name head. It is the last pipe applied in the action pipe stack
    (first pipe to receive actions). The pipe adds the following functionality
    to the base environment:
        - Action parsing
        - Action mapping
        - Action clipping
    
    After parsing the actions should correspond the notional value of trade in
    base currency (e.g. 100$ for USDT-BTC pair). In general it is assumed that
    a fixed percentage of the equity is traded at each interval. The percentage
    is fixed at construction. This trading budget so to speak can be
    distributed uniformly, or non-uniformly across the assets. Models that
    produce discrete actions are only compatible with uniform distribution of
    the trading budget. The trading equity ratio can also be determined by the
    model, in this case the trading budget is determined by the model and the
    percentage at construction is ignored. Types of actions expected from the
    model are:
        - Uniform fixed ratio: 
            one neuron for each asset each with value (-1, 1). This will be
            used to infer both side and value of trade. Interpretation of this
            signal is left to an action interpretter. This can be achieved by
            applying tanh to the output of the model, for continuous models, or
            simply just clipping the actions of the model to this range. For
            discrete models, the output of the model is mapped to (-1, 1) using
            an action mapper.
        - Uniform variable ratio:
            one neuron for each asset each with value (-1, 1). One neuron with
            value in (0,1) indicating the trade equity ratio. This can be
            achieved by applying sigmoid to a corresponding neuron. For
            discrete models, the output of the model for each asset is mapped
            to (-1, 1) using an action mapper. Similarly output of the model
            for the trade equity ratio is mapped to (0, 1) using the same
            action mapper.
        - Non-uniform fixed ratio:
            This is only viable for continuous models. The model should output
            one neuron for each asset each with value (-1, 1), showing trade
            side (buy/sell). Apply tanh to the relevant output of the model.
            Also it has one neuron for each asset each with value in (0, 1)
            summing to 1, showing the distribution of budget across assets.
            This can be achieved by applying softmax to the corresponding
            outputs of the model. An action interpreter then uses these 2n
            neurons to infer the notional value of trade for each asset. The
            trade equity ratio is fixed at construction.
        - Non-uniform variable ratio:
            This is only viable for continuous models. The model is identical
            to the non-uniform fixed ratio model, except that the trade equity
            ratio is determined by the model. A neuron with value in (0,1) is
            responsible for determining the trade equity ratio. This can be
            achieved by applying sigmoid to a corresponding neuron.
        
    Training the non-uniform/variable ratio models is more difficult than the
    uniform/fixed ratio models. This is because the model is dealing with a
    larger action space primarily. Moreover model can produce actions that lead
    to more frequent trading anomalies. It is recommended to use a tiered
    training approach with restrctions on the degrees of freedom of the model
    and gradually removing them at each tier.

    Attributes:
    -----------
        uniform (bool):
            whether to use uniform distribution of trading budget. Set to True
            at construction.
        fixed (bool):
            whether to use fixed trading equity ratio. Set to True at
            construction.
        discrete (bool):
            whether to use discrete actions. Set to True at construction.
        trade_equity_ratio (float):
            fixed trading equity ratio. Set to 0.1 at construction.
        hold_threshold (float):
            threshold for holding an asset. Set to 0.15 at construction.
        clip (bool):
            whether to clip actions to (low, high). Set to False at construction.
        low (float):
            lower bound for clipping actions. Set to -1 at construction.
        high (float):
            upper bound for clipping actions. Set to 1 at construction.
        fixed_uniform (EquityBasedFixedUniformActionParser):
            action parser for fixed uniform ratio models.
        variable_uniform ($$$):
            action parser for variable uniform ratio models.
        fixed_nonuniform ($$$):
            action parser for fixed non-uniform ratio models.
        variable_nonuniform ($$$):
            action parser for variable non-uniform ratio models.
            
    Methods:
    --------
        pipe(env):
            Applies a stack of market wrappers successively to an
            environment.
    
    Raises:
    -------
        ValueError:
            if discrete and non-uniform distribution of trading budget is
            requested.
    """
    def __init__(
            self,
            uniform: bool = True,
            fixed: bool = True,
            discrete: bool = False,
            trade_equity_ratio: float = 0.05,
            hold_threshold: float = 0.15,
            clip: bool = False,
            low: float = -1,
            high: float = 1
            ) -> None:
        """
        Initializes the head action pipe.

        Arguments:
        ----------
            uniform (bool):
                whether to use uniform distribution of trading budget. Set to
                True at construction.
            fixed (bool):
                whether to use fixed trading equity ratio. Set to True at
                construction.
            discrete (bool):
                whether to use discrete actions. Set to True at construction.
            trade_equity_ratio (float):
                fixed trading equity ratio. Set to 0.05 at construction.
            hold_threshold (float):
                threshold for holding an asset. Set to 0.15 at construction.
            clip (bool):
                whether to clip actions to (low, high). Set to False at
                construction.
            low (float):
                lower bound for clipping actions. Set to -1 at construction.
            high (float):
                upper bound for clipping actions. Set to 1 at construction.
        """

        if uniform and discrete:
            raise ValueError(
                'Discrete models can only be used with uniform trading '
                'budget distribution.')
        
        self.uniform = uniform
        self.fixed = fixed

        self.trade_equity_ratio = trade_equity_ratio
        self.hold_threshold = hold_threshold

        self.clip = clip
        self.low = low
        self.high = high

        self.fixed_uniform_parser  = EquityBasedFixedUniformActionParser
        self.variable_uniform_parser = None
        self.fixed_nonuniform_parser = None
        self.variable_nonuniform_parser = None

        self.fixed_uniform_mapper = None
        self.fixed_nonuniform_mapper = None

        self.action_clipper = ActionClipperWrapper

    @property
    def parser(self) -> Callable:
        """
        Parser is the first pipe to receive actions. It is responsible for
        parsing the actions of the model. If model is discrete, it may be 
        preceded by an action mapper wrapper to map discrete actions to
        the expected action space.
        """
        if self.fixed:
            if self.uniform:
                parser = lambda env: self.fixed_uniform_parser(
                    self.trade_equity_ratio, self.hold_threshold, env)
            else:
                parser = self.fixed_nonuniform_parser
        else:
            if self.uniform:
                parser = self.variable_uniform_parser
            else:
                parser = self.variable_nonuniform_parser

        return parser
    
    @property
    def mapper(self):
        """
        Used with discrete models to map the actions to the expected action
        space.

        Examples:
        ---------
        Model produces k actions for buy orders, k actions for sell orders
        and 1 action for hold. The mapper will map the k buy actions to
        the range (hold_threshold, 1) and k sell actions to the range
        (-1, -hold_threshold). The hold action will be mapped to 0. This 
        is the expected input of the uniform action parser.
        """
        if self.uniform:
            return self.fixed_uniform_mapper
        else:
            return self.fixed_nonuniform_mapper

    def pipe(self, env):
        """
        Applies the head pipe to the environment. Infers action parser from

        """
        env = self.parser(env)
        if self.discete:
            env = self.mapper(env)
        if self.clip:
            env = self.action_clipper(self.low, self.high, env)

        return env
    

class MarginAccountPipe(AbstractPipe):
    """
    A pipe to simulate a margin account environment. The pipe adds the
    trading logics of a margin account to the base market environment.

    It offers following functionalities:
        - Margin account metadata
        - Console tearsheet render
        - Initial margin
        - Excess margin

    Also uses combination of the following pipes:
        - ObservationPipe
        - ActionPipe
        - RewardPipe

    and following action interpreter:
        - Equity based uniform action interpreter

    Attributes:
    -----------
        trade_equity_ratio (float):
            ratio of equity to be traded. Set to 0.02 at construction.
        excess_margin_ratio_threshold (float):
            threshold for excess margin ratio. Set to 0.1 at
            construction.
        min_trade (float):
            minimum trade size in terms of notional value of base
            currency. Set to 1 at construction.
        integer (bool):
            whether to modify notional value of trades to match integer
            number of assets. Set to False at construction.
        buffer_size (int):
            size of the buffer for buffering observations. Set to 10 at
            construction.
        stack_size (int):
            size of the stack for stacking observations. Set to None at
            construction. If None, the stack size will be set to the    
            buffer size.
        observation_statistics (RunningStatistics):
            statistics of the observation distribution. Set to None at
            construction. If track_statistics is True, the statistics
            will be synchronized with the statistics of the observation
            normalizer wrapper. This will be reused with the wrapper
            when the pipe is saved and loaded.
        track_statistics (bool):
            whether to track and update the observation statistics
            during training. If False, the statistics will not be   
            tracked and updated during training. If yes statistics are
            tracked as pipe attribute and can be saved and loaded with
            the pipe object.
        verbosity (int):
            verbosity level of the console tearsheet render. Set to 20
            at construction.

        margin_account_metadata (MarginAccountMetaDataWrapper):
            margin account metadata wrapper. Set to
            MarginAccountMetaDataWrapper at construction.   
        render (ConsoleTearsheetRenderWrapper):
            console tearsheet render wrapper. Set to
            ConsoleTearsheetRenderWrapper at construction.
        initial_margin (InitialMarginActionWrapper):
            initial margin wrapper. Set to InitialMarginActionWrapper
            at construction.
        excess_margin (ExcessMarginActionWrapper):
            excess margin wrapper. Set to ExcessMarginActionWrapper at
            construction.
        observation_pipe (ObservationPipe):
            observation pipe. Set to ObservationPipe at construction.
        action_pipe (ActionPipe):
            action pipe. Set to ActionPipe at construction.
        reward_pipe (RewardPipe):
            reward pipe. Set to RewardPipe at construction.
        action_interpreter (EquityBasedUniformActionInterpreter):
            equity based uniform action interpreter wrapper. Set to
            EquityBasedUniformActionInterpreter at construction.
        
    Methods:
    --------
        pipe(env):
            Applies a stack of market wrappers successively to an
            environment.
    """

    def __init__(self,
                 trade_equity_ratio: float = 0.02,
                 excess_margin_ratio_threshold: float = 0.1,
                 min_trade: float = 1,
                 integer: bool = False,
                 buffer_size: int = 10,
                 stack_size: int = None,
                 track_statistics: bool = True,
                 verbosity: int = 20) -> None:

        self.trade_equity_ratio = trade_equity_ratio
        self.excess_margin_ratio_threshold = excess_margin_ratio_threshold

        self.min_trade = min_trade
        self.integer = integer

        self.buffer_size = buffer_size
        self.stack_size = stack_size
        self.observation_statistics = None

        self.track_statistics = track_statistics
        self.verbosity = verbosity

        self.margin_account_metadata = MarginAccountMetaDataWrapper
        self.render = ConsoleTearsheetRenderWrapper
        self.initial_margin = InitialMarginActionWrapper
        self.excess_margin = ExcessMarginActionWrapper


        self.reward_pipe = RewardPipe
        self.observation_pipe = ObservationPipe
        self.action_pipe = ActionPipe
        self.head = HeadActionPipe

        return None

    def pipe(self, env):
        """
        Applies a stack of market wrappers successively to an
        environment.

        Args:
        ------
        env (AbstractMarketEnv): the environment to be wrapped.

        Returns:
        ---------
        env (gym.Env): the wrapped environment.
        """

        env = self.margin_account_metadata(env)
        env = self.render(env, verbosity=self.verbosity)
        env = self.initial_margin(env)
        env = self.excess_margin(
            env,
            excess_margin_ratio_threshold=self.excess_margin_ratio_threshold)

        env = self.reward_pipe().pipe(env)
        env = self.observation_pipe(
            buffer_size=self.buffer_size,
            stack_size=self.stack_size,
            track_statistics=self.track_statistics).pipe(env)
        env = self.action_pipe(min_trade=self.min_trade,
                               integer=self.integer).pipe(env)

        env = self.head().pipe(env)

        return env
