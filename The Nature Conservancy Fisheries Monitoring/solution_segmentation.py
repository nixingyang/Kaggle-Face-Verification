import matplotlib
matplotlib.use("Agg")

import os
import glob
import shutil
import json
import pylab
import numpy as np
from keras.callbacks import Callback, EarlyStopping, ModelCheckpoint
from keras.layers import Input, merge
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.convolutional import AtrousConvolution2D, Convolution2D, UpSampling2D
from keras.layers.core import Activation
from keras.layers.normalization import BatchNormalization
from keras.models import Model
from keras.optimizers import Adam
from keras.preprocessing.image import ImageDataGenerator
from keras.utils.visualize_util import plot
from scipy.misc import imread, imsave, imresize
from sklearn.cluster import DBSCAN
from sklearn.model_selection import GroupShuffleSplit

# Dataset
DATASET_FOLDER_PATH = os.path.join(os.path.expanduser("~"), "Documents/Dataset/The Nature Conservancy Fisheries Monitoring")
TRAIN_FOLDER_PATH = os.path.join(DATASET_FOLDER_PATH, "train")
TEST_FOLDER_PATH = os.path.join(DATASET_FOLDER_PATH, "test_stg1")
SEGMENTATION_FOLDER_PATH = os.path.join(DATASET_FOLDER_PATH, "segmentation")
ANNOTATION_FOLDER_PATH = os.path.join(DATASET_FOLDER_PATH, "annotations")
CLUSTERING_RESULT_FILE_PATH = os.path.join(DATASET_FOLDER_PATH, "clustering_result.npy")

# Workspace
WORKSPACE_FOLDER_PATH = os.path.join("/tmp", os.path.basename(DATASET_FOLDER_PATH))
CLUSTERING_FOLDER_PATH = os.path.join(WORKSPACE_FOLDER_PATH, "clustering")
ACTUAL_DATASET_FOLDER_PATH = os.path.join(WORKSPACE_FOLDER_PATH, "actual_dataset")
ACTUAL_TRAIN_ORIGINAL_FOLDER_PATH = os.path.join(ACTUAL_DATASET_FOLDER_PATH, "train_original")
ACTUAL_VALID_ORIGINAL_FOLDER_PATH = os.path.join(ACTUAL_DATASET_FOLDER_PATH, "valid_original")
ACTUAL_TRAIN_SEGMENTATION_FOLDER_PATH = os.path.join(ACTUAL_DATASET_FOLDER_PATH, "train_segmentation")
ACTUAL_VALID_SEGMENTATION_FOLDER_PATH = os.path.join(ACTUAL_DATASET_FOLDER_PATH, "valid_segmentation")

# Output
OUTPUT_FOLDER_PATH = os.path.join(DATASET_FOLDER_PATH, "{}_output".format(os.path.basename(__file__).split(".")[0]))
VISUALIZATION_FOLDER_PATH = os.path.join(OUTPUT_FOLDER_PATH, "Visualization")
OPTIMAL_WEIGHTS_FOLDER_PATH = os.path.join(OUTPUT_FOLDER_PATH, "Optimal Weights")
OPTIMAL_WEIGHTS_FILE_RULE = os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "epoch_{epoch:03d}-loss_{loss:.5f}-val_loss_{val_loss:.5f}.h5")

# Image processing
IMAGE_ROW_SIZE = 256
IMAGE_COLUMN_SIZE = 256

# Training and Testing procedure
MAXIMUM_EPOCH_NUM = 1000
PATIENCE = 100
BATCH_SIZE = 32
INSPECT_SIZE = 4

def reformat_testing_dataset():
    # Create a dummy folder
    dummy_test_folder_path = os.path.join(TEST_FOLDER_PATH, "dummy")
    os.makedirs(dummy_test_folder_path, exist_ok=True)

    # Move files to the dummy folder if needed
    file_path_list = glob.glob(os.path.join(TEST_FOLDER_PATH, "*"))
    for file_path in file_path_list:
        if os.path.isfile(file_path):
            shutil.move(file_path, os.path.join(dummy_test_folder_path, os.path.basename(file_path)))

def load_annotation():
    annotation_dict = {}
    annotation_file_path_list = glob.glob(os.path.join(ANNOTATION_FOLDER_PATH, "*.json"))
    for annotation_file_path in annotation_file_path_list:
        with open(annotation_file_path) as annotation_file:
            annotation_file_content = json.load(annotation_file)
            for item in annotation_file_content:
                key = os.path.basename(item["filename"])
                if key in annotation_dict:
                    assert False, "Found existing key {}!!!".format(key)
                value = []
                for annotation in item["annotations"]:
                    value.append(np.clip((annotation["x"], annotation["width"], annotation["y"], annotation["height"]), 0, np.inf).astype(np.int))
                annotation_dict[key] = value
    return annotation_dict

def reformat_segmentation():
    print("Creating the segmentation folder ...")
    os.makedirs(SEGMENTATION_FOLDER_PATH, exist_ok=True)

    print("Loading annotation ...")
    annotation_dict = load_annotation()

    original_image_path_list = glob.glob(os.path.join(TRAIN_FOLDER_PATH, "*/*"))
    for original_image_path in original_image_path_list:
        segmentation_image_path = SEGMENTATION_FOLDER_PATH + original_image_path[len(TRAIN_FOLDER_PATH):]
        if os.path.isfile(segmentation_image_path):
            continue

        segmentation_image_content = np.zeros(imread(original_image_path).shape[:2], dtype=np.uint8)
        for annotation_x, annotation_width, annotation_y, annotation_height in annotation_dict.get(os.path.basename(original_image_path), []):
            segmentation_image_content[annotation_y:annotation_y + annotation_height, annotation_x:annotation_x + annotation_width] = 255

        os.makedirs(os.path.abspath(os.path.join(segmentation_image_path, os.pardir)), exist_ok=True)
        imsave(segmentation_image_path, segmentation_image_content)

def perform_CV(image_path_list, resized_image_row_size=64, resized_image_column_size=64):
    if os.path.isfile(CLUSTERING_RESULT_FILE_PATH):
        print("Loading clustering result ...")
        image_name_to_cluster_ID_array = np.load(CLUSTERING_RESULT_FILE_PATH)
        image_name_to_cluster_ID_dict = dict(image_name_to_cluster_ID_array)
        cluster_ID_array = np.array([image_name_to_cluster_ID_dict[os.path.basename(image_path)] for image_path in image_path_list], dtype=np.int)
    else:
        print("Reading image content ...")
        image_content_array = np.array([imresize(imread(image_path), (resized_image_row_size, resized_image_column_size)) for image_path in image_path_list])
        image_content_array = np.reshape(image_content_array, (len(image_content_array), -1))
        image_content_array = np.array([(image_content - image_content.mean()) / image_content.std() for image_content in image_content_array], dtype=np.float32)

        print("Apply clustering ...")
        cluster_ID_array = DBSCAN(eps=1.5 * resized_image_row_size * resized_image_column_size, min_samples=20, metric="l1", n_jobs=-1).fit_predict(image_content_array)

        print("Saving clustering result ...")
        image_name_to_cluster_ID_array = np.transpose(np.vstack(([os.path.basename(image_path) for image_path in image_path_list], cluster_ID_array)))
        np.save(CLUSTERING_RESULT_FILE_PATH, image_name_to_cluster_ID_array)

    print("The ID value and count are as follows:")
    cluster_ID_values, cluster_ID_counts = np.unique(cluster_ID_array, return_counts=True)
    for cluster_ID_value, cluster_ID_count in zip(cluster_ID_values, cluster_ID_counts):
        print("{}\t{}".format(cluster_ID_value, cluster_ID_count))

    print("Visualizing clustering result ...")
    shutil.rmtree(CLUSTERING_FOLDER_PATH, ignore_errors=True)
    for image_path, cluster_ID in zip(image_path_list, cluster_ID_array):
        sub_clustering_folder_path = os.path.join(CLUSTERING_FOLDER_PATH, str(cluster_ID))
        if not os.path.isdir(sub_clustering_folder_path):
            os.makedirs(sub_clustering_folder_path)
        os.symlink(image_path, os.path.join(sub_clustering_folder_path, os.path.basename(image_path)))

    cv_object = GroupShuffleSplit(n_splits=100, test_size=0.2, random_state=0)
    for cv_index, (train_index_array, valid_index_array) in enumerate(cv_object.split(X=np.zeros((len(cluster_ID_array), 1)), groups=cluster_ID_array), start=1):
        print("Checking cv {} ...".format(cv_index))
        valid_sample_ratio = len(valid_index_array) / (len(train_index_array) + len(valid_index_array))
        if -1 in np.unique(cluster_ID_array[train_index_array]) and valid_sample_ratio > 0.15 and valid_sample_ratio < 0.25:
            train_unique_label, train_unique_counts = np.unique([image_path.split("/")[-2] for image_path in np.array(image_path_list)[train_index_array]], return_counts=True)
            valid_unique_label, valid_unique_counts = np.unique([image_path.split("/")[-2] for image_path in np.array(image_path_list)[valid_index_array]], return_counts=True)
            if np.array_equal(train_unique_label, valid_unique_label):
                train_unique_ratio = train_unique_counts / np.sum(train_unique_counts)
                valid_unique_ratio = valid_unique_counts / np.sum(valid_unique_counts)
                print("Using {:.2f}% original training samples as validation samples ...".format(valid_sample_ratio * 100))
                print("For training samples: {}".format(train_unique_ratio))
                print("For validation samples: {}".format(valid_unique_ratio))
                return train_index_array, valid_index_array

    assert False

def reorganize_dataset():
    # Get list of files
    original_image_path_list = sorted(glob.glob(os.path.join(TRAIN_FOLDER_PATH, "*/*")))
    segmentation_image_path_list = sorted(glob.glob(os.path.join(SEGMENTATION_FOLDER_PATH, "*/*")))

    # Sanity check
    original_image_name_list = [os.path.basename(image_path) for image_path in original_image_path_list]
    segmentation_image_name_list = [os.path.basename(image_path) for image_path in segmentation_image_path_list]
    assert np.array_equal(original_image_name_list, segmentation_image_name_list)

    # Perform Cross Validation
    train_index_array, valid_index_array = perform_CV(original_image_path_list)

    # Create symbolic links
    shutil.rmtree(ACTUAL_DATASET_FOLDER_PATH, ignore_errors=True)
    for (actual_original_folder_path, actual_segmentation_folder_path), index_array in zip(
            ((ACTUAL_TRAIN_ORIGINAL_FOLDER_PATH, ACTUAL_TRAIN_SEGMENTATION_FOLDER_PATH),
            (ACTUAL_VALID_ORIGINAL_FOLDER_PATH, ACTUAL_VALID_SEGMENTATION_FOLDER_PATH)),
            (train_index_array, valid_index_array)):
        for index_value in index_array:
            original_image_path = original_image_path_list[index_value]
            segmentation_image_path = segmentation_image_path_list[index_value]

            path_suffix = original_image_path[len(TRAIN_FOLDER_PATH):]
            assert path_suffix == segmentation_image_path[len(SEGMENTATION_FOLDER_PATH):]

            actual_original_image_path = actual_original_folder_path + path_suffix
            actual_segmentation_image_path = actual_segmentation_folder_path + path_suffix

            os.makedirs(os.path.abspath(os.path.join(actual_original_image_path, os.pardir)), exist_ok=True)
            os.makedirs(os.path.abspath(os.path.join(actual_segmentation_image_path, os.pardir)), exist_ok=True)

            os.symlink(original_image_path, actual_original_image_path)
            os.symlink(segmentation_image_path, actual_segmentation_image_path)

    return len(train_index_array), len(valid_index_array)

def init_model(encoder_filter_num_array=(np.arange(3) + 1) * 32, learning_rate=0.0001):
    # Vanilla input
    input_image_tensor = Input(shape=(3, IMAGE_ROW_SIZE, IMAGE_COLUMN_SIZE))

    # Encoder
    current_input_tensor = input_image_tensor
    encoder_output_tensor_list = []
    for encoder_filter_num in encoder_filter_num_array:
        current_output_tensor = AtrousConvolution2D(encoder_filter_num, 3, 3, subsample=(2, 2), atrous_rate=(2, 2), activation="linear", border_mode="same")(current_input_tensor)
        current_output_tensor = BatchNormalization(mode=0, axis=1)(current_output_tensor)
        current_output_tensor = LeakyReLU()(current_output_tensor)
        encoder_output_tensor_list.append(current_output_tensor)
        current_input_tensor = current_output_tensor

    # Decoder
    current_input_tensor = None
    decoder_filter_num_array = np.hstack((np.flipud(encoder_filter_num_array)[1:], 1))
    for layer_index, (encoder_output_tensor, decoder_filter_num) in enumerate(zip(np.flipud(encoder_output_tensor_list), decoder_filter_num_array)):
        if current_input_tensor is not None:
            current_input_tensor = merge([current_input_tensor, encoder_output_tensor], mode="concat", concat_axis=1)
        else:
            current_input_tensor = encoder_output_tensor
        current_output_tensor = UpSampling2D(size=(2, 2))(current_input_tensor)
        current_output_tensor = Convolution2D(decoder_filter_num, 3, 3, subsample=(1, 1), activation="linear", border_mode="same")(current_output_tensor)
        if layer_index != len(encoder_filter_num_array) - 1:
            current_output_tensor = BatchNormalization(mode=0, axis=1)(current_output_tensor)
            current_output_tensor = LeakyReLU()(current_output_tensor)
        else:
            current_output_tensor = Activation("sigmoid")(current_output_tensor)
        current_input_tensor = current_output_tensor

    # Define and compile the model
    model = Model(input_image_tensor, current_output_tensor)
    model.compile(optimizer=Adam(lr=learning_rate), loss="binary_crossentropy")
    plot(model, to_file=os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "model.png"), show_shapes=True, show_layer_names=True)

    return model

def load_dataset(folder_path_list, color_mode_list, batch_size, classes=None, class_mode=None, shuffle=True, seed=None):
    # Get the generator of the dataset
    data_generator_list = []
    for folder_path, color_mode in zip(folder_path_list, color_mode_list):
        data_generator_object = ImageDataGenerator(
            rotation_range=10,
            width_shift_range=0.05,
            height_shift_range=0.05,
            shear_range=0.05,
            zoom_range=0.2,
            horizontal_flip=True,
            rescale=1.0 / 255)
        data_generator = data_generator_object.flow_from_directory(
            directory=folder_path,
            target_size=(IMAGE_ROW_SIZE, IMAGE_COLUMN_SIZE),
            color_mode=color_mode,
            classes=classes,
            class_mode=class_mode,
            batch_size=batch_size,
            shuffle=shuffle,
            seed=seed)
        data_generator_list.append(data_generator)

    # Sanity check
    filenames_list = [data_generator.filenames for data_generator in data_generator_list]
    assert all(filenames == filenames_list[0] for filenames in filenames_list)

    return zip(*data_generator_list)

class InspectPrediction(Callback):
    def __init__(self, data_generator_list):
        super(InspectPrediction, self).__init__()

        self.data_generator_list = data_generator_list

    def on_epoch_end(self, epoch, logs=None):
        for data_generator_index, data_generator in enumerate(self.data_generator_list, start=1):
            X_array, GT_Y_array = next(data_generator)
            P_Y_array = self.model.predict_on_batch(X_array)

            for sample_index, (X, GT_Y, P_Y) in enumerate(zip(X_array, GT_Y_array, P_Y_array), start=1):
                pylab.figure()
                pylab.subplot(1, 3, 1)
                pylab.imshow(np.rollaxis(X, 0, 3))
                pylab.title("X")
                pylab.axis("off")
                pylab.subplot(1, 3, 2)
                pylab.imshow(GT_Y[0], cmap="gray")
                pylab.title("GT_Y")
                pylab.axis("off")
                pylab.subplot(1, 3, 3)
                pylab.imshow(P_Y[0], cmap="gray")
                pylab.title("P_Y")
                pylab.axis("off")
                pylab.savefig(os.path.join(VISUALIZATION_FOLDER_PATH, "Epoch_{}_Split_{}_Sample_{}.png".format(epoch + 1, data_generator_index, sample_index)))
                pylab.close()

class InspectLoss(Callback):
    def __init__(self):
        super(InspectLoss, self).__init__()

        self.train_loss_list = []
        self.valid_loss_list = []

    def on_epoch_end(self, epoch, logs=None):
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

def run():
    print("Creating folders ...")
    os.makedirs(VISUALIZATION_FOLDER_PATH, exist_ok=True)
    os.makedirs(OPTIMAL_WEIGHTS_FOLDER_PATH, exist_ok=True)

    print("Reformatting testing dataset ...")
    reformat_testing_dataset()

    print("Reformatting segmentation ...")
    reformat_segmentation()

    print("Reorganizing dataset ...")
    train_sample_num, valid_sample_num = reorganize_dataset()

    print("Initializing model ...")
    model = init_model()

    weights_file_path_list = sorted(glob.glob(os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "*.h5")))
    if len(weights_file_path_list) == 0:
        print("Performing the training procedure ...")
        train_generator = load_dataset(folder_path_list=[ACTUAL_TRAIN_ORIGINAL_FOLDER_PATH, ACTUAL_TRAIN_SEGMENTATION_FOLDER_PATH], color_mode_list=["rgb", "grayscale"], batch_size=BATCH_SIZE, seed=0)
        valid_generator = load_dataset(folder_path_list=[ACTUAL_VALID_ORIGINAL_FOLDER_PATH, ACTUAL_VALID_SEGMENTATION_FOLDER_PATH], color_mode_list=["rgb", "grayscale"], batch_size=BATCH_SIZE, seed=0)
        train_generator_for_inspection = load_dataset(folder_path_list=[ACTUAL_TRAIN_ORIGINAL_FOLDER_PATH, ACTUAL_TRAIN_SEGMENTATION_FOLDER_PATH], color_mode_list=["rgb", "grayscale"], batch_size=INSPECT_SIZE, seed=1)
        valid_generator_for_inspection = load_dataset(folder_path_list=[ACTUAL_VALID_ORIGINAL_FOLDER_PATH, ACTUAL_VALID_SEGMENTATION_FOLDER_PATH], color_mode_list=["rgb", "grayscale"], batch_size=INSPECT_SIZE, seed=1)
        earlystopping_callback = EarlyStopping(monitor="val_loss", patience=PATIENCE)
        modelcheckpoint_callback = ModelCheckpoint(OPTIMAL_WEIGHTS_FILE_RULE, monitor="val_loss", save_best_only=True, save_weights_only=True)
        inspectprediction_callback = InspectPrediction([train_generator_for_inspection, valid_generator_for_inspection])
        inspectloss_callback = InspectLoss()
        model.fit_generator(generator=train_generator,
                            samples_per_epoch=train_sample_num,
                            validation_data=valid_generator,
                            nb_val_samples=valid_sample_num,
                            callbacks=[earlystopping_callback, modelcheckpoint_callback, inspectprediction_callback, inspectloss_callback],
                            nb_epoch=MAXIMUM_EPOCH_NUM, verbose=2)
        weights_file_path_list = sorted(glob.glob(os.path.join(OPTIMAL_WEIGHTS_FOLDER_PATH, "*.h5")))

    print("All done!")

if __name__ == "__main__":
    run()
