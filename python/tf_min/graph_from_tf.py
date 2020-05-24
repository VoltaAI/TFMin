"""
    TFMin v1.0 Minimal TensorFlow to C++ exporter
    ------------------------------------------

    Copyright (C) 2019 Pete Blacker, Surrey Space Centre & Airbus Defence and 
    Space Ltd.
    Pete.Blacker@Surrey.ac.uk
    https://www.surrey.ac.uk/surrey-space-centre/research-groups/on-board-data-handling

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    in the LICENCE file of this software.  If not, see
    <http://www.gnu.org/licenses/>.

    ---------------------------------------------------------------------

    This module contains the Tensorflow v1.x importer which generates a 
    TFMin Graph object from a Tensorflow interactive session. 
"""
import tensorflow as tf
import numpy as np
import tf_min.graph as tg


TF_OP_TRANSLATIONS = {'DepthwiseConv2DNative': 'DepthwiseConv2D'}


def np_type_to_tfmin(np_type):
  if np_type == np.float32:
    return "Float32"
  if np_type == np.float64:
    return "Float64"
  if np_type == np.uint8:
    return "Uint8"
  if np_type == np.int8:
    return "Int8"
  if np_type == np.int16:
    return "Int16"
  if np_type == np.int32:
    return "Int32"
  if np_type == np.int64:
    return "Int64"
  return "Unknown_Type"


def tf_shape_to_np(tf_shape):
  np_shape = []
  for dim in tf_shape.dims:
    if dim.value is None:
      np_shape.append(-1)
    else:
      np_shape.append(dim.value)
  return np_shape


def get_opr_input_params(tf_opr, sess):
  """
  Function to extract effective parameterw which TF insists on passing as
  tensor inputs. This is really messey, so this function extracts their
  values adds them as const parameters instead and removes the link to the
  input tensor
  :param tf_opr:
  :param sess: tf.InteractiveSession used to resolve contant values
  :return:
  """
  additional_params = {}
  # crude copy of inputs array to create a genunine python list instead.
  valid_inputs = []
  for input in tf_opr.inputs:
    valid_inputs.append(input)

  if tf_opr.type == "ArgMax":
    [value] = sess.run([tf_opr.inputs[1]], {})
    # print("Got a value of [%s] type [%s]" % (value, str(type(value))))
    additional_params["dim"] = value
    valid_inputs.remove(valid_inputs[1])
  elif tf_opr.type == "Reshape":
    [shape] = sess.run([tf_opr.inputs[1]], {})
    additional_params['shape'] = shape
    valid_inputs.remove(valid_inputs[1])

  return [additional_params, valid_inputs]


def add_tf_tensor(graph, tf_tensor, sess):
    # skip if this tensor has already been added
    for tensor in graph.tensors:
        if tensor.label == tf_tensor.name:
            return tensor

    new_tensor = tf_to_tensor(tf_tensor)
    new_tensor.creating_op = add_tf_op(graph, tf_tensor.op, sess)
    new_tensor.creating_op.outputs.append(new_tensor)
    graph.tensors.append(new_tensor)
    return new_tensor


def add_tf_op(graph, tf_op, sess):
  # skip if this op has already been added
  for opr in graph.ops:
    if opr.label == tf_op.name:
      return opr

  # add this operation and input tensors
  new_op = tf_to_operation(tf_op, sess)
  [_, valid_inputs] = get_opr_input_params(tf_op, sess)
  for tensor in valid_inputs:
    new_tensor = add_tf_tensor(graph, tensor, sess)
    new_op.inputs.append(new_tensor)
    new_tensor.dependent_ops.append(new_op)
  graph.ops.append(new_op)

  return new_op


def mark_inputs(self):
  ops_to_remove = []
  for opr in self.ops:
    if opr.type == "Placeholder":
      input_tensor = opr.outputs[0]
      input_tensor.creating_op = None
      input_tensor.type = tg.TenType.INPUT
      ops_to_remove.append(opr)

  for opr in ops_to_remove:
    self.ops.remove(self.ops[self.get_opr_idx(opr)])


def mark_weights(self, sess):
  weight_op_types = ["Const", "Variable", "VariableV2"]
  ops_to_remove = []
  for opr in self.ops:
    if opr.type in weight_op_types:
      weights_tensor = opr.outputs[0]
      weights_tensor.creating_op = None
      weights_tensor.type = tg.TenType.CONSTANT
      tf_tensor = sess.graph.get_tensor_by_name(weights_tensor.label)
      value = sess.run([tf_tensor], {})
      weights_tensor.value = value
      ops_to_remove.append(opr)

  for opr in ops_to_remove:
    self.ops.remove(self.ops[self.get_opr_idx(opr)])


def tf_to_tensor(tf_tensor):
    new_tensor = tg.Tensor()
    new_tensor.label = tf_tensor.name
    new_tensor.d_type = np_type_to_tfmin(tf_tensor.dtype.as_numpy_dtype)
    new_tensor.shape = tf_shape_to_np(tf_tensor.shape)
    new_tensor.type = tg.TenType.INTERMEDIATE
    return new_tensor


def tf_to_operation(tf_opr, sess):
    opr = tg.Operation()
    opr.type = tf_opr.type
    opr.label = tf_opr.name

    # translate operation type from tflite to TFMin
    if opr.type in TF_OP_TRANSLATIONS:
      opr.type = TF_OP_TRANSLATIONS[self.type]

    # Brutally hacky way of getting the list of attributes
    # from a tensorflow.core.framework.node_def_pb2.NodeDef
    lines = str(tf_opr.node_def).split("\n")
    for line in lines:
      if line.startswith("  key: \""):
        key = line[8:100].replace("\"", "")

        # add recognised parameter types
        if key == "dtype":
          opr.params['dtype'] = np_type_to_tfmin(
            tf_opr.get_attr(key)
          )
        elif key == "dilations":
          opr.params['dilation_height_factor'] = \
            tf_opr.get_attr(key)[1]
          opr.params['dilation_width_factor'] = \
            tf_opr.get_attr(key)[2]
        elif key == "padding":
          opr.params['padding'] = \
            tf_opr.get_attr(key).decode('utf-8')
        elif key == "strides":
          opr.params['stride_height'] = \
            tf_opr.get_attr(key)[1]
          opr.params['stride_width'] = \
            tf_opr.get_attr(key)[2]
        elif key == "ksize":
          opr.params['kernel_height'] = tf_opr.get_attr(key)[1]
          opr.params['kernel_width'] = tf_opr.get_attr(key)[2]

    [add_params, _] = get_opr_input_params(tf_opr, sess)
    opr.params.update(add_params)
    return opr

def graph_from_tf_sess(sess, outputs):
    """
    method to populate this grah from the given session and list of output
    tensors
    :param sess: TF interactive session which includes the source flow graph
    :param outputs: list of output tensors (either string of their
                    name or objects)
    :return: True on success, False on failure
    """
    new_graph = tg.Graph()

    # Convert and strings in the outputs list to their tensor objects
    output_tensors = []
    for out in outputs:
        if isinstance(out, tf.Tensor):
            output_tensors.append(out)
        else:
            try:
                output_tensors.append(
                    sess.graph.get_tensor_by_name(out))
            except KeyError:
                print("Error: No tensor named \"%s\" found in graph!" % out)
                for opr in sess.graph.get_operations():
                    for ten in opr.outputs:
                        print("Did you mean : %s" % ten.name)

    # add each tensor and recurrively all preceding operations and
    # tensors. Marking them as outputs.
    for output_tensor in output_tensors:
        new_tensor = add_tf_tensor(new_graph, output_tensor, sess)
        new_tensor.type = tg.TenType.OUTPUT

    mark_inputs(new_graph)
    mark_weights(new_graph, sess)

    return new_graph
