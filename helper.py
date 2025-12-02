import os, math, zipfile, shutil, asyncio
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from config import Config
from pyrogram import Client
from math import ceil

async def extract_metadata(file_path):
    try:
        parser = createParser(file_path)
        metadata = extractMetadata(parser)
        if not metadata:
            return {}
        data = metadata.exportDictionary()
        # flatten to string-friendly map
        out = {}
        for k, v in data.items():
            out[k] = str(v)
        return out
    except Exception:
        return {}

def ensure_dirs():
    os.makedirs(Config.TMP_DIR, exist_ok=True)
    os.makedirs(Config.THUMB_DIR, exist_ok=True)

def split_file(file_path, chunk_size_bytes):
    parts = []
    total = os.path.getsize(file_path)
    count = ceil(total / chunk_size_bytes)
    with open(file_path, "rb") as f:
        for i in range(count):
            part_path = f"{file_path}.part{i+1:03d}"
            with open(part_path, "wb") as pf:
                pf.write(f.read(chunk_size_bytes))
            parts.append(part_path)
    return parts

def zip_file(src_path, dest_zip):
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        arcname = os.path.basename(src_path)
        zf.write(src_path, arcname=arcname)
    return dest_zip

async def remove_files(paths):
    for p in paths:
        try:
            os.remove(p)
        except:
            pass

async def send_with_progress(client: Client, chat_id, file_path, caption=None, thumb=None):
    """
    Sends a file as document and yields the sent message.
    Uses client.send_document (can be edited to send video/audio if needed).
    """
    return await client.send_document(chat_id=chat_id, document=file_path, caption=caption, thumb=thumb)
