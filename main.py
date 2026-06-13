import os
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from openai import OpenAI

from database import Thread, Message, get_db, init_db, UNIVERSAL_THREAD_ID

load_dotenv()

app = FastAPI(title="AI Chatbot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


def get_llm_client() -> OpenAI:
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        return OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_model() -> str:
    return os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")


class ThreadCreate(BaseModel):
    name: str


class MessageCreate(BaseModel):
    content: str


@app.get("/threads")
def list_threads(db: Session = Depends(get_db)):
    threads = db.query(Thread).order_by(Thread.id).all()
    return [{"id": t.id, "name": t.name, "created_at": t.created_at} for t in threads]


@app.post("/threads", status_code=201)
def create_thread(body: ThreadCreate, db: Session = Depends(get_db)):
    thread = Thread(name=body.name.strip())
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return {"id": thread.id, "name": thread.name, "created_at": thread.created_at}


@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: int, db: Session = Depends(get_db)):
    if thread_id == UNIVERSAL_THREAD_ID:
        raise HTTPException(status_code=400, detail="Cannot delete the Universal Memory thread")
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    db.delete(thread)
    db.commit()
    return {"message": "Thread deleted"}


@app.get("/threads/{thread_id}/messages")
def get_messages(thread_id: int, db: Session = Depends(get_db)):
    if not db.query(Thread).filter(Thread.id == thread_id).first():
        raise HTTPException(status_code=404, detail="Thread not found")
    msgs = (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.created_at)
        .all()
    )
    return [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at} for m in msgs]


@app.post("/threads/{thread_id}/messages")
def send_message(thread_id: int, body: MessageCreate, db: Session = Depends(get_db)):
    if not db.query(Thread).filter(Thread.id == thread_id).first():
        raise HTTPException(status_code=404, detail="Thread not found")

    # Persist user message first
    db.add(Message(thread_id=thread_id, role="user", content=body.content))
    db.commit()

    # Build system prompt, injecting Universal Memory for non-universal threads
    system_prompt = (
        "You are a helpful, concise AI assistant. "
        "Answer clearly and stay on topic."
    )

    if thread_id != UNIVERSAL_THREAD_ID:
        universal_msgs = (
            db.query(Message)
            .filter(Message.thread_id == UNIVERSAL_THREAD_ID)
            .order_by(Message.created_at)
            .all()
        )
        if universal_msgs:
            memory_lines = "\n".join(
                f"{m.role.upper()}: {m.content}" for m in universal_msgs
            )
            system_prompt += (
                "\n\n--- Universal Memory (shared across all threads) ---\n"
                f"{memory_lines}\n"
                "--- End of Universal Memory ---\n\n"
                "Use the above memory to maintain continuity and context across conversations."
            )

    # Fetch current thread history (includes the message just saved)
    thread_msgs = (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.created_at)
        .all()
    )

    llm_messages = [{"role": "system", "content": system_prompt}]
    llm_messages += [{"role": m.role, "content": m.content} for m in thread_msgs]

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=get_model(),
            messages=llm_messages,
        )
        ai_content = response.choices[0].message.content
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

    db.add(Message(thread_id=thread_id, role="assistant", content=ai_content))
    db.commit()

    return {"role": "assistant", "content": ai_content}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
