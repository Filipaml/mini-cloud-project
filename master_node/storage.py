import hashlib
import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from db import get_db
from models import File as FileModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["storage"])

STORAGE_PATHS: dict[str, Path] = {
    "primary": Path("/data/storage"),
    "replica": Path("/data/storage_replica"),
}
for p in STORAGE_PATHS.values():
    p.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 1024 * 1024              # 1 MiB
MAX_FILE_SIZE = 500 * 1024 * 1024     # 500 MiB


# ---------- helpers ----------

async def _close_all(files: dict) -> None:
    for f in files.values():
        try:
            await f.close()
        except Exception:  # pragma: no cover
            pass


def _cleanup_paths(paths: list[Path]) -> None:
    for p in paths:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ---------- endpoints ----------

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    """
    Upload com streaming + replicação síncrona para 2 volumes.
    SHA-256 é calculado durante o stream (não numa segunda passagem).
    """
    file_id = uuid.uuid4()
    hasher = hashlib.sha256()
    total = 0
    written_paths = [path / str(file_id) for path in STORAGE_PATHS.values()]
    open_files: dict[str, "aiofiles.threadpool.binary.AsyncBufferedIOBase"] = {}

    try:
        # 1. Abrir todas as réplicas para escrita
        for name, base in STORAGE_PATHS.items():
            open_files[name] = await aiofiles.open(base / str(file_id), "wb")

        # 2. Streaming em chunks
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise HTTPException(status_code=413, detail="File too large")
            hasher.update(chunk)
            for f in open_files.values():
                await f.write(chunk)

    except HTTPException:
        # 413 / outros HTTP — não embrulhar em 500
        await _close_all(open_files)
        _cleanup_paths(written_paths)
        raise
    except Exception as e:
        logger.exception("Upload failed for %s", file.filename)
        await _close_all(open_files)
        _cleanup_paths(written_paths)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    else:
        await _close_all(open_files)

    # 3. Metadata (só depois dos bytes estarem em disco)
    meta = FileModel(
        id=file_id,
        owner_username=user,
        filename=file.filename or str(file_id),
        content_type=file.content_type,
        size_bytes=total,
        sha256=hasher.hexdigest(),
        locations=",".join(STORAGE_PATHS.keys()),
    )
    try:
        db.add(meta)
        db.commit()
    except Exception as e:
        # Se a BD falha, apaga os bytes para não deixar "ficheiros órfãos"
        db.rollback()
        _cleanup_paths(written_paths)
        logger.exception("DB commit failed; rolled back replicas")
        raise HTTPException(status_code=500, detail=f"Metadata persist failed: {e}")

    return {
        "file_id": str(file_id),
        "filename": meta.filename,
        "size": total,
        "sha256": meta.sha256,
        "replicas": list(STORAGE_PATHS.keys()),
    }


@router.get("")
def list_files(
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    rows = (
        db.query(FileModel)
        .filter(FileModel.owner_username == user)
        .order_by(FileModel.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(r.id),
            "filename": r.filename,
            "size": r.size_bytes,
            "content_type": r.content_type,
            "sha256": r.sha256,
            "created_at": r.created_at.isoformat(),
            "replicas": r.locations.split(","),
        }
        for r in rows
    ]


@router.get("/{file_id}")
async def download_file(
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    """Download com streaming + fallback automático para réplica."""
    meta = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not meta:
        raise HTTPException(status_code=404, detail="File not found")
    if meta.owner_username != user:
        raise HTTPException(status_code=403, detail="Forbidden")

    for loc in meta.locations.split(","):
        if loc not in STORAGE_PATHS:
            continue
        path = STORAGE_PATHS[loc] / str(file_id)
        if not path.exists():
            logger.warning("Replica '%s' missing for %s, tentando próxima", loc, file_id)
            continue

        async def stream(p: Path = path):
            async with aiofiles.open(p, "rb") as f:
                while True:
                    chunk = await f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            stream(),
            media_type=meta.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{meta.filename}"',
                "X-File-SHA256": meta.sha256,
                "X-Replica-Used": loc,   # útil para o teste de fallback
            },
        )

    logger.error("Todas as réplicas em falta para %s", file_id)
    raise HTTPException(status_code=500, detail="All replicas unavailable")


@router.delete("/{file_id}")
def delete_file(
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    meta = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not meta or meta.owner_username != user:
        raise HTTPException(status_code=404, detail="File not found")

    for loc in meta.locations.split(","):
        if loc in STORAGE_PATHS:
            (STORAGE_PATHS[loc] / str(file_id)).unlink(missing_ok=True)

    db.delete(meta)
    db.commit()
    return {"deleted": str(file_id)}