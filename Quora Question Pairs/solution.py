from __future__ import absolute_import, division, print_function

import matplotlib
matplotlib.use("Agg")

import os
import re
import pylab
import numpy as np
import pandas as pd
from string import punctuation
from gensim.models import KeyedVectors
from keras import backend as K
from keras.callbacks import Callback, EarlyStopping, ModelCheckpoint
from keras.layers import Dense, Dropout, Embedding, Input, LSTM, merge
from keras.layers.normalization import BatchNormalization
from keras.models import Model
from keras.optimizers import Nadam
from keras.preprocessing.sequence import pad_sequences
from keras.preprocessing.text import Tokenizer
from keras.utils.visualize_util import plot
from sklearn.model_selection import StratifiedShuffleSplit

# Dataset
PROJECT_NAME = "Quora Question Pairs"
PROJECT_FOLDER_PATH = os.path.join(os.path.expanduser("~"), "Documents/Dataset", PROJECT_NAME)
TRAIN_FILE_PATH = os.path.join(PROJECT_FOLDER_PATH, "train.csv")
TEST_FILE_PATH = os.path.join(PROJECT_FOLDER_PATH, "test.csv")
EMBEDDING_FILE_PATH = os.path.join(PROJECT_FOLDER_PATH, "GoogleNews-vectors-negative300.bin")
DATASET_FILE_PATH = os.path.join(PROJECT_FOLDER_PATH, "dataset.npz")
MAX_SEQUENCE_LENGTH = 30

# Output
OUTPUT_FOLDER_PATH = os.path.join(PROJECT_FOLDER_PATH, "{}_output".format(os.path.basename(__file__).split(".")[0]))
OPTIMAL_WEIGHTS_FOLDER_PATH = os.path.join(OUTPUT_FOLDER_PATH, "Optimal Weights")
OPTIMAL_WEIGHTS_FILE_RULE = os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "epoch_{epoch:03d}-loss_{loss:.5f}-val_loss_{val_loss:.5f}.h5")
SUBMISSION_FOLDER_PATH = os.path.join(OUTPUT_FOLDER_PATH, "submission")

# Training and Testing procedure
PERFORM_TRAINING = True
WEIGHTS_FILE_PATH = None
MAXIMUM_EPOCH_NUM = 1000
PATIENCE = 100
BATCH_SIZE = 1024
CLASS_WEIGHT = {0:1.309028344, 1:0.472001959}

def clean_sentence(original_sentence, available_vocabulary, result_when_failure="empty"):
    """
        https://www.kaggle.com/currie32/quora-question-pairs/the-importance-of-cleaning-text
    """
    try:
        # Convert to lower case
        cleaned_sentence = " ".join(original_sentence.lower().split())

        # Replace elements
        cleaned_sentence = re.sub(r"[^A-Za-z0-9^,!.\/'+-=]", " ", cleaned_sentence)
        cleaned_sentence = re.sub(r"what's", "what is ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\'s", " ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\'ve", " have ", cleaned_sentence)
        cleaned_sentence = re.sub(r"can't", "cannot ", cleaned_sentence)
        cleaned_sentence = re.sub(r"n't", " not ", cleaned_sentence)
        cleaned_sentence = re.sub(r"i'm", "i am ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\'re", " are ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\'d", " would ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\'ll", " will ", cleaned_sentence)
        cleaned_sentence = re.sub(r",", " ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\.", " ", cleaned_sentence)
        cleaned_sentence = re.sub(r"!", " ! ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\/", " ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\^", " ^ ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\+", " + ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\-", " - ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\=", " = ", cleaned_sentence)
        cleaned_sentence = re.sub(r"'", " ", cleaned_sentence)
        cleaned_sentence = re.sub(r"(\d+)(k)", r"\g<1>000", cleaned_sentence)
        cleaned_sentence = re.sub(r":", " : ", cleaned_sentence)
        cleaned_sentence = re.sub(r" e g ", " eg ", cleaned_sentence)
        cleaned_sentence = re.sub(r" b g ", " bg ", cleaned_sentence)
        cleaned_sentence = re.sub(r" u s ", " american ", cleaned_sentence)
        cleaned_sentence = re.sub(r"\0s", "0", cleaned_sentence)
        cleaned_sentence = re.sub(r" 9 11 ", "911", cleaned_sentence)
        cleaned_sentence = re.sub(r"e - mail", "email", cleaned_sentence)
        cleaned_sentence = re.sub(r"j k", "jk", cleaned_sentence)
        cleaned_sentence = re.sub(r"\s{2,}", " ", cleaned_sentence)

        # Remove punctuation
        cleaned_sentence = "".join([character for character in cleaned_sentence if character not in punctuation])

        # Remove words that are not in vocabulary
        cleaned_sentence = " ".join([word for word in cleaned_sentence.split() if word in available_vocabulary])

        # Check the length of the cleaned sentence
        assert cleaned_sentence

        return cleaned_sentence
    except Exception as exception:
        print("Exception for {}: {}".format(original_sentence, exception))
        return result_when_failure

def load_file(original_file_path, available_vocabulary):
    processed_file_path = os.path.join(os.path.dirname(original_file_path), "processed_" + os.path.basename(original_file_path))
    if os.path.isfile(processed_file_path):
        print("Loading {} ...".format(processed_file_path))
        file_content = pd.read_csv(processed_file_path, encoding="utf-8")
    else:
        print("Loading {} ...".format(original_file_path))
        file_content = pd.read_csv(original_file_path, encoding="utf-8")
        file_content["question1"] = file_content["question1"].apply(lambda original_sentence: clean_sentence(original_sentence, available_vocabulary))
        file_content["question2"] = file_content["question2"].apply(lambda original_sentence: clean_sentence(original_sentence, available_vocabulary))
        file_content.to_csv(processed_file_path, index=False)

    question1_list = file_content["question1"].tolist()
    question2_list = file_content["question2"].tolist()
    if "is_duplicate" in file_content.columns:
        is_duplicate_list = file_content["is_duplicate"].tolist()
        return question1_list, question2_list, is_duplicate_list
    else:
        return question1_list, question2_list

def load_dataset():
    if os.path.isfile(DATASET_FILE_PATH):
        print("Loading dataset from disk ...")
        dataset_file_content = np.load(DATASET_FILE_PATH)
        train_data_1_array = dataset_file_content["train_data_1_array"]
        train_data_2_array = dataset_file_content["train_data_2_array"]
        test_data_1_array = dataset_file_content["test_data_1_array"]
        test_data_2_array = dataset_file_content["test_data_2_array"]
        train_label_array = dataset_file_content["train_label_array"]
        embedding_matrix = dataset_file_content["embedding_matrix"]

        return train_data_1_array, train_data_2_array, test_data_1_array, test_data_2_array, train_label_array, embedding_matrix
    else:
        print("Initiating word2vec ...")
        word2vec = KeyedVectors.load_word2vec_format(EMBEDDING_FILE_PATH, binary=True)
        available_vocabulary = word2vec.vocab
        print("word2vec contains {} unique words.".format(len(available_vocabulary)))

        print("Loading text files ...")
        train_text_1_list, train_text_2_list, train_label_list = load_file(TRAIN_FILE_PATH, available_vocabulary)
        test_text_1_list, test_text_2_list = load_file(TEST_FILE_PATH, available_vocabulary)

        print("Initiating tokenizer ...")
        tokenizer = Tokenizer()
        tokenizer.fit_on_texts(train_text_1_list + train_text_2_list)
        print("dataset contains {} unique words.".format(len(tokenizer.word_index)))

        print("Turning texts into sequences ...")
        train_sequence_1_list = tokenizer.texts_to_sequences(train_text_1_list)
        train_sequence_2_list = tokenizer.texts_to_sequences(train_text_2_list)
        test_sequence_1_list = tokenizer.texts_to_sequences(test_text_1_list)
        test_sequence_2_list = tokenizer.texts_to_sequences(test_text_2_list)

        print("Padding sequences with fixed length ...")
        train_data_1_array = pad_sequences(train_sequence_1_list, maxlen=MAX_SEQUENCE_LENGTH, padding="post", truncating="post")
        train_data_2_array = pad_sequences(train_sequence_2_list, maxlen=MAX_SEQUENCE_LENGTH, padding="post", truncating="post")
        test_data_1_array = pad_sequences(test_sequence_1_list, maxlen=MAX_SEQUENCE_LENGTH, padding="post", truncating="post")
        test_data_2_array = pad_sequences(test_sequence_2_list, maxlen=MAX_SEQUENCE_LENGTH, padding="post", truncating="post")
        train_label_array = np.array(train_label_list, dtype=np.bool)

        print("Initiating embedding matrix ...")
        embedding_matrix = np.zeros((len(tokenizer.word_index) + 1, word2vec.vector_size), dtype=np.float32)
        for word, index in tokenizer.word_index.items():
            assert word in available_vocabulary
            embedding_matrix[index] = word2vec.word_vec(word)
        assert np.sum(np.isclose(np.sum(embedding_matrix, axis=1), 0)) == 1

        print("Saving dataset to disk ...")
        np.savez_compressed(DATASET_FILE_PATH,
                            train_data_1_array=train_data_1_array, train_data_2_array=train_data_2_array,
                            test_data_1_array=test_data_1_array, test_data_2_array=test_data_2_array,
                            train_label_array=train_label_array, embedding_matrix=embedding_matrix)

        return train_data_1_array, train_data_2_array, test_data_1_array, test_data_2_array, train_label_array, embedding_matrix

def init_model(embedding_matrix, learning_rate=0.002):
    def get_sentence_feature_extractor(embedding_matrix):
        input_tensor = Input(shape=(None,), dtype="int32")
        output_tensor = Embedding(input_dim=embedding_matrix.shape[0], output_dim=embedding_matrix.shape[1],
                                input_length=None, mask_zero=True, weights=[embedding_matrix], trainable=False)(input_tensor)
        output_tensor = LSTM(output_dim=256, dropout_W=0.2, dropout_U=0.2, activation="tanh", return_sequences=False)(output_tensor)
        output_tensor = BatchNormalization()(output_tensor)
        output_tensor = Dropout(0.2)(output_tensor)

        model = Model(input_tensor, output_tensor)
        return model

    def get_binary_classifier(input_shape, vanilla_dense_size=256, block_num=3):
        input_tensor = Input(shape=input_shape)
        output_tensor = input_tensor
        for block_index in np.arange(block_num):
            output_tensor = Dense(int(vanilla_dense_size / (2 ** block_index)), activation="relu")(output_tensor)
            output_tensor = BatchNormalization()(output_tensor)
            output_tensor = Dropout(0.2)(output_tensor)
        output_tensor = Dense(1, activation="sigmoid")(output_tensor)

        model = Model(input_tensor, output_tensor)
        return model

    # Initiate the input tensors
    input_1_tensor = Input(shape=(None,), dtype="int32")
    input_2_tensor = Input(shape=(None,), dtype="int32")

    # Define the sentence feature extractor
    sentence_feature_extractor = get_sentence_feature_extractor(embedding_matrix)
    input_1_feature_tensor = sentence_feature_extractor(input_1_tensor)
    input_2_feature_tensor = sentence_feature_extractor(input_2_tensor)
    merged_tensor = merge([input_1_feature_tensor, input_2_feature_tensor], mode="concat")

    # Define the binary classifier
    binary_classifier = get_binary_classifier(input_shape=(K.int_shape(merged_tensor)[1],))
    output_tensor = binary_classifier(merged_tensor)

    # Define the overall model
    model = Model([input_1_tensor, input_2_tensor], output_tensor)
    model.compile(optimizer=Nadam(lr=learning_rate), loss="binary_crossentropy", metrics=["accuracy"])
    model.summary()

    # Plot the model structures
    plot(sentence_feature_extractor, to_file=os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "sentence_feature_extractor.png"), show_shapes=True, show_layer_names=True)
    plot(binary_classifier, to_file=os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "binary_classifier.png"), show_shapes=True, show_layer_names=True)
    plot(model, to_file=os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "model.png"), show_shapes=True, show_layer_names=True)

    # Load weights if applicable
    if WEIGHTS_FILE_PATH is not None:
        assert os.path.isfile(WEIGHTS_FILE_PATH), "Could not find file {}!".format(WEIGHTS_FILE_PATH)
        print("Loading weights from {} ...".format(WEIGHTS_FILE_PATH))
        model.load_weights(WEIGHTS_FILE_PATH)

    return model

def divide_dataset(label_array):
    cv_object = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=0)
    for train_index_array, valid_index_array in cv_object.split(np.zeros((len(label_array), 1)), label_array):
        return train_index_array, valid_index_array

def augment_dataset(data_1_array, data_2_array, label_array):
    augmented_data_1_array = np.vstack((data_1_array, data_2_array))
    augmented_data_2_array = np.vstack((data_2_array, data_1_array))
    augmented_label_array = np.concatenate((label_array, label_array))
    return augmented_data_1_array, augmented_data_2_array, augmented_label_array

class InspectLossAccuracy(Callback):
    def __init__(self):
        super(InspectLossAccuracy, self).__init__()

        self.train_loss_list = []
        self.valid_loss_list = []

        self.train_acc_list = []
        self.valid_acc_list = []

    def on_epoch_end(self, epoch, logs=None):
        # Loss
        train_loss = logs.get("loss")
        valid_loss = logs.get("val_loss")
        self.train_loss_list.append(train_loss)
        self.valid_loss_list.append(valid_loss)
        epoch_index_array = np.arange(len(self.train_loss_list)) + 1

        pylab.figure()
        pylab.plot(epoch_index_array, self.train_loss_list, "yellowgreen", label="train_loss")
        pylab.plot(epoch_index_array, self.valid_loss_list, "lightskyblue", label="valid_loss")
        pylab.grid()
        pylab.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc=2, ncol=2, mode="expand", borderaxespad=0.)
        pylab.savefig(os.path.join(OUTPUT_FOLDER_PATH, "Loss Curve.png"))
        pylab.close()

        # Accuracy
        train_acc = logs.get("acc")
        valid_acc = logs.get("val_acc")
        self.train_acc_list.append(train_acc)
        self.valid_acc_list.append(valid_acc)
        epoch_index_array = np.arange(len(self.train_acc_list)) + 1

        pylab.figure()
        pylab.plot(epoch_index_array, self.train_acc_list, "yellowgreen", label="train_acc")
        pylab.plot(epoch_index_array, self.valid_acc_list, "lightskyblue", label="valid_acc")
        pylab.grid()
        pylab.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc=2, ncol=2, mode="expand", borderaxespad=0.)
        pylab.savefig(os.path.join(OUTPUT_FOLDER_PATH, "Accuracy Curve.png"))
        pylab.close()

def run():
    print("Creating folders ...")
    os.makedirs(OPTIMAL_WEIGHTS_FOLDER_PATH, exist_ok=True)
    os.makedirs(SUBMISSION_FOLDER_PATH, exist_ok=True)

    print("Loading dataset ...")
    train_data_1_array, train_data_2_array, test_data_1_array, test_data_2_array, train_label_array, embedding_matrix = load_dataset()

    print("Initializing model ...")
    model = init_model(embedding_matrix)

    if PERFORM_TRAINING:
        print("Dividing the vanilla training dataset ...")
        train_index_array, valid_index_array = divide_dataset(train_label_array)

        print("Performing data augmentation ...")
        augmented_train_data_1_array, augmented_train_data_2_array, augmented_train_label_array = augment_dataset(train_data_1_array[train_index_array], train_data_2_array[train_index_array], train_label_array[train_index_array])
        augmented_valid_data_1_array, augmented_valid_data_2_array, augmented_valid_label_array = augment_dataset(train_data_1_array[valid_index_array], train_data_2_array[valid_index_array], train_label_array[valid_index_array])

        print("Performing the training procedure ...")
        valid_sample_weights = np.ones(len(augmented_valid_label_array)) * CLASS_WEIGHT[1]
        valid_sample_weights[np.logical_not(augmented_valid_label_array)] = CLASS_WEIGHT[0]
        earlystopping_callback = EarlyStopping(monitor="val_loss", patience=PATIENCE)
        modelcheckpoint_callback = ModelCheckpoint(OPTIMAL_WEIGHTS_FILE_RULE, monitor="val_loss", save_best_only=True, save_weights_only=True)
        inspectlossaccuracy_callback = InspectLossAccuracy()
        model.fit([augmented_train_data_1_array, augmented_train_data_2_array], augmented_train_label_array, batch_size=BATCH_SIZE,
                validation_data=([augmented_valid_data_1_array, augmented_valid_data_2_array], augmented_valid_label_array, valid_sample_weights),
                callbacks=[earlystopping_callback, modelcheckpoint_callback, inspectlossaccuracy_callback],
                class_weight=CLASS_WEIGHT, nb_epoch=MAXIMUM_EPOCH_NUM, verbose=2)
    else:
        assert WEIGHTS_FILE_PATH is not None

        print("Performing the testing procedure ...")
        submission_file_path = os.path.join(SUBMISSION_FOLDER_PATH, "Aurora.csv")
        if not os.path.isfile(submission_file_path):
            prediction_1_array = model.predict([test_data_1_array, test_data_2_array], batch_size=BATCH_SIZE, verbose=2)
            prediction_2_array = model.predict([test_data_2_array, test_data_1_array], batch_size=BATCH_SIZE, verbose=2)
            prediction_array = np.mean(np.hstack((prediction_1_array, prediction_2_array)), axis=1, keepdims=True)
            submission_file_content = pd.DataFrame({"test_id":np.arange(len(prediction_array)), "is_duplicate":prediction_array.flat})
            submission_file_content.to_csv(submission_file_path, index=False)

    print("All done!")

if __name__ == "__main__":
    run()
