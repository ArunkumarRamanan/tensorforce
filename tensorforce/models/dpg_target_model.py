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

from tensorforce import util, TensorForceError
from tensorforce.models import DistributionModel

from tensorforce.core.networks import Network, LayerBasedNetwork, Dense
from tensorforce.core.optimizers import Optimizer, Synchronization


class DDPGCriticNetwork(LayerBasedNetwork):
    def __init__(self, scope='layerbased-network', summary_labels=(), size_t0=400, size_t1=300):
        super(DDPGCriticNetwork, self).__init__(scope=scope, summary_labels=summary_labels)

        self.t0 = Dense(size=size_t0, activation='relu')
        self.t1 = Dense(size=size_t1, activation='relu')
        self.t2 = Dense(size=1, activation='tanh')

        self.add_layer(self.t0)
        self.add_layer(self.t1)
        self.add_layer(self.t2)

    def tf_apply(self, x, internals, update, return_internals=False):
        assert x['states'], x['actions']

        if isinstance(x['states'], dict):
            if len(x['states']) != 1:
                raise TensorForceError('DDPG critic network must have only one state input, but {} given.'.format(
                    len(x['states'])))
            x_states = next(iter(x['states'].values()))
        else:
            x_states = x['states']

        if isinstance(x['actions'], dict):
            if len(x['actions']) != 1:
                raise TensorForceError('DDPG critic network must have only one action input, but {} given.'.format(
                    len(x['actions'])))
            x_actions = next(iter(x['actions'].values()))
        else:
            x_actions = x['actions']

        x_actions = tf.reshape(tf.cast(x_actions, dtype=tf.float32), (-1, 1))

        out = self.t0.tf_apply(x=x_states, update=update)

        out = self.t1.tf_apply(x=tf.concat([out, x_actions], axis=-1), update=update)

        out = self.t2.tf_apply(x=out, update=update)

        return out


class DPGTargetModel(DistributionModel):
    """
    Policy gradient model log likelihood model with target network (e.g. DDPG)
    """

    def __init__(
        self,
        states,
        actions,
        scope,
        device,
        saver,
        summarizer,
        distributed,
        batching_capacity,
        variable_noise,
        states_preprocessing,
        actions_exploration,
        reward_preprocessing,
        update_mode,
        memory,
        optimizer,
        discount,
        network,
        distributions,
        entropy_regularization,
        critic_network,
        critic_optimizer,
        target_sync_frequency,
        target_update_weight
    ):

        self.critic_network_spec = critic_network
        self.critic_optimizer_spec = critic_optimizer

        self.target_sync_frequency = target_sync_frequency
        self.target_update_weight = target_update_weight

        # self.network is the actor, self.critic is the critic
        self.target_network = None
        self.target_network_optimizer = None

        self.critic = None
        self.critic_optimizer = None
        self.target_critic = None
        self.target_critic_optimizer = None

        super(DPGTargetModel, self).__init__(
            states=states,
            actions=actions,
            scope=scope,
            device=device,
            saver=saver,
            summarizer=summarizer,
            distributed=distributed,
            batching_capacity=batching_capacity,
            variable_noise=variable_noise,
            states_preprocessing=states_preprocessing,
            actions_exploration=actions_exploration,
            reward_preprocessing=reward_preprocessing,
            update_mode=update_mode,
            memory=memory,
            optimizer=optimizer,
            discount=discount,
            network=network,
            distributions=distributions,
            entropy_regularization=entropy_regularization,
            requires_deterministic=True
        )

        assert self.memory_spec["include_next_states"]

    def initialize(self, custom_getter):
        super(DPGTargetModel, self).initialize(custom_getter)

        # Target network
        self.target_network = Network.from_spec(
            spec=self.network_spec,
            kwargs=dict(scope='target-network', summary_labels=self.summary_labels)
        )

        # Target network optimizer
        self.target_network_optimizer = Synchronization(
            sync_frequency=self.target_sync_frequency,
            update_weight=self.target_update_weight
        )

        # Target network distributions
        self.target_distributions = self.create_distributions()

        # Critic
        # self.critic = Network.from_spec(
        #     spec=self.critic_network_spec,
        #     kwargs=dict(scope='critic', summary_labels=self.summary_labels)
        # )
        size_t0 = self.critic_network_spec['size_t0']
        size_t1 = self.critic_network_spec['size_t1']

        self.critic = DDPGCriticNetwork(scope='critic', size_t0=size_t0, size_t1=size_t1)
        self.critic_optimizer = Optimizer.from_spec(
            spec=self.critic_optimizer_spec,
            kwargs=dict(summary_labels=self.summary_labels)
        )

        # self.target_critic = Network.from_spec(
        #     spec=self.critic_network_spec,
        #     kwargs=dict(scope='target-critic', summary_labels=self.summary_labels)
        # )
        self.target_critic = DDPGCriticNetwork(scope='critic', size_t0=size_t0, size_t1=size_t1)

        # Target critic optimizer
        self.target_critic_optimizer = Synchronization(
            sync_frequency=self.target_sync_frequency,
            update_weight=self.target_update_weight
        )

        self.fn_target_actions_and_internals = tf.make_template(
            name_='target-actions-and-internals',
            func_=self.tf_target_actions_and_internals,
            custom_getter_=custom_getter
        )

        self.fn_predict_q = tf.make_template(
            name_='predict-q',
            func_=self.tf_predict_q,
            custom_getter_=custom_getter
        )

        self.fn_predict_target_q = tf.make_template(
            name_='predict-target-q',
            func_=self.tf_predict_target_q,
            custom_getter_=custom_getter
        )

    def tf_target_actions_and_internals(self, states, internals, deterministic=True):
        embedding, internals = self.target_network.apply(
            x=states,
            internals=internals,
            update=tf.constant(value=False),
            return_internals=True
        )

        actions = dict()
        for name, distribution in self.target_distributions.items():
            distr_params = distribution.parameterize(x=embedding)
            actions[name] = distribution.sample(
                distr_params=distr_params,
                deterministic=tf.logical_or(x=deterministic, y=self.requires_deterministic)
            )

        return actions, internals

    def tf_loss_per_instance(self, states, internals, actions, terminal, reward, next_states, next_internals, update):
        # Same as PGLogProbModel
        embedding = self.network.apply(x=states, internals=internals, update=update)
        log_probs = list()

        for name, distribution in self.distributions.items():
            distr_params = distribution.parameterize(x=embedding)
            log_prob = distribution.log_probability(distr_params=distr_params, action=actions[name])
            collapsed_size = util.prod(util.shape(log_prob)[1:])
            log_prob = tf.reshape(tensor=log_prob, shape=(-1, collapsed_size))
            log_probs.append(log_prob)
        log_prob = tf.reduce_mean(input_tensor=tf.concat(values=log_probs, axis=1), axis=1)
        return -log_prob * reward

    def tf_predict_q(self, states, internals, actions, reward, update):
        q_value = self.critic.apply(dict(states=states, actions=actions), internals=internals, update=update)
        return reward + self.discount * q_value

    def tf_predict_target_q(self, states, internals, actions, reward, update):
        q_value = self.target_critic.apply(dict(states=states, actions=actions), internals=internals, update=update)
        return reward + self.discount * q_value

    def tf_optimization(self, states, internals, actions, terminal, reward, next_states=None, next_internals=None):
        update = tf.constant(value=True)
        # Predict actions from target actor
        target_actions, target_internals = self.fn_target_actions_and_internals(
            states=next_states, internals=next_internals, deterministic=True)

        predicted_q = self.fn_predict_target_q(states=next_states, internals=next_internals,
                                               actions=target_actions, reward=reward, update=update)
        predicted_q = tf.stop_gradient(input=predicted_q)

        real_q = self.fn_predict_q(states=states, internals=internals, actions=actions, reward=reward, update=update)

        # Update critic
        def fn_critic_loss(predicted_q, real_q):
            return tf.nn.l2_loss(t=predicted_q - real_q)

        critic_optimization = self.critic_optimizer.minimize(
            time=self.timestep,
            variables=self.critic.get_variables(),
            arguments=dict(
                predicted_q=predicted_q,
                real_q=real_q
            ),
            fn_loss=fn_critic_loss)

        # Update actor
        optimization = super(DPGTargetModel, self).tf_optimization(
            states=states,
            internals=internals,
            actions=actions,
            terminal=terminal,
            reward=real_q,
            next_states=next_states,
            next_internals=next_internals
        )

        # Update target network and baseline
        network_distributions_variables = self.get_distributions_variables(self.distributions)
        target_distributions_variables = self.get_distributions_variables(self.target_distributions)

        target_optimization = self.target_network_optimizer.minimize(
            time=self.timestep,
            variables=self.target_network.get_variables() + target_distributions_variables,
            source_variables=self.network.get_variables() + network_distributions_variables
        )

        target_critic_optimization = self.target_critic_optimizer.minimize(
            time=self.timestep,
            variables=self.target_critic.get_variables(),
            source_variables=self.critic.get_variables()
        )

        return tf.group(critic_optimization, optimization, target_optimization, target_critic_optimization)

    def get_variables(self, include_non_trainable=False):
        model_variables = super(DPGTargetModel, self).get_variables(include_non_trainable=include_non_trainable)
        critic_variables = self.critic.get_variables() + self.critic_optimizer.get_variables()

        if include_non_trainable:
            # Target network and optimizer variables only included if 'include_non_trainable' set
            target_variables = self.target_network.get_variables(include_non_trainable=include_non_trainable) \
                               + self.get_distributions_variables(self.target_distributions)\
                               + self.target_network_optimizer.get_variables()

            target_critic_variables = self.target_critic.get_variables() + self.target_critic_optimizer.get_variables()

            return model_variables + critic_variables + target_variables + target_critic_variables
        else:
            return model_variables + critic_variables

    def get_summaries(self):
        # Todo: Critic summaries
        target_distributions_summaries = self.get_distributions_summaries(self.target_distributions)
        return super(DPGTargetModel, self).get_summaries() + self.target_network.get_summaries() \
            + target_distributions_summaries