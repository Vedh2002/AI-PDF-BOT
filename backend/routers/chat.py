import json
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from config import DEFAULT_LLM_PROVIDER
from database import get_db
from models import Conversation, Document
from utils.authentication import get_current_user
from utils.llm_client import get_llm_response
from utils.rag_builder import load_faiss_index

TOP_K_CHUNKS = 5

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    document_id: int
    question: str
    provider: Literal["groq", "openai"] = DEFAULT_LLM_PROVIDER
    model: Optional[str] = None
    conversation_history: List[Message] = []

    @field_validator("model", mode="before")
    @classmethod
    def blank_model_to_none(cls, v):
        """Treat empty string or Swagger placeholder 'string' as no override."""
        if v == "" or v == "string":
            return None
        return v


class ChatResponse(BaseModel):
    answer: str
    conversation_id: int
    conversation_history: List[Message]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    RAG-powered Q&A over a user's document.

    Flow:
      1. Verify the document belongs to the authenticated user.
      2. Embed the question and retrieve the top-K relevant chunks from FAISS.
      3. Build a grounded prompt: system (context) + prior history + user question.
      4. Call the chosen LLM (Groq or OpenAI).
      5. Persist the conversation to the DB.
      6. Return the answer plus the updated conversation history.
    """
    user_id = current_user["id"]  # already int from get_current_user

    # -- 1. Ownership check ---------------------------------------------------
    doc = (
        db.query(Document)
        .filter(Document.id == request.document_id, Document.user_id == user_id)
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    # -- 2. Load FAISS index & retrieve relevant chunks ----------------------
    try:
        vector_store = load_faiss_index(user_id, request.document_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vector index not found for this document. Please re-upload the file.",
        )

    results = vector_store.similarity_search(request.question, k=TOP_K_CHUNKS)
    context = "\n\n---\n\n".join(chunk.page_content for chunk in results)

    # -- 3. Build prompt messages --------------------------------------------
    system_message = {
        "role": "system",
        "content": (
            "You are a helpful assistant that answers questions strictly based on "
            "the provided document context. If the answer cannot be found in the "
            "context, say you don't know. Do not fabricate information.\n\n"
            f"Document context:\n{context}"
        ),
    }
    history = [{"role": m.role, "content": m.content} for m in request.conversation_history]
    user_message = {"role": "user", "content": request.question}

    messages = [system_message] + history + [user_message]

    # -- 4. Call LLM ---------------------------------------------------------
    try:
        answer = get_llm_response(
            messages, provider=request.provider, model=request.model
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM request failed: {exc}",
        )

    # -- 5. Build updated history & persist ----------------------------------
    updated_history = request.conversation_history + [
        Message(role="user", content=request.question),
        Message(role="assistant", content=answer),
    ]

    conv = Conversation(
        user_id=user_id,
        document_id=request.document_id,
        question=request.question,
        answer=answer,
        conversation_history=json.dumps([m.model_dump() for m in updated_history]),
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # -- 6. Return -----------------------------------------------------------
    return ChatResponse(
        answer=answer,
        conversation_id=conv.id,
        conversation_history=updated_history,
    )


# ---------------------------------------------------------------------------
# Chat history endpoint
# ---------------------------------------------------------------------------

class ConversationRecord(BaseModel):
    id: int
    question: str
    answer: str
    created_at: str
    conversation_history: List[Message]

    class Config:
        from_attributes = True


@router.get("/chat/history/{document_id}", response_model=List[ConversationRecord])
def get_chat_history(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Return all saved Q&A turns for a specific document, newest first.
    Only returns conversations that belong to the authenticated user.
    """
    user_id = current_user["id"]

    # Verify the document belongs to this user
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user_id)
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied.",
        )

    conversations = (
        db.query(Conversation)
        .filter(Conversation.document_id == document_id, Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .all()
    )

    return [
        ConversationRecord(
            id=c.id,
            question=c.question,
            answer=c.answer,
            created_at=c.created_at.isoformat(),
            conversation_history=[
                Message(**m) for m in json.loads(c.conversation_history or "[]")
            ],
        )
        for c in conversations
    ]
