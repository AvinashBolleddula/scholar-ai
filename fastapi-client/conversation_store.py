from google.cloud import firestore
from datetime import datetime
import uuid

db = firestore.Client()
COLLECTION = "conversations"

def create_session(api_key: str) -> str:
    session_id = str(uuid.uuid4())
    db.collection(COLLECTION).document(session_id).set({
        "api_key": api_key,
        "messages": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "summary": "",
        "summarized_until": 0
    })
    return session_id

def get_session(session_id: str) -> dict:
    doc = db.collection(COLLECTION).document(session_id).get()
    if doc.exists:
        data = doc.to_dict()
        return {
            "messages": data.get("messages", []),
            "summary": data.get("summary", ""),
            "summarized_until": data.get("summarized_until", 0)
        }
    return {"messages": [], "summary": "", "summarized_until": 0}

def list_sessions(api_key: str) -> list:
    docs = db.collection(COLLECTION).where("api_key", "==", api_key).stream()
    sessions = []
    for doc in docs:
        data = doc.to_dict()
        sessions.append({
            "session_id": doc.id,
            "created_at": data.get("created_at"),
            "message_count": len(data.get("messages", []))
        })
    return sessions

def get_messages(session_id: str) -> list:
    doc = db.collection(COLLECTION).document(session_id).get()
    if doc.exists:
        return doc.to_dict().get("messages", [])
    return []


def add_messages(session_id: str, messages: list):
    doc_ref = db.collection(COLLECTION).document(session_id)
    doc_ref.update({
        "messages": firestore.ArrayUnion(messages),
        "updated_at": datetime.utcnow()
    })

def update_summary(session_id: str, summary: str, summarized_until: int):
    db.collection(COLLECTION).document(session_id).update({
        "summary": summary,
        "summarized_until": summarized_until,
        "updated_at": datetime.utcnow()
    })