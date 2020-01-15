# -*- coding: utf-8 -*-

# Commented out IPython magic to ensure Python compatibility.
# %load_ext tensorboard

# Commented out IPython magic to ensure Python compatibility.
# %tensorflow_version 2.x
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf
import os
import datetime
from tensorflow.keras.preprocessing import image
from zipfile import ZipFile 
from tensorflow.keras.preprocessing.image import ImageDataGenerator

tf.test.gpu_device_name()

!rm -rf sample_data

!mkdir -p /root/.kaggle
!touch /root/.kaggle/kaggle.json
!chmod 600 /root/.kaggle/kaggle.json

!echo '{"username":"USERNAME","key":"API_KEY"}' > /root/.kaggle/kaggle.json

!kaggle datasets download "chetankv/dogs-cats-images"

!unzip -q dogs-cats-images.zip

"""## Reading dogs vs cats ds"""

test_dir="dog vs cat/dataset/test_set"
train_dir="dog vs cat/dataset/training_set"

train_dir_cats = train_dir + '/cats'
train_dir_dogs = train_dir + '/dogs'
test_dir_cats = test_dir + '/cats'
test_dir_dogs = test_dir + '/dogs'

import pathlib
DATA_DIR = "dog vs cat/dataset/"
train_dir = pathlib.Path(DATA_DIR + "training_set")
test_dir = pathlib.Path(DATA_DIR + "test_set")

train_image_count = len(list(train_dir.glob('*/*.jpg')))
test_image_count = len(list(test_dir.glob('*/*.jpg')))
(train_image_count, test_image_count)

CLASS_NAMES = np.array([item.name for item in train_dir.glob('*') if item.name != "LICENSE.txt"])
CLASS_NAMES

IMG_WIDTH, IMG_HEIGHT = 224, 224
BATCH_SIZE = 25

data_generator = ImageDataGenerator(rescale = 1.0/255.0, zoom_range = 0.2)

def list_files(data_dir):
  return tf.data.Dataset.list_files(str(data_dir/'*/*'))

def get_label(file_path):
  # convert the path to a list of path components
  parts = tf.strings.split(file_path, os.path.sep)
  # The second to last is the class-directory
  return parts[-2] == CLASS_NAMES

def decode_img(img):
  # convert the compressed string to a 3D uint8 tensor
  img = tf.image.decode_jpeg(img, channels=3)
  # Use `convert_image_dtype` to convert to floats in the [0,1] range.
  img = tf.image.convert_image_dtype(img, tf.float32)
  # resize the image to the desired size.
  return tf.image.resize(img, [IMG_WIDTH, IMG_HEIGHT])

def process_path(file_path):
  label = get_label(file_path)
  # load the raw data from the file as a string
  img = tf.io.read_file(file_path)
  img = decode_img(img)
  return img, label

AUTOTUNE = 100

def load_cats_vs_dogs():
  train_list_ds = list_files(train_dir)
  test_list_ds = list_files(test_dir)

  for f in train_list_ds.take(5):
    print(f.numpy())
  # Set `num_parallel_calls` so multiple images are loaded/processed in parallel.
  return (
      train_list_ds.map(process_path, num_parallel_calls=AUTOTUNE),
      test_list_ds.map(process_path, num_parallel_calls=AUTOTUNE),
  )

train_labeled_ds, test_labeled_ds = load_cats_vs_dogs()

for image, label in train_labeled_ds.take(1):
  print("Image shape: ", image.numpy().shape)
  print("Label: ", label.numpy())

def prepare_for_training(ds, batch_size=BATCH_SIZE, cache=True, shuffle_buffer_size=1000):
  # This is a small dataset, only load it once, and keep it in memory.
  # use `.cache(filename)` to cache preprocessing work for datasets that don't
  # fit in memory.
  if cache:
    if isinstance(cache, str):
      ds = ds.cache(cache)
    else:
      ds = ds.cache()

  ds = ds.shuffle(buffer_size=shuffle_buffer_size)

  # Repeat forever
  ds = ds.repeat()

  ds = ds.batch(batch_size)

  # `prefetch` lets the dataset fetch batches in the background while the model
  # is training.
  ds = ds.prefetch(buffer_size=AUTOTUNE)

  return ds

train_ds = prepare_for_training(train_labeled_ds)
test_ds = prepare_for_training(test_labeled_ds)

image_batch, label_batch = next(iter(train_ds))

def show_batch(image_batch, label_batch):
  plt.figure(figsize=(10,10))
  for n in range(25):
      ax = plt.subplot(5,5,n+1)
      plt.imshow(image_batch[n])
      plt.title(CLASS_NAMES[label_batch[n]==1][0].title())
      plt.axis('off')

show_batch(image_batch.numpy(), label_batch.numpy())

label_batch.numpy()

"""## TF for local runs"""

def allow_memory_growth():
    gpus = tf.config.experimental.list_physical_devices('GPU')
    if gpus:
        try:
            # Currently, memory growth needs to be the same across GPUs
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
            logical_gpus = tf.config.experimental.list_logical_devices('GPU')
            print(len(gpus), "Physical GPUs,", len(logical_gpus), "Logical GPUs")
        except RuntimeError as e:
            # Memory growth must be set before GPUs have been initialized
            print(e)
# run the line below if you're using local runtime and have GTX > 1660 (this is known bug with tensorflow memory allocation)
# allow_memory_growth()

"""## Model definition"""

import tensorflow.keras.layers as layers
from tensorflow.keras import Sequential
from tensorflow.keras.applications import MobileNetV2

class AttensionALPModel(tf.keras.Model):

  def __init__(self, num_classes, input_shape=(IMG_WIDTH, IMG_HEIGHT, 3)):
    super(AttensionALPModel, self).__init__(name="attension_alp_model")
    self.num_classes = num_classes
    self.res_net = MobileNetV2(include_top=False, input_shape=input_shape, weights='imagenet')
    self.classifier = Sequential()
    self.classifier.add(layers.GlobalAveragePooling2D())
    self.classifier.add(layers.Dense(num_classes, activation='softmax'))

    for layer in self.res_net.layers[:-10]:
      layer.trainable = False

  def call(self, inputs):
    resnet_features = self.res_net(inputs)
    return self.classifier(resnet_features)
    
def train_step_attension_alp_model(attension_alp_model, 
                                   optim,
                                   loss_f,
                                   train_loss,
                                   train_accuracy,
                                   adversarial_pattern_finder=None,
                                   alp_weight=1):
  @tf.function
  def _train_step_attension_alp_model(images, labels):

    adv_out =  attension_alp_model(adversarial_pattern_finder.transform(images, labels, {}, {})) if adversarial_pattern_finder else 0

    with tf.GradientTape() as tape:
      gen_out = attension_alp_model(images) 

        # Use alp if use_alp is True 
      loss = loss_f(labels, gen_out)
      if adversarial_pattern_finder: 
        loss += alp_weight * tf.nn.l2_loss(gen_out - adv_out)
    
    grads = tape.gradient(loss, attension_alp_model.classifier.trainable_variables)
    optim.apply_gradients(zip(grads, attension_alp_model.classifier.trainable_variables))

    train_loss(loss)
    train_accuracy(labels, gen_out)
  return _train_step_attension_alp_model

def validation_step_attension_alp_model(attension_alp_model, 
                                        loss_f,
                                        validation_loss,
                                        validation_accuracy):
  @tf.function
  def _validation_step_attension_alp_model(images, labels):
    gen_out = attension_alp_model(images)      
    loss = loss_f(labels, gen_out)

    validation_loss(loss)
    validation_accuracy(labels, gen_out)

  return _validation_step_attension_alp_model

current_time = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
train_log_dir = 'logs/gradient_tape/' + current_time + '/train'
validation_log_dir = 'logs/gradient_tape/' + current_time + '/validation'
train_summary_writer = tf.summary.create_file_writer(train_log_dir)
validation_summary_writer = tf.summary.create_file_writer(validation_log_dir)

def train(train_step, 
          validation_step, 
          train_ds, 
          validation_ds,
          epochs,
          train_steps_per_epoch,
          validation_steps_per_epoch
          ):
  for epoch in range(epochs):
    
    for i, (images, labels) in enumerate(train_ds):
      train_step(images, labels)
      if i == train_steps_per_epoch:
        break

    with train_summary_writer.as_default():
      tf.summary.scalar("loss", train_loss.result(), step=epoch)
      tf.summary.scalar("accuracy", train_accuracy.result(), step=epoch)

    for i, (images, labels) in enumerate(validation_ds):
      validation_step(images, labels)
      if i == validation_steps_per_epoch:
        break

    with validation_summary_writer.as_default():
      tf.summary.scalar("loss", validation_loss.result(), step=epoch)
      tf.summary.scalar("accuracy", validation_accuracy.result(), step=epoch)


    template = 'Epoch {}, Loss: {}, Accuracy: {} , Validation Loss: {}, Validation Accuracy: {}'
    print (template.format(epoch+1,
                          train_loss.result(), 
                          train_accuracy.result(),
                          validation_loss.result(), 
                          validation_accuracy.result()))

    train_loss.reset_states()
    train_accuracy.reset_states()
    validation_loss.reset_states()
    validation_accuracy.reset_states()

"""## FGSM model"""

class AdversarialPaternFinder(object):
  def __init__(self, model):
    self.model = model

  def create_adversarial_pattern(self, input_image, input_label, **kwargs):
    raise NotImplementedError

  def apply_adversarial_pattern(self, pattern, input_image, **kwargs):
    raise NotImplementedError

  def transform(self, input_image, input_label, 
                                   create_args, apply_args):
    pattern = self.create_adversarial_pattern(input_image, input_label, 
                                               **create_args)
    return self.apply_adversarial_pattern(pattern, input_image, **apply_args)

class FGSM(AdversarialPaternFinder):
  def create_adversarial_pattern(self, input_image, input_label, **kwargs):
    loss_object = kwargs.get('loss_object', tf.keras.losses.CategoricalCrossentropy())
    
    with tf.GradientTape() as tape:
      tape.watch(input_image)
      prediction = self.model(input_image)
      loss = loss_object(input_label, prediction)

    # Get the gradients of the loss w.r.t to the input image.
    gradient = tape.gradient(loss, input_image)
    # Get the sign of the gradients to create the perturbation
    signed_grad = tf.sign(gradient)
    return signed_grad

  def apply_adversarial_pattern(self, pattern, input_image, **kwargs):
    epsilon = kwargs.get("epsilon", 0.01)
    return input_image + epsilon * pattern

"""## Train Model"""

optim = tf.optimizers.Nadam()

train_loss = tf.keras.metrics.Mean('train_loss', dtype=tf.float32)
train_accuracy = tf.keras.metrics.CategoricalAccuracy('train_accuracy')
validation_loss = tf.keras.metrics.Mean('validation_loss', dtype=tf.float32)
validation_accuracy = tf.keras.metrics.CategoricalAccuracy('validation_accuracy')

# adv_images = list(iter(fgsm_generator(image_batch, label_batch, 0.05)))

attension_alp_model = AttensionALPModel(2)
fgsm = FGSM(attension_alp_model)

train_step = train_step_attension_alp_model(
    attension_alp_model=attension_alp_model,
    optim=optim,
    loss_f=tf.keras.losses.categorical_crossentropy,
    train_loss=train_loss,
    train_accuracy=train_accuracy,
    adversarial_pattern_finder=fgsm,
    alp_weight=0.001)
    # adversarial_pattern_finder=None)

validation_step = validation_step_attension_alp_model(
    attension_alp_model,
    loss_f=tf.keras.losses.categorical_crossentropy,
    validation_loss=validation_loss,
    validation_accuracy=validation_accuracy
)

"""## Generate Adversarial Examples"""

def fgsm_generator(image_batch, label_batch, epsilon=0.01, loss_object=tf.keras.losses.CategoricalCrossentropy()):
  paternFinder = FGSM(attension_alp_model)
  
  for image, label in zip(image_batch, label_batch):
    perturbations = paternFinder.transform(image[None,:,:,:], label, {'loss_object': loss_object}, {'epsilon': epsilon})
    yield np.clip(perturbations[0].numpy(), 0, 1)[None,:,:,:]


adv_examples = list(iter(fgsm_generator(image_batch, label_batch, 0.05)))

show_batch([np.squeeze(x, axis=0) for x in adv_examples], label_batch.numpy())

# Commented out IPython magic to ensure Python compatibility.
# %tensorboard --logdir logs/gradient_tape

train(train_step, 
      validation_step,
      train_ds,
      test_ds,
      3,
      train_steps_per_epoch=train_image_count / BATCH_SIZE,
      validation_steps_per_epoch=test_image_count / BATCH_SIZE)

import tensorflow.keras.metrics as metrics

attension_alp_model.summary()