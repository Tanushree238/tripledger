from pathlib import Path

from fastapi import HTTPException, UploadFile


async def read_receipt(file: UploadFile) -> tuple[bytes, str]:
    max_size = 10 * 1024 * 1024
    signatures = {
        '.pdf': b'%PDF-',
        '.png': b'\x89PNG\r\n\x1a\n',
        '.jpg': b'\xff\xd8',
        '.jpeg': b'\xff\xd8',
    }
    extension = Path(file.filename or '').suffix.lower()
    content = await file.read(max_size + 1)
    if extension not in signatures or len(content) > max_size or not content.startswith(signatures[extension]):
        raise HTTPException(400, 'Use a valid PDF, PNG or JPEG up to 10 MB')
    return content, extension
