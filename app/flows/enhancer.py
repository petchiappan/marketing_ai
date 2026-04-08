"""LLM Enhancement utility to manually refine enriched lead payloads."""

import json
import logging
from typing import Any

from litellm import acompletion

from app.config.settings import settings

logger = logging.getLogger(__name__)

async def run_enhancement(company_name: str, original_payload: str, instructions: str | None) -> tuple[str, dict]:
    """
    Passes the existing enriched payload to the LLM along with user instructions 
    for modification and returning the updated payload.
    
    Returns:
        tuple: (enhanced_payload_json_string, token_usage_dict)
    """
    system_prompt = (
        "You are a strict data-restructuring assistant. Your job is to modify the provided "
        "JSON payload according to the user's instructions. \n\n"
        "Rules:\n"
        "1. Start and end your response ONLY with valid JSON. Do not include markdown codeblocks or other text.\n"
        "2. Keep the schema the same, unless the user explicitly requests adding/removing a field.\n"
        "3. Preserve all data that the user does not specify to remove.\n"
    )

    user_prompt = f"Company: {company_name}\n\n"
    if instructions:
        user_prompt += f"Instructions: {instructions}\n\n"
    else:
        user_prompt += "Instructions: Refine and perfectly format the JSON. Ensure it is valid and clean.\n\n"
        
    user_prompt += f"Original Payload:\n{original_payload}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await acompletion(
            model=settings.llm_identifier,
            messages=messages,
            api_key=settings.openai_api_key if "openai" in settings.llm_provider.lower() else None,
            temperature=0.0,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean markdown code blocks if the LLM ignored the instruction
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        content = content.strip()
        
        # Verify it's valid JSON
        json.loads(content)
        
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            
        return content, usage
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse enhanced output as JSON: {e}")
        raise ValueError("The LLM returned invalid JSON.")
    except Exception as e:
        logger.error(f"Enhancement failed: {e}")
        raise
