import numpy as np
import random
from keras.layers.embeddings import Embedding
from keras.layers.core import Dense, Dropout, Activation, Flatten, Reshape
from keras.models import Model
from keras.layers import Convolution2D, Dense, Flatten, Input, merge, Lambda, TimeDistributed
from keras.optimizers import RMSprop, Adadelta, Adam

from rlofc.ofc_environment import OFCEnv
from rlofc.gamestate_encoder import GamestateRankSuitEncoder, GamestateStreetsonlyEncoder


def simple_pgnet(input_dim,
                 action_space,
                 hidden_size=10,
                 dropout=0.0,
                 learning_rate=1e-4):
    """Karpathy-approved PGNet. From kerlym."""
    S = Input(shape=[input_dim])
    h = Dense(hidden_size, activation='relu', init='he_normal')(S)
    h = Dropout(dropout)(h)
    V = Dense(action_space, activation='sigmoid', init='zero')(h)
    model = Model(S, V)
    model.compile(loss='mse', optimizer=RMSprop(lr=learning_rate))
    return model


action_space = 3
niter = 1000000

env = OFCEnv([])
# encoder = GamestateRankSuitEncoder()
encoder = GamestateStreetsonlyEncoder()

model = simple_pgnet(encoder.dim, action_space)

# Initialize
reward_tracker = []
xs, hs, dlogps, drs = [], [], [], []
running_reward = None
reward_sum = 0
episode_number = 0

for i in xrange(niter):
    # Observe and encode the game state
    observation = env.observe()
    plyr_board, oppo_board, cur_card, cards, game_over, reward = observation
    x = encoder.encode(*observation)

    # Sample an action
    aprob = model.predict(x.reshape([1, encoder.dim]), batch_size=1)
    action = np.random.choice(action_space, 1, p=(aprob / np.sum(aprob))[0])
    action = random.choice(plyr_board.get_free_street_indices())
    # Calculate harsh grad
    y = np.zeros([action_space])
    y[action] = 1

    # Record the story
    xs.append(x)  # Observation
    dlogps.append(y)  # Gradient

    # Step forward
    env.step(action)
    observation = env.observe()
    plyr_board, oppo_board, cur_card, cards, game_over, reward = observation

    # Record reward
    reward_sum += reward
    drs.append(float(reward))

    if game_over:
        reward_tracker.append(float(reward))
        episode_number += 1

        # Stack together the stories of this episode
        epx = np.vstack(xs)
        epdlogp = np.vstack(dlogps)
        epr = np.vstack(drs)

        # Reset array memory
        xs, hs, dlogps, drs = [], [], [], []

        # Don't discount EPR, but standardize it
        discounted_epr = epr
        mean_epr = np.mean(discounted_epr)
        std_epr = np.std(discounted_epr)
        if std_epr == 0:
            std_epr = 1
        discounted_epr -= mean_epr
        discounted_epr /= std_epr

        # Modulate the gradient (PG magic)
        epdlogp *= discounted_epr

        # Update model!
        model.fit(epx, epdlogp, nb_epoch=1, verbose=0, shuffle=True)

        # Book-keeping
        # running_reward = reward_sum if running_reward is None \
        #     else running_reward * 0.99 + reward_sum * 0.01
        # print 'resetting env. running mean: %f' \
        #     % (running_reward)
        print "Iter %d\trun average: %f\ttot average %f" % \
            (episode_number, np.mean(reward_tracker[-500:]), np.mean(reward_tracker))
        # if episode_number % 100 == 0:
        #     save()
        reward_sum = 0

        env.reset()
