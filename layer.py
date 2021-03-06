import tensorflow as tf
import keras
from keras import backend as K
from utils import _conv2d_wrapper, _get_weights_wrapper


def softmax(x, axis=-1):
    ex = K.exp(x - K.max(x, axis=axis, keepdims=True))
    return ex / K.sum(ex, axis=axis, keepdims=True)


def squash_v1(x, axis=-1):
    s_squared_norm = K.sum(K.square(x), axis, keepdims=True) + K.epsilon()
    scale = K.sqrt(s_squared_norm) / (0.5 + s_squared_norm)
    return scale * x


def routing(u_hat_vecs, iterations):
    b = keras.backend.zeros_like(u_hat_vecs[:, :, :, 0])
    for i in range(iterations):
        c = softmax(b, 1)
        outputs = squash_v1(K.batch_dot(c, u_hat_vecs, [2, 2]))
        if i < iterations - 1:
            b = b + K.batch_dot(outputs, u_hat_vecs, [2, 3])
    poses = outputs
    activations = K.sqrt(K.sum(K.square(poses), 2))
    return poses, activations


def vec_transformation_by_conv(
    poses, input_capsule_dim, input_capsule_num, output_capsule_dim, output_capsule_num
):
    kernel = _get_weights_wrapper(
        name="weights",
        shape=[1, input_capsule_dim, output_capsule_dim * output_capsule_num],
        weights_decay_factor=0.0,
    )
    tf.logging.info("poses: {}".format(poses.get_shape()))
    tf.logging.info("kernel: {}".format(kernel.get_shape()))
    u_hat_vecs = keras.backend.conv1d(poses, kernel)
    u_hat_vecs = keras.backend.reshape(
        u_hat_vecs, (-1, input_capsule_num, output_capsule_num, output_capsule_dim)
    )
    u_hat_vecs = keras.backend.permute_dimensions(u_hat_vecs, (0, 2, 1, 3))
    return u_hat_vecs


def capsules_init(inputs, shape, strides, padding, pose_shape, add_bias, name):
    with tf.variable_scope(name):
        poses = _conv2d_wrapper(
            inputs,
            shape=shape[0:-1] + [shape[-1] * pose_shape],
            strides=strides,
            padding=padding,
            add_bias=add_bias,
            activation_fn=None,
            name="pose_stacked",
        )
        poses_shape = poses.get_shape().as_list()
        poses = tf.reshape(
            poses, [-1, poses_shape[1], poses_shape[2], shape[-1], pose_shape]
        )
        beta_a = _get_weights_wrapper(name="beta_a", shape=[1, shape[-1]])
        poses = squash_v1(poses, axis=-1)
        activations = K.sqrt(K.sum(K.square(poses), axis=-1)) + beta_a
        tf.logging.info("prim poses dimension:{}".format(poses.get_shape()))

    return poses, activations


def capsule_fc_layer(nets, output_capsule_num, iterations, name):
    with tf.variable_scope(name):
        poses, i_activations = nets
        input_pose_shape = poses.get_shape().as_list()

        u_hat_vecs = vec_transformation_by_conv(
            poses,
            input_pose_shape[-1],
            input_pose_shape[1],
            input_pose_shape[-1],
            output_capsule_num,
        )

        tf.logging.info("votes shape: {}".format(u_hat_vecs.get_shape()))

        poses, activations = routing(u_hat_vecs, iterations)

        tf.logging.info("capsule fc shape: {}".format(poses.get_shape()))

    return poses, activations


def capsule_flatten(nets):
    poses, activations = nets
    input_pose_shape = poses.get_shape().as_list()

    poses = tf.reshape(
        poses,
        [
            -1,
            input_pose_shape[1] * input_pose_shape[2] * input_pose_shape[3],
            input_pose_shape[-1],
        ],
    )
    activations = tf.reshape(
        activations,
        [-1, input_pose_shape[1] * input_pose_shape[2] * input_pose_shape[3]],
    )
    tf.logging.info("flatten poses dimension:{}".format(poses.get_shape()))
    tf.logging.info("flatten activations dimension:{}".format(activations.get_shape()))

    return poses, activations


def capsule_conv_layer(nets, shape, strides, iterations, name):
    with tf.variable_scope(name):
        poses, i_activations = nets

        inputs_poses_shape = poses.get_shape().as_list()

        hk_offsets = [
            [(h_offset + k_offset) for k_offset in range(0, shape[0])]
            for h_offset in range(0, inputs_poses_shape[1] + 1 - shape[0], strides[1])
        ]
        wk_offsets = [
            [(w_offset + k_offset) for k_offset in range(0, shape[1])]
            for w_offset in range(0, inputs_poses_shape[2] + 1 - shape[1], strides[2])
        ]

        inputs_poses_patches = tf.transpose(
            tf.gather(
                tf.gather(poses, hk_offsets, axis=1, name="gather_poses_height_kernel"),
                wk_offsets,
                axis=3,
                name="gather_poses_width_kernel",
            ),
            perm=[0, 1, 3, 2, 4, 5, 6],
            name="inputs_poses_patches",
        )
        tf.logging.info(
            "i_poses_patches shape: {}".format(inputs_poses_patches.get_shape())
        )

        inputs_poses_shape = inputs_poses_patches.get_shape().as_list()
        inputs_poses_patches = tf.reshape(
            inputs_poses_patches,
            [-1, shape[0] * shape[1] * shape[2], inputs_poses_shape[-1]],
        )

        i_activations_patches = tf.transpose(
            tf.gather(
                tf.gather(
                    i_activations,
                    hk_offsets,
                    axis=1,
                    name="gather_activations_height_kernel",
                ),
                wk_offsets,
                axis=3,
                name="gather_activations_width_kernel",
            ),
            perm=[0, 1, 3, 2, 4, 5],
            name="inputs_activations_patches",
        )
        tf.logging.info(
            "i_activations_patches shape: {}".format(i_activations_patches.get_shape())
        )

        u_hat_vecs = vec_transformation_by_conv(
            inputs_poses_patches,
            inputs_poses_shape[-1],
            shape[0] * shape[1] * shape[2],
            inputs_poses_shape[-1],
            shape[3],
        )
        tf.logging.info("capsule conv votes shape: {}".format(u_hat_vecs.get_shape()))

        poses, activations = routing(u_hat_vecs, iterations)
        poses = tf.reshape(
            poses,
            [
                inputs_poses_shape[0],
                inputs_poses_shape[1],
                inputs_poses_shape[2],
                shape[3],
                inputs_poses_shape[-1],
            ],
        )
        activations = tf.reshape(
            activations,
            [
                inputs_poses_shape[0],
                inputs_poses_shape[1],
                inputs_poses_shape[2],
                shape[3],
            ],
        )
        nets = poses, activations
    tf.logging.info("capsule conv poses dimension:{}".format(poses.get_shape()))
    tf.logging.info(
        "capsule conv activations dimension:{}".format(activations.get_shape())
    )
    return nets
