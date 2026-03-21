"""Reusable file-upload helpers."""

import os
import uuid

from flask import current_app

from app.constants import ALLOWED_IMAGE_EXTENSIONS


def save_photo(file_storage, folder='incentive'):
    """Save an uploaded image to *static/uploads/<folder>/*.

    Returns the relative path (e.g. ``uploads/incentive/abc123.jpg``)
    suitable for storing in the database, or ``None`` if the file is
    missing or has a disallowed extension.
    """
    if not file_storage or not file_storage.filename:
        return None

    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None

    fname = f'{uuid.uuid4().hex[:12]}{ext}'
    save_dir = os.path.join(current_app.root_path, 'static', 'uploads', folder)
    os.makedirs(save_dir, exist_ok=True)
    file_storage.save(os.path.join(save_dir, fname))
    return f'uploads/{folder}/{fname}'
