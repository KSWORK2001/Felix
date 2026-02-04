import base64
import io
from typing import Optional

from PIL import Image


def image_base64_to_pil(image_base64: str) -> Image.Image:
    raw = base64.b64decode(image_base64)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def ocr_image_pil(img: Image.Image) -> str:
    try:
        import pytesseract
    except Exception as e:
        raise RuntimeError("pytesseract is not installed. Add pytesseract to requirements and install Tesseract OCR.") from e

    try:
        return pytesseract.image_to_string(img)
    except Exception as e:
        raise RuntimeError("OCR failed. Ensure Tesseract OCR is installed and available on PATH.") from e


def ocr_image_base64(image_base64: str) -> str:
    img = image_base64_to_pil(image_base64)
    return ocr_image_pil(img)
