import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from tensorflow.keras.mixed_precision import experimental as mixed_precision


def get_deepspeech2(input_dim, output_dim,
                    is_mixed_precision=False,
                    rnn_units=800,
                    convert_tflite=False, random_state=1) -> keras.Model:
    max_seq_length = None
    if convert_tflite:
        max_seq_length = 5

    if is_mixed_precision:
        policy = mixed_precision.Policy('mixed_float16')
        mixed_precision.set_policy(policy)

    np.random.seed(random_state)
    tf.random.set_seed(random_state)

    # Create model under CPU scope and avoid OOM, errors during concatenation
    # a large distributed model.
    with tf.device('/cpu:0'):
        # Define input tensor [batch, time, features]
        input_tensor = layers.Input([max_seq_length, input_dim], name='X')

        # Add 4th dimension [batch, time, frequency, channel]
        x = layers.Reshape([max_seq_length or -1, input_dim, 1])(input_tensor)
        x = layers.Conv2D(filters=32,
                          kernel_size=[11, 41],
                          strides=[2, 2],
                          padding='same',
                          use_bias=False,
                          name='conv_1')(x)
        x = layers.BatchNormalization(name='conv_1_bn')(x)
        x = layers.ReLU(name='conv_1_relu')(x)

        x = layers.Conv2D(filters=32,
                          kernel_size=[11, 21],
                          strides=[1, 2],
                          padding='same',
                          use_bias=False,
                          name='conv_2')(x)
        x = layers.BatchNormalization(name='conv_2_bn')(x)
        x = layers.ReLU(name='conv_2_relu')(x)
        # We need to squeeze to 3D tensor. Thanks to the stride in frequency
        # domain, we reduce the number of features four times for each channel.
        x = layers.Reshape([max_seq_length or -1, input_dim//4*32])(x)
        for i in [1, 2, 3, 4, 5]:
            recurrent = layers.GRU(units=rnn_units,
                                   activation='tanh',
                                   recurrent_activation='sigmoid',
                                   use_bias=True,
                                   return_sequences=True,
                                   reset_after=True,
                                   name=f'gru_{i}',
                                   unroll=convert_tflite)
            x = layers.Bidirectional(recurrent,
                                     name=f'bidirectional_{i}',
                                     merge_mode='concat')(x)
            x = layers.Dropout(rate=0.5)(x) if i < 5 else x  # Only between

        # Return at each time step logits along characters. Then CTC
        # computation is more stable, in contrast to the softmax.
        x = layers.Dense(units=rnn_units*2, name='dense_1')(x)
        x = layers.ReLU(name='dense_1_relu')(x)
        x = layers.Dropout(rate=0.5)(x)
        output_tensor = layers.Dense(units=output_dim, name='dense_2')(x)

        if convert_tflite:
            model = keras.Model(input_tensor, output_tensor, name='DeepSpeech2')
        else:
            # Having 1 element vector is required to save and load model in non nightly tensorflow
            # https://github.com/tensorflow/tensorflow/issues/35446.
            feature_lengths = tf.keras.Input(shape=[1], dtype=tf.int32, name='feature_lengths')
            label_lengths = tf.keras.Input(shape=[1], dtype=tf.int32, name='label_lengths')
            model = keras.Model([input_tensor, feature_lengths, label_lengths], output_tensor, name='DeepSpeech2')

    if is_mixed_precision:  # revert policy
        policy = mixed_precision.Policy('float32')
        mixed_precision.set_policy(policy)

    return model
