"""Utility for detecting country names in text (Hebrew and English)."""

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class CountryInfo:
    """Information about a detected country."""
    name_hebrew: str
    name_english: str
    emoji: str


# Comprehensive mapping of countries with Hebrew names, English names, and flag emojis
COUNTRIES: dict[str, CountryInfo] = {
    # Asia
    "תאילנד": CountryInfo("תאילנד", "Thailand", "🇹🇭"),
    "thailand": CountryInfo("תאילנד", "Thailand", "🇹🇭"),
    "יפן": CountryInfo("יפן", "Japan", "🇯🇵"),
    "japan": CountryInfo("יפן", "Japan", "🇯🇵"),
    "סין": CountryInfo("סין", "China", "🇨🇳"),
    "china": CountryInfo("סין", "China", "🇨🇳"),
    "הודו": CountryInfo("הודו", "India", "🇮🇳"),
    "india": CountryInfo("הודו", "India", "🇮🇳"),
    "וייטנאם": CountryInfo("וייטנאם", "Vietnam", "🇻🇳"),
    "vietnam": CountryInfo("וייטנאם", "Vietnam", "🇻🇳"),
    "קמבודיה": CountryInfo("קמבודיה", "Cambodia", "🇰🇭"),
    "cambodia": CountryInfo("קמבודיה", "Cambodia", "🇰🇭"),
    "לאוס": CountryInfo("לאוס", "Laos", "🇱🇦"),
    "laos": CountryInfo("לאוס", "Laos", "🇱🇦"),
    "מיאנמר": CountryInfo("מיאנמר", "Myanmar", "🇲🇲"),
    "myanmar": CountryInfo("מיאנמר", "Myanmar", "🇲🇲"),
    "בורמה": CountryInfo("מיאנמר", "Myanmar", "🇲🇲"),
    "burma": CountryInfo("מיאנמר", "Myanmar", "🇲🇲"),
    "אינדונזיה": CountryInfo("אינדונזיה", "Indonesia", "🇮🇩"),
    "indonesia": CountryInfo("אינדונזיה", "Indonesia", "🇮🇩"),
    "באלי": CountryInfo("אינדונזיה", "Indonesia", "🇮🇩"),  # Bali is in Indonesia
    "bali": CountryInfo("אינדונזיה", "Indonesia", "🇮🇩"),
    "מלזיה": CountryInfo("מלזיה", "Malaysia", "🇲🇾"),
    "malaysia": CountryInfo("מלזיה", "Malaysia", "🇲🇾"),
    "סינגפור": CountryInfo("סינגפור", "Singapore", "🇸🇬"),
    "singapore": CountryInfo("סינגפור", "Singapore", "🇸🇬"),
    "פיליפינים": CountryInfo("פיליפינים", "Philippines", "🇵🇭"),
    "philippines": CountryInfo("פיליפינים", "Philippines", "🇵🇭"),
    "דרום קוריאה": CountryInfo("דרום קוריאה", "South Korea", "🇰🇷"),
    "קוריאה": CountryInfo("דרום קוריאה", "South Korea", "🇰🇷"),
    "korea": CountryInfo("דרום קוריאה", "South Korea", "🇰🇷"),
    "south korea": CountryInfo("דרום קוריאה", "South Korea", "🇰🇷"),
    "טייוואן": CountryInfo("טייוואן", "Taiwan", "🇹🇼"),
    "taiwan": CountryInfo("טייוואן", "Taiwan", "🇹🇼"),
    "הונג קונג": CountryInfo("הונג קונג", "Hong Kong", "🇭🇰"),
    "hong kong": CountryInfo("הונג קונג", "Hong Kong", "🇭🇰"),
    "נפאל": CountryInfo("נפאל", "Nepal", "🇳🇵"),
    "nepal": CountryInfo("נפאל", "Nepal", "🇳🇵"),
    "סרי לנקה": CountryInfo("סרי לנקה", "Sri Lanka", "🇱🇰"),
    "sri lanka": CountryInfo("סרי לנקה", "Sri Lanka", "🇱🇰"),
    "מונגוליה": CountryInfo("מונגוליה", "Mongolia", "🇲🇳"),
    "mongolia": CountryInfo("מונגוליה", "Mongolia", "🇲🇳"),
    
    # Europe
    "ספרד": CountryInfo("ספרד", "Spain", "🇪🇸"),
    "spain": CountryInfo("ספרד", "Spain", "🇪🇸"),
    "איטליה": CountryInfo("איטליה", "Italy", "🇮🇹"),
    "italy": CountryInfo("איטליה", "Italy", "🇮🇹"),
    "צרפת": CountryInfo("צרפת", "France", "🇫🇷"),
    "france": CountryInfo("צרפת", "France", "🇫🇷"),
    "פריז": CountryInfo("צרפת", "France", "🇫🇷"),  # Paris
    "paris": CountryInfo("צרפת", "France", "🇫🇷"),
    "גרמניה": CountryInfo("גרמניה", "Germany", "🇩🇪"),
    "germany": CountryInfo("גרמניה", "Germany", "🇩🇪"),
    "ברלין": CountryInfo("גרמניה", "Germany", "🇩🇪"),
    "berlin": CountryInfo("גרמניה", "Germany", "🇩🇪"),
    "אנגליה": CountryInfo("אנגליה", "England", "🇬🇧"),
    "england": CountryInfo("אנגליה", "England", "🇬🇧"),
    "בריטניה": CountryInfo("בריטניה", "UK", "🇬🇧"),
    "uk": CountryInfo("בריטניה", "UK", "🇬🇧"),
    "לונדון": CountryInfo("בריטניה", "UK", "🇬🇧"),
    "london": CountryInfo("בריטניה", "UK", "🇬🇧"),
    "הולנד": CountryInfo("הולנד", "Netherlands", "🇳🇱"),
    "netherlands": CountryInfo("הולנד", "Netherlands", "🇳🇱"),
    "אמסטרדם": CountryInfo("הולנד", "Netherlands", "🇳🇱"),
    "amsterdam": CountryInfo("הולנד", "Netherlands", "🇳🇱"),
    "בלגיה": CountryInfo("בלגיה", "Belgium", "🇧🇪"),
    "belgium": CountryInfo("בלגיה", "Belgium", "🇧🇪"),
    "פורטוגל": CountryInfo("פורטוגל", "Portugal", "🇵🇹"),
    "portugal": CountryInfo("פורטוגל", "Portugal", "🇵🇹"),
    "יוון": CountryInfo("יוון", "Greece", "🇬🇷"),
    "greece": CountryInfo("יוון", "Greece", "🇬🇷"),
    "קרואטיה": CountryInfo("קרואטיה", "Croatia", "🇭🇷"),
    "croatia": CountryInfo("קרואטיה", "Croatia", "🇭🇷"),
    "צ'כיה": CountryInfo("צ'כיה", "Czech Republic", "🇨🇿"),
    "czech": CountryInfo("צ'כיה", "Czech Republic", "🇨🇿"),
    "פראג": CountryInfo("צ'כיה", "Czech Republic", "🇨🇿"),
    "prague": CountryInfo("צ'כיה", "Czech Republic", "🇨🇿"),
    "אוסטריה": CountryInfo("אוסטריה", "Austria", "🇦🇹"),
    "austria": CountryInfo("אוסטריה", "Austria", "🇦🇹"),
    "וינה": CountryInfo("אוסטריה", "Austria", "🇦🇹"),
    "vienna": CountryInfo("אוסטריה", "Austria", "🇦🇹"),
    "שוויץ": CountryInfo("שוויץ", "Switzerland", "🇨🇭"),
    "switzerland": CountryInfo("שוויץ", "Switzerland", "🇨🇭"),
    "פולין": CountryInfo("פולין", "Poland", "🇵🇱"),
    "poland": CountryInfo("פולין", "Poland", "🇵🇱"),
    "הונגריה": CountryInfo("הונגריה", "Hungary", "🇭🇺"),
    "hungary": CountryInfo("הונגריה", "Hungary", "🇭🇺"),
    "בודפשט": CountryInfo("הונגריה", "Hungary", "🇭🇺"),
    "budapest": CountryInfo("הונגריה", "Hungary", "🇭🇺"),
    "רומניה": CountryInfo("רומניה", "Romania", "🇷🇴"),
    "romania": CountryInfo("רומניה", "Romania", "🇷🇴"),
    "בולגריה": CountryInfo("בולגריה", "Bulgaria", "🇧🇬"),
    "bulgaria": CountryInfo("בולגריה", "Bulgaria", "🇧🇬"),
    "סלובניה": CountryInfo("סלובניה", "Slovenia", "🇸🇮"),
    "slovenia": CountryInfo("סלובניה", "Slovenia", "🇸🇮"),
    "איסלנד": CountryInfo("איסלנד", "Iceland", "🇮🇸"),
    "iceland": CountryInfo("איסלנד", "Iceland", "🇮🇸"),
    "נורווגיה": CountryInfo("נורווגיה", "Norway", "🇳🇴"),
    "norway": CountryInfo("נורווגיה", "Norway", "🇳🇴"),
    "שוודיה": CountryInfo("שוודיה", "Sweden", "🇸🇪"),
    "sweden": CountryInfo("שוודיה", "Sweden", "🇸🇪"),
    "פינלנד": CountryInfo("פינלנד", "Finland", "🇫🇮"),
    "finland": CountryInfo("פינלנד", "Finland", "🇫🇮"),
    "דנמרק": CountryInfo("דנמרק", "Denmark", "🇩🇰"),
    "denmark": CountryInfo("דנמרק", "Denmark", "🇩🇰"),
    "אירלנד": CountryInfo("אירלנד", "Ireland", "🇮🇪"),
    "ireland": CountryInfo("אירלנד", "Ireland", "🇮🇪"),
    "סקוטלנד": CountryInfo("סקוטלנד", "Scotland", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    "scotland": CountryInfo("סקוטלנד", "Scotland", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"),
    "טורקיה": CountryInfo("טורקיה", "Turkey", "🇹🇷"),
    "turkey": CountryInfo("טורקיה", "Turkey", "🇹🇷"),
    "איסטנבול": CountryInfo("טורקיה", "Turkey", "🇹🇷"),
    "istanbul": CountryInfo("טורקיה", "Turkey", "🇹🇷"),
    "קפריסין": CountryInfo("קפריסין", "Cyprus", "🇨🇾"),
    "cyprus": CountryInfo("קפריסין", "Cyprus", "🇨🇾"),
    "מלטה": CountryInfo("מלטה", "Malta", "🇲🇹"),
    "malta": CountryInfo("מלטה", "Malta", "🇲🇹"),
    "אלבניה": CountryInfo("אלבניה", "Albania", "🇦🇱"),
    "albania": CountryInfo("אלבניה", "Albania", "🇦🇱"),
    "מונטנגרו": CountryInfo("מונטנגרו", "Montenegro", "🇲🇪"),
    "montenegro": CountryInfo("מונטנגרו", "Montenegro", "🇲🇪"),
    
    # Americas
    "ארצות הברית": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "ארה\"ב": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "אמריקה": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "usa": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "america": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "ניו יורק": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "new york": CountryInfo("ארצות הברית", "USA", "🇺🇸"),
    "קנדה": CountryInfo("קנדה", "Canada", "🇨🇦"),
    "canada": CountryInfo("קנדה", "Canada", "🇨🇦"),
    "מקסיקו": CountryInfo("מקסיקו", "Mexico", "🇲🇽"),
    "mexico": CountryInfo("מקסיקו", "Mexico", "🇲🇽"),
    "ברזיל": CountryInfo("ברזיל", "Brazil", "🇧🇷"),
    "brazil": CountryInfo("ברזיל", "Brazil", "🇧🇷"),
    "ארגנטינה": CountryInfo("ארגנטינה", "Argentina", "🇦🇷"),
    "argentina": CountryInfo("ארגנטינה", "Argentina", "🇦🇷"),
    "צ'ילה": CountryInfo("צ'ילה", "Chile", "🇨🇱"),
    "chile": CountryInfo("צ'ילה", "Chile", "🇨🇱"),
    "פרו": CountryInfo("פרו", "Peru", "🇵🇪"),
    "peru": CountryInfo("פרו", "Peru", "🇵🇪"),
    "קולומביה": CountryInfo("קולומביה", "Colombia", "🇨🇴"),
    "colombia": CountryInfo("קולומביה", "Colombia", "🇨🇴"),
    "קוסטה ריקה": CountryInfo("קוסטה ריקה", "Costa Rica", "🇨🇷"),
    "costa rica": CountryInfo("קוסטה ריקה", "Costa Rica", "🇨🇷"),
    "פנמה": CountryInfo("פנמה", "Panama", "🇵🇦"),
    "panama": CountryInfo("פנמה", "Panama", "🇵🇦"),
    "קובה": CountryInfo("קובה", "Cuba", "🇨🇺"),
    "cuba": CountryInfo("קובה", "Cuba", "🇨🇺"),
    "הרפובליקה הדומיניקנית": CountryInfo("הרפובליקה הדומיניקנית", "Dominican Republic", "🇩🇴"),
    "דומיניקנה": CountryInfo("הרפובליקה הדומיניקנית", "Dominican Republic", "🇩🇴"),
    "dominican": CountryInfo("הרפובליקה הדומיניקנית", "Dominican Republic", "🇩🇴"),
    "ג'מייקה": CountryInfo("ג'מייקה", "Jamaica", "🇯🇲"),
    "jamaica": CountryInfo("ג'מייקה", "Jamaica", "🇯🇲"),
    "אקוודור": CountryInfo("אקוודור", "Ecuador", "🇪🇨"),
    "ecuador": CountryInfo("אקוודור", "Ecuador", "🇪🇨"),
    "בוליביה": CountryInfo("בוליביה", "Bolivia", "🇧🇴"),
    "bolivia": CountryInfo("בוליביה", "Bolivia", "🇧🇴"),
    
    # Africa
    "מרוקו": CountryInfo("מרוקו", "Morocco", "🇲🇦"),
    "morocco": CountryInfo("מרוקו", "Morocco", "🇲🇦"),
    "מצרים": CountryInfo("מצרים", "Egypt", "🇪🇬"),
    "egypt": CountryInfo("מצרים", "Egypt", "🇪🇬"),
    "דרום אפריקה": CountryInfo("דרום אפריקה", "South Africa", "🇿🇦"),
    "south africa": CountryInfo("דרום אפריקה", "South Africa", "🇿🇦"),
    "קניה": CountryInfo("קניה", "Kenya", "🇰🇪"),
    "kenya": CountryInfo("קניה", "Kenya", "🇰🇪"),
    "טנזניה": CountryInfo("טנזניה", "Tanzania", "🇹🇿"),
    "tanzania": CountryInfo("טנזניה", "Tanzania", "🇹🇿"),
    "זנזיבר": CountryInfo("טנזניה", "Tanzania", "🇹🇿"),
    "zanzibar": CountryInfo("טנזניה", "Tanzania", "🇹🇿"),
    "אתיופיה": CountryInfo("אתיופיה", "Ethiopia", "🇪🇹"),
    "ethiopia": CountryInfo("אתיופיה", "Ethiopia", "🇪🇹"),
    "רואנדה": CountryInfo("רואנדה", "Rwanda", "🇷🇼"),
    "rwanda": CountryInfo("רואנדה", "Rwanda", "🇷🇼"),
    "אוגנדה": CountryInfo("אוגנדה", "Uganda", "🇺🇬"),
    "uganda": CountryInfo("אוגנדה", "Uganda", "🇺🇬"),
    "נמיביה": CountryInfo("נמיביה", "Namibia", "🇳🇦"),
    "namibia": CountryInfo("נמיביה", "Namibia", "🇳🇦"),
    "בוצוואנה": CountryInfo("בוצוואנה", "Botswana", "🇧🇼"),
    "botswana": CountryInfo("בוצוואנה", "Botswana", "🇧🇼"),
    "זימבבואה": CountryInfo("זימבבואה", "Zimbabwe", "🇿🇼"),
    "zimbabwe": CountryInfo("זימבבואה", "Zimbabwe", "🇿🇼"),
    "סיישל": CountryInfo("סיישל", "Seychelles", "🇸🇨"),
    "seychelles": CountryInfo("סיישל", "Seychelles", "🇸🇨"),
    "מאוריציוס": CountryInfo("מאוריציוס", "Mauritius", "🇲🇺"),
    "mauritius": CountryInfo("מאוריציוס", "Mauritius", "🇲🇺"),
    "מדגסקר": CountryInfo("מדגסקר", "Madagascar", "🇲🇬"),
    "madagascar": CountryInfo("מדגסקר", "Madagascar", "🇲🇬"),
    "תוניסיה": CountryInfo("תוניסיה", "Tunisia", "🇹🇳"),
    "tunisia": CountryInfo("תוניסיה", "Tunisia", "🇹🇳"),
    
    # Middle East
    "איחוד האמירויות": CountryInfo("איחוד האמירויות", "UAE", "🇦🇪"),
    "אמירויות": CountryInfo("איחוד האמירויות", "UAE", "🇦🇪"),
    "דובאי": CountryInfo("איחוד האמירויות", "UAE", "🇦🇪"),
    "dubai": CountryInfo("איחוד האמירויות", "UAE", "🇦🇪"),
    "uae": CountryInfo("איחוד האמירויות", "UAE", "🇦🇪"),
    "ירדן": CountryInfo("ירדן", "Jordan", "🇯🇴"),
    "jordan": CountryInfo("ירדן", "Jordan", "🇯🇴"),
    "עומאן": CountryInfo("עומאן", "Oman", "🇴🇲"),
    "oman": CountryInfo("עומאן", "Oman", "🇴🇲"),
    "סעודיה": CountryInfo("סעודיה", "Saudi Arabia", "🇸🇦"),
    "saudi": CountryInfo("סעודיה", "Saudi Arabia", "🇸🇦"),
    "קטאר": CountryInfo("קטאר", "Qatar", "🇶🇦"),
    "qatar": CountryInfo("קטאר", "Qatar", "🇶🇦"),
    "בחריין": CountryInfo("בחריין", "Bahrain", "🇧🇭"),
    "bahrain": CountryInfo("בחריין", "Bahrain", "🇧🇭"),
    
    # Oceania
    "אוסטרליה": CountryInfo("אוסטרליה", "Australia", "🇦🇺"),
    "australia": CountryInfo("אוסטרליה", "Australia", "🇦🇺"),
    "ניו זילנד": CountryInfo("ניו זילנד", "New Zealand", "🇳🇿"),
    "new zealand": CountryInfo("ניו זילנד", "New Zealand", "🇳🇿"),
    "פיג'י": CountryInfo("פיג'י", "Fiji", "🇫🇯"),
    "fiji": CountryInfo("פיג'י", "Fiji", "🇫🇯"),
    "טהיטי": CountryInfo("טהיטי", "Tahiti", "🇵🇫"),
    "tahiti": CountryInfo("טהיטי", "Tahiti", "🇵🇫"),
    "מלדיביים": CountryInfo("מלדיביים", "Maldives", "🇲🇻"),
    "מלדיבים": CountryInfo("מלדיביים", "Maldives", "🇲🇻"),
    "maldives": CountryInfo("מלדיביים", "Maldives", "🇲🇻"),
    "האיים המלדיביים": CountryInfo("מלדיביים", "Maldives", "🇲🇻"),
    "הוואי": CountryInfo("הוואי", "Hawaii", "🌺"),
    "hawaii": CountryInfo("הוואי", "Hawaii", "🌺"),
    
    # Russia & Central Asia
    "רוסיה": CountryInfo("רוסיה", "Russia", "🇷🇺"),
    "russia": CountryInfo("רוסיה", "Russia", "🇷🇺"),
    "אוזבקיסטן": CountryInfo("אוזבקיסטן", "Uzbekistan", "🇺🇿"),
    "uzbekistan": CountryInfo("אוזבקיסטן", "Uzbekistan", "🇺🇿"),
    "גיאורגיה": CountryInfo("גיאורגיה", "Georgia", "🇬🇪"),
    "georgia": CountryInfo("גיאורגיה", "Georgia", "🇬🇪"),
    "ארמניה": CountryInfo("ארמניה", "Armenia", "🇦🇲"),
    "armenia": CountryInfo("ארמניה", "Armenia", "🇦🇲"),
    "אזרבייג'ן": CountryInfo("אזרבייג'ן", "Azerbaijan", "🇦🇿"),
    "azerbaijan": CountryInfo("אזרבייג'ן", "Azerbaijan", "🇦🇿"),
    "קזחסטן": CountryInfo("קזחסטן", "Kazakhstan", "🇰🇿"),
    "kazakhstan": CountryInfo("קזחסטן", "Kazakhstan", "🇰🇿"),
}


def detect_country(text: str) -> Optional[CountryInfo]:
    """
    Detect a country name in the given text.
    
    Searches for both Hebrew and English country names (case-insensitive).
    
    Args:
        text: The text to search (e.g., group name or message)
        
    Returns:
        CountryInfo if a country is found, None otherwise
    """
    if not text:
        return None
    
    # Normalize text for matching
    text_lower = text.lower()
    
    # Try to find a country match
    # Sort by length (descending) to match longer names first (e.g., "south korea" before "korea")
    sorted_countries = sorted(COUNTRIES.keys(), key=len, reverse=True)
    
    for country_key in sorted_countries:
        # Check if the country name appears in the text
        # Use word boundary-like matching for better accuracy
        pattern = re.compile(
            rf'(?:^|[\s\-_,./])({re.escape(country_key)})(?:[\s\-_,./]|$)',
            re.IGNORECASE
        )
        if pattern.search(text_lower) or country_key in text_lower:
            return COUNTRIES[country_key]
    
    return None


def detect_country_from_message(text: str) -> Optional[CountryInfo]:
    """
    Detect a country from a user message like "אנחנו טסים לתאילנד".
    
    This is specifically for parsing user messages that mention a destination.
    
    Args:
        text: The user message
        
    Returns:
        CountryInfo if a country is found, None otherwise
    """
    return detect_country(text)


def get_all_country_names() -> list[str]:
    """
    Get a list of all supported country names (Hebrew and English).
    
    Returns:
        List of country name strings
    """
    return list(COUNTRIES.keys())

