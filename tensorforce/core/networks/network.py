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
from __future__ import division
from __future__ import print_function

from collections import Counter
import json
import os

import tensorflow as tf

from tensorforce import TensorForceError
from tensorforce.core.networks import Layer


class Network(object):
    """
    Base class for networks
    """

    def __init__(self, scope='network', summary_level=0):
        self.summary_level = summary_level
        self.variables = dict()

        with tf.name_scope(name=scope):
            def custom_getter(getter, name, *args, **kwargs):
                variable = getter(name=name, *args, **kwargs)
                self.variables[name] = variable
                return variable

            self.apply = tf.make_template(
                name_='apply',
                func_=self.tf_apply,
                create_scope_now_=True,
                custom_getter_=custom_getter
            )
            self.regularization_losses = tf.make_template(
                name_='regularization-losses',
                func_=self.tf_regularization_losses,
                create_scope_now_=True,
                custom_getter_=custom_getter
            )

    def tf_apply(self, x, internals=(), return_internals=False):
        """
        Creates the TensorFlow operations for applying the network to the given input

        Args:
            x: Network input tensor
            internals: Prior internal state tensors
            return_internals: If true, also returns posterior internal state tensors

        Returns:
            Network output tensor, plus optionally posterior internal state tensors
        """
        raise NotImplementedError

    def tf_regularization_losses(self):
        """
        Creates the TensorFlow operations for the network regularization losses

        Returns:
            List of network regularization loss tensors
        """
        return None

    def get_variables(self):
        """
        Returns the TensorFlow variables used by the network

        Returns:
            List of network variables
        """
        return [self.variables[key] for key in sorted(self.variables)]

    def internal_inputs(self):
        """
        Returns the TensorFlow placeholders for internal state inputs

        Returns:
            List of internal state input placeholders
        """
        return list()

    def internal_inits(self):
        """
        Returns the TensorFlow tensors for internal state initializations

        Returns:
            List of internal state initialization tensors
        """
        return list()


class LayerBasedNetwork(Network):
    """
    Base class for networks using TensorForce layers
    """

    def __init__(self, scope='layerbased-network', summary_level=0):
        super(LayerBasedNetwork, self).__init__(scope=scope, summary_level=summary_level)
        self.layers = list()

    def add_layer(self, layer):
        self.layers.append(layer)

    def tf_regularization_losses(self):
        losses = list()
        for layer in self.layers:
            losses.extend(layer.regularization_losses())
        if len(losses) > 0:
            return tf.add_n(inputs=losses)
        else:
            return None

    def get_variables(self):
        return super(LayerBasedNetwork, self).get_variables() + [variable for layer in self.layers for variable in layer.get_variables()]

    def internal_inputs(self):
        internal_inputs = list()
        for layer in self.layers:
            internal_inputs.extend(layer.internal_inputs())
        return internal_inputs

    def internal_inits(self):
        internal_inits = list()
        for layer in self.layers:
            internal_inits.extend(layer.internal_inits())
        return internal_inits


class LayeredNetwork(LayerBasedNetwork):
    """
    Network consisting of a sequence of layers, which can be created from a specification dict.
    """

    def __init__(self, layers_spec, scope='layered-network', summary_level=0):
        """
        Layered network

        Args:
            layers_spec: List of layer specification dicts
        """
        super(LayeredNetwork, self).__init__(scope=scope, summary_level=summary_level)
        self.layers_spec = layers_spec
        layer_counter = Counter()

        with tf.name_scope(name=scope):
            for layer_spec in self.layers_spec:
                layer = Layer.from_spec(
                    spec=layer_spec,
                    kwargs=dict(scope=scope, summary_level=summary_level)
                )

                name = layer_spec['type'].__class__.__name__
                scope = name + str(layer_counter[name])
                layer_counter[name] += 1

                self.add_layer(layer=layer)

    def tf_apply(self, x, internals=(), return_internals=False):
        if isinstance(x, dict):
            if len(x) != 1:
                raise TensorForceError('Layered network must have only one input, but {} given.'.format(len(x)))
            x = next(iter(x.values()))

        internal_outputs = list()
        index = 0
        for layer in self.layers:
            layer_internals = [internals[index + n] for n in range(layer.num_internals)]
            index += layer.num_internals
            x = layer.apply(x, *layer_internals)

            if not isinstance(x, tf.Tensor):
                internal_outputs.extend(x[1])
                x = x[0]

        if return_internals:
            return x, internal_outputs
        else:
            return x

    @staticmethod
    def from_json(filename):
        """Creates a layer_networkd_builder from a JSON.

        Args:
            filename: Path to configuration

        Returns: A layered_network_builder function with layers generated from the JSON

        """
        path = os.path.join(os.getcwd(), filename)
        with open(path, 'r') as fp:
            config = json.load(fp=fp)
        return LayeredNetwork(layers_spec=config)
