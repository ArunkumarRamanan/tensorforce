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


from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import tensorflow as tf

from tensorforce import util
import tensorforce.core.baselines


class Baseline(object):
    """
    Base class for baseline value functions
    """

    def __init__(self, scope='baseline', summary_level=0):
        self.summary_level = summary_level

        self.variables = dict()

        with tf.name_scope(name=scope):
            def custom_getter(getter, name, *args, **kwargs):
                variable = getter(name=name, *args, **kwargs)
                self.variables[name] = variable
                return variable

            self.predict = tf.make_template(
                name_='predict',
                func_=self.tf_predict,
                create_scope_now_=True,
                custom_getter_=custom_getter
            )
            self.loss = tf.make_template(
                name_='loss',
                func_=self.tf_loss,
                create_scope_now_=True,
                custom_getter_=custom_getter
            )

    def tf_predict(self, states):
        """
        Creates the TensorFlow operations for predicting the value function of given states
        Args:
            states: State tensors
        Returns:
            State value tensor
        """
        raise NotImplementedError

    def tf_loss(self, states, reward):
        """
        Creates the TensorFlow operations for calculating the L2 loss between predicted state values and actual rewards
        Args:
            states: State tensors
            reward: Reward tensor
        Returns:
            Loss tensor
        """
        prediction = self.predict(states=states)
        return tf.nn.l2_loss(t=(prediction - reward))

    def get_variables(self):
        """
        Returns the TensorFlow variables used by the baseline
        Returns:
            List of baseline variables
        """
        return [self.variables[key] for key in sorted(self.variables)]

    @staticmethod
    def from_spec(spec, kwargs=None):
        """
        Creates a baseline from a specification dict.
        """
        return util.get_object(
            obj=spec,
            predefined_objects=tensorforce.core.baselines.baselines,
            kwargs=kwargs
        )
