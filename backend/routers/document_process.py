import os
import shutil
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from database import get_db
from models import Document
from utils.rag_builder import build_faiss_index
from utils.authentication import get_current_user

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./data/uploads")
ALLOWED_EXTENSIONS = {".pdf", ".txt"}

router = APIRouter()


@router.post(
    "/upload_documents",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "One or more PDF or TXT files",
                            }
                        },
                    }
                }
            },
            "required": True,
        }
    },
)
def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Accept one or more PDF/TXT files, persist each file to disk,
    build a per-document FAISS vector index, and record metadata in the DB.
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    user_id = current_user["id"]  # already int from get_current_user
    results = []

    for upload in files:
        ext = os.path.splitext(upload.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type '{ext}'. Allowed types: PDF, TXT.",
            )

        # Create DB record first so we can use its ID for a collision-free filename
        doc = Document(user_id=user_id, filename=upload.filename)
        db.add(doc)
        db.flush()  # assigns doc.id without committing yet

        # Store file as  <user_id>_<doc_id><ext>  to avoid path-traversal risks
        safe_filename = f"{user_id}_{doc.id}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)

        # Build FAISS index from the saved file
        try:
            index_path = build_faiss_index(file_path, user_id, doc.id)
            doc.faiss_index_path = index_path
        except Exception as exc:
            db.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to build FAISS index for '{upload.filename}': {exc}",
            )

        db.commit()
        db.refresh(doc)
        results.append(
            {"id": doc.id, "filename": doc.filename, "index_path": index_path}
        )

    return {
        "message": f"Successfully processed {len(results)} document(s).",
        "documents": results,
    }


@router.get("/documents")
def get_documents(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return all documents belonging to the authenticated user."""
    user_id = current_user["id"]
    docs = (
        db.query(Document)
        .filter(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [
        {"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat()}
        for d in docs
    ]


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete a document, its uploaded file, and its FAISS index."""
    user_id = current_user["id"]
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.user_id == user_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # Remove uploaded file (try both extensions)
    for ext in ALLOWED_EXTENSIONS:
        file_path = os.path.join(UPLOAD_DIR, f"{user_id}_{doc_id}{ext}")
        if os.path.exists(file_path):
            os.remove(file_path)

    # Remove FAISS index directory
    if doc.faiss_index_path and os.path.exists(doc.faiss_index_path):
        shutil.rmtree(doc.faiss_index_path, ignore_errors=True)

    db.delete(doc)
    db.commit()
    return None
