"""Relevant numerical/decoder versions participate in analysis cache identity."""

import cv2
import numpy as np
import PIL


def image_runtime():
    return {"pillow": PIL.__version__, "numpy": np.__version__, "opencv": cv2.__version__}
