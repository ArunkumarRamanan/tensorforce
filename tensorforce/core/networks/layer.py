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
Creates various neural network layers. For most layers, these functions use
TF-slim layer types. The purpose of this class is to encapsulate
layer types to mix between layers available in TF-slim and custom implementations.
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from math import sqrt

import numpy as np
import tensorflow as tf

from tensorforce import TensorForceError, util
import tensorforce.core.networks


class Layer(object):
    """
    Base class for network layers
    """

    def __init__(self, num_internals=0, scope='layer', summary_level=0):
        self.num_internals = num_internals
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

    def tf_apply(self, x):
        """
        Creates the TensorFlow operations for applying the layer to the given input

        Args:
            x: Layer input tensor

        Returns:
            Layer output tensor
        """
        raise NotImplementedError

    def tf_regularization_losses(self):
        """
        Creates the TensorFlow operations for the layer regularization losses

        Returns:
            List of layer regularization loss tensors
        """
        return list()

    def get_variables(self):
        """
        Returns the TensorFlow variables used by the layer

        Returns:
            List of layer variables
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

    @staticmethod
    def from_spec(spec, kwargs=None):
        """
        Creates a layer from a specification dict.
        """
        return util.get_object(
            obj=spec,
            predefined_objects=tensorforce.core.networks.layers,
            kwargs=kwargs
        )


class Flatten(Layer):
    """
    Flatten layer
    """

    def __init__(self, scope='flatten', summary_level=0):
        super(Flatten, self).__init__(scope=scope, summary_level=summary_level)

    def tf_apply(self, x):
        return tf.reshape(tensor=x, shape=(-1, util.prod(util.shape(x)[1:])))


class Nonlinearity(Layer):
    """
    Nonlinearity layer
    """

    def __init__(self, name='relu', scope='nonlinearity', summary_level=0):
        """
        Nonlinearity layer

        Args:
            name: Nonlinearity name, one of 'elu', 'relu', 'selu', 'sigmoid', 'softmax', 'softplus', or 'tanh'
        """
        self.name = name
        super(Nonlinearity, self).__init__(scope=scope, summary_level=summary_level)

    def tf_apply(self, x):
        if self.name == 'elu':
            x = tf.nn.elu(features=x)
        elif self.name == 'relu':
            x = tf.nn.relu(features=x)
            if self.summary_level >= 3:  # summary level 3: layer activations
                non_zero_pct = (tf.cast(tf.count_nonzero(x), tf.float32) / tf.cast(tf.reduce_prod(tf.shape(x)), tf.float32))
                tf.summary.scalar('relu-sparsity', 1.0 - non_zero_pct)
        elif self.name == 'selu':
            # https://arxiv.org/pdf/1706.02515.pdf
            alpha = 1.6732632423543772848170429916717
            scale = 1.0507009873554804934193349852946
            negative = alpha * tf.nn.elu(features=x)
            x = scale * tf.where(condition=(x >= 0.0), x=x, y=negative)
        elif self.name == 'sigmoid':
            x = tf.sigmoid(x=x)
        elif self.name == 'softmax':
            x = tf.nn.softmax(logits=x)
        elif self.name == 'softplus':
            x = tf.nn.softplus(features=x)
        elif self.name == 'tanh':
            x = tf.nn.tanh(x=x)
        else:
            raise TensorForceError('Invalid non-linearity: {}'.format(self.name))
        return x


class Linear(Layer):
    """
    Linear fully connected layer
    """

    def __init__(self, size, weights=None, bias=True, l2_regularization=0.0, scope='linear', summary_level=0):
        """
        Linear layer

        Args:
            size: Layer size
            weights: Weight initialization, random if None
            bias: Bias initialization, random if True, no bias added if False
            l2_regularization: L2 regularization weight
        """
        self.size = size
        self.weights_init = weights
        self.bias_init = bias
        self.l2_regularization = l2_regularization
        super(Linear, self).__init__(scope=scope, summary_level=summary_level)

    def tf_apply(self, x):
        if util.rank(x) != 2:
            raise TensorForceError('Invalid input rank for linear layer: {},'
                                   ' must be 2.'.format(util.rank(x)))

        weights_shape = (x.shape[1].value, self.size)

        if self.weights_init is None:
            stddev = min(0.1, sqrt(2.0 / (x.shape[1].value + self.size)))
            self.weights_init = tf.random_normal_initializer(mean=0.0, stddev=stddev, dtype=tf.float32)

        elif isinstance(self.weights_init, float):
            if self.weights == 0.0:
                self.weights_init = tf.zeros_initializer(dtype=tf.float32)
            else:
                self.weights_init = tf.constant_initializer(value=self.weights, dtype=tf.float32)

        elif isinstance(self.weights_init, list):
            self.weights_init = np.asarray(self.weights_init, dtype=np.float32)
            if self.weights.shape != weights_shape:
                raise TensorForceError(
                    'Weights shape {} does not match expected shape {} '.format(self.weights.shape, weights_shape)
                )
            self.weights_init = tf.constant_initializer(value=self.weights_init, dtype=tf.float32)

        elif isinstance(self.weights_init, np.ndarray):
            if self.weights.shape != weights_shape:
                raise TensorForceError(
                    'Weights shape {} does not match expected shape {} '.format(self.weights.shape, weights_shape)
                )
            self.weights_init = tf.constant_initializer(value=self.weights_init, dtype=tf.float32)

        elif isinstance(self.weights_init, tf.Tensor):
            if util.shape(self.weights_init) != weights_shape:
                raise TensorForceError(
                    'Weights shape {} does not match expected shape {} '.format(self.weights.shape, weights_shape)
                )

        bias_shape = (self.size,)

        if isinstance(self.bias_init, bool):
            if self.bias_init:
                self.bias_init = tf.zeros_initializer(dtype=tf.float32)
            else:
                self.bias_init = None

        elif isinstance(self.bias_init, float):
            if self.bias_init == 0.0:
                self.bias_init = tf.zeros_initializer(dtype=tf.float32)
            else:
                self.bias_init = tf.constant_initializer(value=self.bias_init, dtype=tf.float32)

        elif isinstance(self.bias, list):
            self.bias_init = np.asarray(self.bias_init, dtype=np.float32)
            if self.bias_init.shape != bias_shape:
                raise TensorForceError(
                    'Bias shape {} does not match expected shape {} '.format(self.bias.shape, bias_shape)
                )
            self.bias_init = tf.constant_initializer(value=self.bias_init, dtype=tf.float32)

        elif isinstance(self.bias, np.ndarray):
            if self.bias_init.shape != bias_shape:
                raise TensorForceError(
                    'Bias shape {} does not match expected shape {} '.format(self.bias.shape, bias_shape)
                )
            self.bias_init = tf.constant_initializer(value=self.bias_init, dtype=tf.float32)

        elif isinstance(self.bias_init, tf.Tensor):
            if util.shape(self.bias_init) != bias_shape:
                raise TensorForceError(
                    'Bias shape {} does not match expected shape {} '.format(self.bias.shape, bias_shape)
                )

        if isinstance(self.weights_init, tf.Tensor):
            self.weights = self.weights_init
        else:
            self.weights = tf.get_variable(name='W', shape=weights_shape, dtype=tf.float32, initializer=self.weights_init)
        x = tf.matmul(a=x, b=self.weights)

        if self.bias_init is None:
            self.bias = None

        else:
            if isinstance(self.bias_init, tf.Tensor):
                self.bias = self.bias_init
            else:
                self.bias = tf.get_variable(name='b', shape=bias_shape, dtype=tf.float32, initializer=self.bias_init)
            x = tf.nn.bias_add(value=x, bias=self.bias)
        return x

    def tf_regularization_losses(self):
        losses = super(Linear, self).tf_regularization_losses()
        if self.l2_regularization > 0.0:
            losses.append(self.l2_regularization * tf.nn.l2_loss(t=self.weights))
            if self.bias is not None:
                losses.append(self.l2_regularization * tf.nn.l2_loss(t=self.bias))
        return losses


class Dense(Layer):
    """
    Dense layer, i.e. linear fully connected layer with subsequent nonlinearity
    """

    def __init__(self, size, bias=True, activation='relu', l2_regularization=0.0, scope='dense', summary_level=0):
        """
        Dense layer

        Args:
            size: Layer size
            bias: If true, bias is added
            activation: Type of nonlinearity
            l2_regularization: L2 regularization weight
        """
        self.linear = Linear(size=size, bias=bias, l2_regularization=l2_regularization, summary_level=summary_level)
        self.nonlinearity = Nonlinearity(name=activation, summary_level=summary_level)
        super(Dense, self).__init__(scope=scope, summary_level=summary_level)

    def tf_apply(self, x):
        x = self.linear.apply(x=x)
        x = self.nonlinearity.apply(x=x)

        if self.summary_level >= 3:
            tf.summary.histogram('activations', x)
        return x

    def tf_regularization_losses(self):
        losses = super(Dense, self).tf_regularization_losses()
        losses.extend(self.linear.regularization_losses())
        return losses

    def get_variables(self):
        return super(Dense, self).get_variables() + self.linear.get_variables() + self.nonlinearity.get_variables()


class Conv2d(Layer):
    """
    A 2-dimensional convolutional layer.
    """

    def __init__(self, size, window=3, stride=1, padding='SAME', bias=False, activation='relu', l2_regularization=0.0, scope='conv2d', summary_level=0):
        """
        Convolutional layer

        Args:
            size: Number of filters
            window: Convolution window size
            stride: Convolution stride
            padding: Convolution padding, one of 'VALID' or 'SAME'
            bias: If true, a bias is added
            activation: Type of nonlinearity
            l2_regularization: L2 regularization weight
        """
        self.window = window
        self.stride = stride
        self.padding = padding
        self.bias = bias
        self.l2_regularization = l2_regularization
        self.nonlinearity = Nonlinearity(name=activation, summary_level=summary_level)
        super(Conv2d, self).__init__(scope=scope, summary_level=summary_level)

    def tf_apply(self, x):
        if util.rank(x) != 4:
            raise TensorForceError('Invalid input rank for conv2d layer: {}, must be 4'.format(util.rank(x)))

        filters_shape = (self.window, self.window, x.shape[3].value, self.size)
        stddev = min(0.1, sqrt(2.0 / self.size))
        filters_init = tf.random_normal_initializer(mean=0.0, stddev=stddev, dtype=tf.float32)
        self.filters = tf.get_variable(name='W', shape=filters_shape, dtype=tf.float32, initializer=filters_init)
        x = tf.nn.conv2d(input=x, filter=self.filters, strides=(1, self.stride, self.stride, 1), padding=self.padding)

        if self.bias:
            bias_shape = (self.size,)
            bias_init = tf.zeros_initializer(dtype=tf.float32)
            self.bias = tf.get_variable(name='b', shape=bias_shape, dtype=tf.float32, initializer=bias_init)
            x = tf.nn.bias_add(value=x, bias=self.bias)

        if self.summary_level >= 3:
            tf.summary.histogram('activations', x)
        return x

    def tf_regularization_losses(self):
        losses = super(Conv2d, self).tf_regularization_losses()
        if self.l2_regularization > 0.0:
            losses.append(self.l2_regularization * tf.nn.l2_loss(t=self.filters))
            if self.bias is not None:
                losses.append(self.l2_regularization * tf.nn.l2_loss(t=self.bias))
        return losses


class Lstm(Layer):
    """
    LSTM layer
    """

    def __init__(self, size, dropout=None, scope='lstm', summary_level=0):
        """
        LSTM layer

        Args:
            size: LSTM size
            dropout: Dropout rate
        """
        self.size = size
        self.dropout = dropout
        super(Lstm, self).__init__(num_internals=1, scope=scope, summary_level=summary_level)

    def tf_apply(self, x, state):
        if util.rank(x) != 2:
            raise TensorForceError('Invalid input rank for lstm layer: {}, must be 2.'.format(util.rank(x)))

        c = state[:, 0, :]
        h = state[:, 1, :]
        state = tf.contrib.rnn.LSTMStateTuple(c=c, h=h)

        self.lstm_cell = tf.contrib.rnn.LSTMCell(num_units=self.size)
        if self.dropout is not None:
            self.lstm_cell = tf.contrib.rnn.DropoutWrapper(cell=self.lstm_cell, output_keep_prob=(1.0 - self.dropout))

        x, state = self.lstm_cell(inputs=x, state=state)

        if self.summary_level >= 3:
            tf.summary.histogram('activations', x)

        internal_output = tf.stack(values=(state.c, state.h), axis=1)

        return x, (internal_output,)

    def internal_inputs(self):
        return (tf.placeholder(dtype=tf.float32, shape=(None, 2, self.size)),)

    def internal_inits(self):
        return (np.zeros(shape=(2, self.size)),)
