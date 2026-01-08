"""Extract trip information from group names using OpenAI."""

import logging
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from tenacity import (
    retry,
    wait_random_exponential,
    stop_after_attempt,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


class TripInfo(BaseModel):
    """Structured trip information extracted from group name."""

    destination: Optional[str] = Field(
        default=None,
        description="The destination/place name in Hebrew (normalized, e.g., 'פראג' not 'פראגגגגג')",
    )
    destination_emoji: Optional[str] = Field(
        default=None, description="Flag or relevant emoji for the destination"
    )
    start_date: Optional[date] = Field(
        default=None, description="Trip start date if mentioned"
    )
    end_date: Optional[date] = Field(
        default=None, description="Trip end date if mentioned"
    )
    context: Optional[str] = Field(
        default=None,
        description="Trip context/purpose in Hebrew (e.g., 'מסיבת רווקים', 'טיול משפחתי', 'חופשה רומנטית')",
    )


SYSTEM_PROMPT = """אתה עוזר שמנתח שמות של קבוצות וואטסאפ של טיולים ומחלץ מהם מידע.

קבל שם קבוצה וחלץ:
1. **destination** - שם היעד בעברית (תקן שגיאות כתיב ואותיות כפולות, למשל "פראגגגגג" → "פראג")
2. **destination_emoji** - אימוג'י דגל המדינה או אימוג'י רלוונטי ליעד
3. **start_date** / **end_date** - תאריכי הטיול אם מוזכרים (פורמט YYYY-MM-DD). אם רק חודש מוזכר בלי שנה, השתמש בשנה הקרובה
4. **context** - הקשר/מטרת הטיול בעברית (למשל: "מסיבת רווקים", "טיול משפחתי", "חופשה זוגית", "טיול חברים")

דוגמאות:
- "תאילנד 15.3-20.3 מסיבת רווקים" → destination: "תאילנד", start_date: "2026-03-15", end_date: "2026-03-20", context: "מסיבת רווקים"
- "פראגגגגגגג במרץ" → destination: "פראג", context: null (רק חודש בלי תאריכים מדויקים)
- "יוון עם כל המשפחה" → destination: "יוון", context: "טיול משפחתי"
- "ברצלונה רווקות 🎉" → destination: "ברצלונה", context: "מסיבת רווקות"
- "טיול לפראג" → destination: "פראג"

אם לא ניתן לחלץ מידע מסוים, החזר null עבורו."""


@retry(
    wait=wait_random_exponential(min=1, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.DEBUG),
    reraise=True,
)
async def extract_trip_info(
    group_name: str, model_name: str = "openai:gpt-4o-mini"
) -> TripInfo:
    """
    Extract trip information from a WhatsApp group name using OpenAI.

    Args:
        group_name: The WhatsApp group name
        model_name: The model to use for extraction

    Returns:
        TripInfo with extracted destination, dates, and context
    """
    if not group_name:
        return TripInfo()

    agent = Agent(
        model=model_name,
        system_prompt=SYSTEM_PROMPT,
        output_type=TripInfo,
    )

    result = await agent.run(f"שם הקבוצה: {group_name}")

    logger.info(f"Extracted trip info from '{group_name}': {result.output}")

    return result.output

