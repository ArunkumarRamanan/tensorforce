# Copyright 2017 reinforce.io. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""
Basic Reinforcement learning agent. An agent encapsulates execution logic
of a particular reinforcement learning algorithm and defines the external interface
to the environment.

The agent hence acts an intermediate layer between environment
and backend execution (value function or policy updates).
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from random import random, randrange

from tensorforce.core.preprocessing import Preprocessing
from tensorforce.core.explorations import Exploration


class Agent(object):

    name = None
    model = None
    default_config = dict(
        preprocessing=None,
        exploration=None
    )

    def __init__(self, config):
        assert self.__class__.name is not None and self.__class__.model is not None
        config.default(Agent.default_config)

        # states config and preprocessing
        self.preprocessing = dict()
        if 'type' in config.states:
            # only one state
            config.states = dict(state=config.states)
            self.unique_state = True
            if config.preprocessing is not None:
                config.preprocessing = dict(state=config.preprocessing)
        else:
            self.unique_state = False
        for name, state in config.states:
            if config.preprocessing is not None and name in config.preprocessing:
                preprocessing = Preprocessing.from_config(config=config.preprocessing[name])
                self.preprocessing[name] = preprocessing
                state.shape = preprocessing.processed_shape(shape=state.shape)

        # actions config and exploration
        self.continuous_actions = list()
        self.exploration = dict()
        if 'continuous' in config.actions:
            # only one action
            if config.actions.continuous:
                self.continuous_actions.append('action')
            config.actions = dict(action=config.actions)
            if config.exploration is not None:
                config.exploration = dict(action=config.exploration)
            self.unique_action = True
        else:
            self.unique_action = False
        for name, action in config.actions:
            if action.continuous:
                self.continuous_actions.append(name)
            if config.exploration is not None and name in config.exploration:
                self.exploration[name] = Exploration.from_config(config=config.exploration[name])

        self.states_config = config.states
        self.actions_config = config.actions

        self.model = self.__class__.model(config)

        self.episode = 0
        self.timestep = 0

    def __str__(self):
        return str(self.__class__.name)

    def reset(self):
        self.episode += 1
        self.internal = self.next_internal = self.model.reset()
        for preprocessing in self.preprocessing.values():
            preprocessing.reset()

    def act(self, state):
        self.timestep += 1
        self.internal = self.next_internal

        if self.unique_state:
            state = dict(state=state)

        # preprocessing
        for name, preprocessing in self.preprocessing.items():
            state[name] = preprocessing.process(state=state[name])

        # model action
        action, self.next_internal = self.model.get_action(state=state, internal=self.internal)

        # exploration
        for name, exploration in self.exploration.items():
            if name in self.continuous_actions:
                action[name] += exploration(episode=self.episode, timestep=self.timestep)
            else:
                if random() < exploration(episode=self.episode, timestep=self.timestep):
                    action[name] = randrange(self.actions_config[name].num_actions)

        if self.unique_state:
            state = state['state']
        if self.unique_action:
            action = action['action']
        return state, action

    def observe(self, state, action, reward, terminal):
        raise NotImplementedError

    def load_model(self, path):
        self.model.load_model(path)

    def save_model(self, path):
        self.model.save_model(path)