from anthropic import Anthropic

anthropic = Anthropic()

def count_messages(messages: list) -> int:
    return len(messages)


async def summarize_messages(messages: list) -> str:
    """Summarize old messages using Claude."""
    
    # Format messages for summarization
    conversation_text = "\n".join(
        f"{msg['role']}: {msg['content']}" 
        for msg in messages 
        if isinstance(msg['content'], str)
    )
    
    response = anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"""Summarize this conversation concisely. Preserve:
- Key facts and information found
- User's goals and preferences
- Important decisions made
- Tool results and findings

Conversation:
{conversation_text}"""
        }]
    )
    
    return response.content[0].text


def build_context(summary: str, recent_messages: list, new_query: str) -> list:
    """Build messages list for LLM with summary + recent + new query."""
    
    messages = []
    
    # Add summary as system context if exists
    if summary:
        messages.append({
            "role": "user",
            "content": f"[Previous conversation summary: {summary}]"
        })
        messages.append({
            "role": "assistant", 
            "content": "I understand the context from our previous conversation."
        })
    
    # Add recent messages
    messages.extend(recent_messages)
    
    # Add new query
    messages.append({"role": "user", "content": new_query})
    
    return messages