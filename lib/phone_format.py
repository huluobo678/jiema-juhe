"""Phone number formatting utilities."""
import re


def format_phone(phone: str, channel_name: str = "") -> str:
    """Format phone number for display.
    
    HeroSMS returns international numbers like 447599685269.
    This formats them as +44 (759) 968 52 69.
    Domestic numbers (haozhuma) are returned as-is.
    """
    if not phone or not isinstance(phone, str):
        return phone or ""
    
    phone = phone.strip()
    
    # HeroSMS / SMS-Activate numbers start with country code, no +
    # Known formats:
    #   UK: 44XXXXXXXXX -> +44 (XXXX) XXX XXX
    #   Russia/Kazakhstan: 7XXXXXXXXX -> +7 (XXX) XXX XX XX
    #   Others: just add + prefix
    
    # Strip non-digits for analysis
    digits = re.sub(r'\D', '', phone)
    
    if not digits:
        return phone
    
    # ---------- HeroSMS international numbers ----------
    if digits.startswith('44') and len(digits) >= 11:
        # UK: 44 + area + local
        # 447599685269 -> +44 (759) 968 52 69
        # 447XXXXXXXXX (11-12 digits)
        local = digits[2:]  # strip 44
        if len(local) == 10:
            # +44 (XXXX) XXX XXX
            return f"+44 ({local[:4]}) {local[4:7]} {local[7:]}"
        elif len(local) == 9:
            # +44 (XXX) XXX XXX or +44 (X)XXXX XXX XXX
            # Most UK mobiles: 7XXX XXX XXX (10 digits total)
            return f"+44 ({local[:3]}) {local[3:6]} {local[6:8]} {local[8:]}"
        elif len(local) >= 7:
            return f"+44 ({local[:3]}) {local[3:6]} {local[6:8]} {local[8:]}"
        return f"+{digits}"
    
    if digits.startswith('7') and len(digits) >= 10:
        # Russia/Kazakhstan: 7XXXXXXXXXX
        local = digits[1:]  # strip 7
        if len(local) == 10:
            return f"+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:]}"
        return f"+7 {digits[1:]}"
    
    if digits.startswith('1') and len(digits) == 11:
        # USA/Canada: 1XXXXXXXXXX -> +1 (XXX) XXX-XXXX
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    
    if digits.startswith('86') and len(digits) >= 11:
        # China: 86XXXXXXXXXXX -> +86 XXXXXXXXXX
        return f"+86 {digits[2:]}"
    
    # Generic: just add + and group by 3-4 digits
    if len(digits) >= 10:
        # Find country code (first 1-3 digits)
        # Best-effort grouping
        if len(digits) <= 7:
            return f"+{digits}"
        groups = []
        i = 1 if digits[0] == '7' else (2 if digits[:2] in ('44','86','81','82','91') else 1)
        if i == 1 and len(digits) > 11:
            i = 2
        elif i == 1:
            i = 1
        cc = digits[:i]
        rest = digits[i:]
        while rest:
            chunk_size = min(3, len(rest)) if not groups else (4 if len(rest) > 3 else len(rest))
            groups.append(rest[:chunk_size])
            rest = rest[chunk_size:]
        return f"+{cc} " + " ".join(groups)
    
    # Short numbers: just add +
    return f"+{digits}"

