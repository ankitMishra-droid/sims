"""Tenant- and user-isolated conversation & message persistence with bounded history windows."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ...core.ai_exceptions import AIInvalidRequestError
from ...models.ai_rag import AIConversation, AIMessage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ConversationService:
    """Enforces user + business ownership over all chat sessions and history."""

    @staticmethod
    def create_conversation(
        db: Session,
        *,
        business_id: int,
        user_id: int,
        title: Optional[str] = None,
        preferred_language: str = "auto",
        page_context: Optional[Dict[str, Any]] = None,
    ) -> AIConversation:
        clean_title = (title or "New Conversation").strip()[:190] or "New Conversation"
        clean_lang = (preferred_language or "auto").strip().lower()
        if clean_lang not in ("auto", "en", "hi", "mixed"):
            clean_lang = "auto"

        conv = AIConversation(
            business_id=business_id,
            user_id=user_id,
            title=clean_title,
            preferred_language=clean_lang,
            last_page_context_json=json.dumps(page_context) if page_context else None,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv

    @staticmethod
    def require_owned_conversation(
        db: Session,
        *,
        conv_id: int,
        business_id: int,
        user_id: int,
    ) -> AIConversation:
        conv = (
            db.query(AIConversation)
            .filter(
                AIConversation.id == conv_id,
                AIConversation.business_id == business_id,
                AIConversation.user_id == user_id,
                AIConversation.is_archived.is_(False),
            )
            .first()
        )
        if not conv:
            raise AIInvalidRequestError(
                "Conversation not found for this user and workspace.",
                provider="assistant",
            )
        return conv

    @staticmethod
    def list_conversations(
        db: Session,
        *,
        business_id: int,
        user_id: int,
        limit: int = 25,
        offset: int = 0,
    ) -> List[AIConversation]:
        return (
            db.query(AIConversation)
            .filter(
                AIConversation.business_id == business_id,
                AIConversation.user_id == user_id,
                AIConversation.is_archived.is_(False),
            )
            .order_by(AIConversation.updated_at.desc(), AIConversation.id.desc())
            .offset(max(0, offset))
            .limit(min(100, max(1, limit)))
            .all()
        )

    @staticmethod
    def get_conversation_with_messages(
        db: Session,
        *,
        conv_id: int,
        business_id: int,
        user_id: int,
        message_limit: int = 100,
    ) -> Tuple[AIConversation, List[AIMessage]]:
        conv = ConversationService.require_owned_conversation(
            db, conv_id=conv_id, business_id=business_id, user_id=user_id
        )
        messages = (
            db.query(AIMessage)
            .filter(
                AIMessage.conversation_id == conv.id,
                AIMessage.business_id == business_id,
                AIMessage.user_id == user_id,
            )
            .order_by(AIMessage.id.asc())
            .limit(min(200, max(1, message_limit)))
            .all()
        )
        return conv, messages

    @staticmethod
    def get_bounded_recent_turns(
        db: Session,
        *,
        conv: AIConversation,
        max_turns: int = 8,
    ) -> Tuple[Optional[str], List[tuple[str, str]], Optional[str]]:
        """Return compact rolling summary, recent `(role, content)` window, and last user question."""
        import re

        recent_rows = (
            db.query(AIMessage)
            .filter(
                AIMessage.conversation_id == conv.id,
                AIMessage.business_id == conv.business_id,
                AIMessage.user_id == conv.user_id,
                AIMessage.status == "COMPLETED",
            )
            .order_by(AIMessage.id.desc())
            .limit(max(2, max_turns))
            .all()
        )
        ordered = list(reversed(recent_rows))
        turns: List[tuple[str, str]] = []
        for m in ordered:
            txt = m.content
            if m.role == "assistant":
                # Keep conversational history free of legacy [1]/[2] citation artifacts
                txt = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", txt).strip()
            turns.append((m.role, txt))
        last_user = next((m.content for m in reversed(ordered) if m.role == "user"), None)
        return conv.context_summary, turns, last_user

    @staticmethod
    def append_turn(
        db: Session,
        *,
        conv: AIConversation,
        role: str,
        content: str,
        language: str = "en",
        sources: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        pending_action: Optional[Dict[str, Any]] = None,
        model_name: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        candidates_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        latency_ms: Optional[float] = None,
        request_id: Optional[str] = None,
        status: str = "COMPLETED",
        error_code: Optional[str] = None,
    ) -> AIMessage:
        msg = AIMessage(
            conversation_id=conv.id,
            business_id=conv.business_id,
            user_id=conv.user_id,
            role=role,
            content=content,
            language=language,
            sources_json=json.dumps(sources or [], ensure_ascii=False),
            tool_calls_json=json.dumps(tool_calls or [], ensure_ascii=False),
            pending_action_json=json.dumps(pending_action, ensure_ascii=False)
            if pending_action is not None
            else None,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            candidates_tokens=candidates_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            request_id=request_id,
            status=status,
            error_code=error_code,
        )
        db.add(msg)

        if conv.title == "New Conversation" and role == "user":
            snippet = " ".join(content.strip().split())[:72]
            if snippet:
                conv.title = snippet

        # Maintain compact rolling context summary when message count exceeds window
        total_msgs = (
            db.query(AIMessage)
            .filter(AIMessage.conversation_id == conv.id)
            .count()
        )
        if total_msgs > 8 and role == "user":
            prev_summary = (conv.context_summary or "").strip()
            new_topic = " ".join(content.strip().split())[:100]
            conv.context_summary = (
                f"{prev_summary}; {new_topic}"[-600:] if prev_summary else new_topic
            )

        conv.updated_at = _utcnow()
        db.commit()
        db.refresh(msg)
        return msg

    @staticmethod
    def delete_conversation(
        db: Session,
        *,
        conv_id: int,
        business_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        conv = ConversationService.require_owned_conversation(
            db, conv_id=conv_id, business_id=business_id, user_id=user_id
        )
        db.delete(conv)
        db.commit()
        return {"conversation_id": conv_id, "deleted": True}
