import tensorflow as tf

import os, sys
from data_loader import DataLoader
import numpy as np
from const import Constant
from sklearn.metrics import roc_auc_score

from model import  InterprecsysBase
from utils import create_folder_tree, evaluate_metrics, build_msg

flags = tf.app.flags

# Run time
flags.DEFINE_integer('epoch', 300, 'Number of Epochs.')
flags.DEFINE_integer('batch_size', 64, 'Number of training instance per batch.')
flags.DEFINE_string('dataset', 'example', 'Name of the dataset.')
flags.DEFINE_integer('num_iter_per_save', 100, 'Number of iterations per save.')

# Optimization
flags.DEFINE_float('learning_rate', 0.001, 'Learning Rate.')
flags.DEFINE_float('l2_reg', 0.01, 'Weight of L2 Regularizations.')

# Parameter Space
flags.DEFINE_integer('embedding_size', 8, 'Hidden Embedding Size.')

# Hyper-param
flags.DEFINE_string('trial_id', '001', 'The ID of the current run.')
flags.DEFINE_float('entity_graph_threshold', 0.5, 'The threshold used when building subgraphs.')
flags.DEFINE_integer('neg_pos_ratio', 3, 'The ratio of negative samples v.s. positive.')
flags.DEFINE_float('dropout_rate', 0.1, 'The dropout rate of Transformer model.')
flags.DEFINE_float('regularization_weight', 0.01, 'The weight of L2-regularization.')

# Structure & Configure
flags.DEFINE_integer('random_seed', 2018, 'Random Seed.')
flags.DEFINE_integer('num_block', 2, 'Number of blocks of Multi-head Attention.')
flags.DEFINE_integer('num_head', 8, 'Number of heads of Multi-head Attention.')
flags.DEFINE_integer('attention_size', 128, 'Number of hidden units in Multi-head Attention.')
flags.DEFINE_boolean('scale_embedding', True, 'Boolean. Whether scale the embeddings.')
flags.DEFINE_integer('pool_filter_size', 64, 'Size of pooling filter.')

# Options
flags.DEFINE_boolean('use_graph', True, 'Whether use graph information.')
flags.DEFINE_string('nct_neg_sample_method', 'uniform', 'Non click-through negative sampling method.')
flags.DEFINE_boolean('load_recent', True, 'Whether to load most recent model.')


FLAGS = flags.FLAGS


def run_model(data_loader,
              model,
              epochs=None,
              load_recent=False):
    """
    Run model (fit/predict)
    
    :param data_loader:
    :param model:
    :param epochs:
    :param is_training: True - Training; False - Evaluation.
    :return:

    TODO: add load_recent
    """

    # ===== Saver for saving & loading =====

    saver = tf.train.Saver(max_to_keep=10)

    # ===== Configurations of runtime environment =====

    config = tf.ConfigProto(
        allow_soft_placement=True
        # , log_device_placement=True
    )
    config.gpu_options.allow_growth = True
    config.gpu_options.per_process_gpu_memory_fraction = 0.8

    # ===== Run Everything =====

    # set dir for runtime log
    log_dir = os.path.join(Constant.LOG_DIR, FLAGS.dataset, "train_" + FLAGS.trial_id)

    # create session
    sess = tf.Session(config=config)

    print("\n========\nID:{}\n========\n".format(FLAGS.trial_id))

    # training
    with sess.as_default(), \
        open("./performance/"
             + FLAGS.dataset + "."
             + FLAGS.trial_id + ".pref", "w") as performance_writer:

        # ===== Initialization of params =====

        sess.run(tf.local_variables_initializer())
        sess.run(tf.global_variables_initializer())

        # ===== Create TensorBoard Logger ======

        train_writer = tf.summary.FileWriter(logdir=log_dir, graph=sess.graph)
        
        for epoch in range(epochs):
            data_loader.has_next = True

            while data_loader.has_next:

                # get batch
                batch_ind, batch_val, batch_label = data_loader.generate_train_batch_ivl()
                batch_label = batch_label.squeeze()

                # run training operation
                op, merged_summary, reg_loss, \
                mean_logloss, overall_loss, \
                sigmoid_logits = sess.run(
                    fetches=[
                        model.train_op,
                        model.merged,
                        model.regularization_loss,
                        model.mean_logloss,
                        model.overall_loss,
                        model.sigmoid_logits,
                    ],
                    feed_dict={
                        model.X_ind: batch_ind,
                        model.X_val: batch_val,
                        model.label: batch_label,
                        model.is_training: True
                    }
                )

                # print results and write to file
                if sess.run(model.global_step) \
                        % 100 == 0:

                    # get AUC
                    try:
                        auc = roc_auc_score(batch_label.astype(np.int32),
                                            sigmoid_logits)
                    except:
                        auc = 0.00
                    
                    msg = build_msg(stage="Trn",
                                    epoch=epoch,
                                    iteration=data_loader.batch_index,
                                    global_step=sess.run(model.global_step),
                                    logloss=mean_logloss,
                                    regloss=reg_loss,
                                    auc=auc)
                    
                    # write to file
                    print(msg, file=performance_writer)

                    # print performance every 1000 batches
                    if sess.run(model.global_step) % 1000 == 0:
                        print(msg)

                # save model
                if sess.run(model.global_step) \
                        % FLAGS.num_iter_per_save == 0:
                    print("\tSaving Checkpoint at global step [{}]!"
                          .format(sess.run(model.global_step)))
                    saver.save(sess,
                               save_path=log_dir,
                               global_step=sess.run(model.global_step))

                # add tensorboard summary
                train_writer.add_summary(
                    merged_summary,
                    global_step=sess.run(model.global_step)
                )

            # run validation set
            epoch_msg = run_evaluation(sess=sess,
                                       data_loader=data_loader,
                                       epoch=epoch,
                                       model=model)

            print(epoch_msg)
            print(epoch_msg, file=performance_writer)

            test_msg = run_evaluation(sess=sess,
                                      data_loader=data_loader,
                                      epoch=epoch,
                                      model=model,
                                      validation=False)
            print(test_msg)
            print(test_msg, file=performance_writer)



        # run test set, with validation=False
        # training_msg = run_evaluation(sess=sess,
        #                               data_loader=data_loader,
        #                               model=model,
        #                               validation=False)
        # print(training_msg)
        # print(training_msg, file=performance_writer)

    print("Training finished!")


def run_evaluation(sess, data_loader, model,
                   epoch=None,
                   validation=True):
    """
    Run validation or testing
    :return:
    """
    if validation:
        batch_generator = data_loader.generate_val_ivl()
    else:
        batch_generator = data_loader.generate_test_ivl()

    sigmoid_logits = []
    test_labels = []
    sum_logloss = 0

    while True:
        try:
            ind, val, label = next(batch_generator)
            label = label.squeeze()
        except StopIteration:
            break

        batch_sigmoid_logits, batch_logloss = sess.run(
            fetches=[
                model.sigmoid_logits,
                model.logloss
            ],
            feed_dict={
                model.X_ind: ind,
                model.X_val: val,
                model.label: label,
                model.is_training: False
            }
        )
        sigmoid_logits += batch_sigmoid_logits.tolist()
        test_labels += label.astype(np.int32).tolist()
        sum_logloss += np.sum(batch_logloss)
    
    mean_logloss = sum_logloss / len(sigmoid_logits)
    auc = roc_auc_score(test_labels, sigmoid_logits)

    msg = build_msg(
        stage="Vld" if validation else "Tst",
        epoch=epoch if epoch is not None else 999,
        global_step=sess.run(model.global_step),
        logloss=mean_logloss,
        auc=auc
    )

    return msg


def main(argv):

    create_folder_tree(FLAGS.dataset)

    print("loading dataset ...")
    dl = DataLoader(dataset=FLAGS.dataset,
                    batch_size=FLAGS.batch_size)

    if FLAGS.use_graph:
        raise NotImplementedError("Graph version not implemented!")
    else:
        model = InterprecsysBase(
            embedding_dim=FLAGS.embedding_size,
            learning_rate=FLAGS.learning_rate,
            field_size=dl.field_size,
            feature_size=dl.feature_size,
            batch_size=FLAGS.batch_size,
            num_block=FLAGS.num_block,
            attention_size=FLAGS.attention_size,
            num_head=FLAGS.num_head,
            dropout_rate=FLAGS.dropout_rate,
            regularization_weight=FLAGS.regularization_weight,
            random_seed=Constant.RANDOM_SEED,
            scale_embedding=FLAGS.scale_embedding,
            pool_filter_size=FLAGS.pool_filter_size,
        )

    # ===== Run everything =====
    run_model(data_loader=dl, 
              model=model, 
              epochs=FLAGS.epoch, 
              load_recent=FLAGS.load_recent)


if __name__ == '__main__':
    tf.app.run()
