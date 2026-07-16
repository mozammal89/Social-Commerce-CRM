"""
WhatsApp Cloud API error code → user-friendly message mapping.

Meta's Cloud API returns errors as ``{"error": {"code": int, "message": str,
"error_subcode": int, ...}}``. The raw messages are developer-oriented and
frequently reference internal details end users should never see.

This module translates known Meta error codes/subcodes (and common
message fragments) into plain-language guidance that a CRM agent or store
owner can act on. Unknown codes fall back to a sanitized generic message.

Key references:
* https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
* https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages
"""

from __future__ import annotations


def translate_error(
    *,
    code: str | int | None = None,
    subcode: str | int | None = None,
    message: str = "",
) -> str:
    """Return a user-friendly explanation for a WhatsApp Cloud API error.

    Looks up the error by ``subcode`` (most specific) then ``code``, and
    finally by scanning ``message`` for known phrases (e.g. 24-hour
    window). Falls back to a sanitized version of the raw message.
    """
    sc = int(subcode) if subcode and str(subcode).isdigit() else None
    c = int(code) if code and str(code).isdigit() else None

    # --- Subcode-level (most specific) ---
    if sc in _SUBCODE_MESSAGES:
        return _SUBCODE_MESSAGES[sc]

    # --- Code-level ---
    if c in _CODE_MESSAGES:
        return _CODE_MESSAGES[c]

    # --- Message-fragment fallbacks (for codes not yet mapped) ---
    lower = (message or "").lower()
    for fragment, friendly in _MESSAGE_FRAGMENTS:
        if fragment in lower:
            return friendly

    # --- Sanitized fallback: strip Meta internals from the message ---
    return _sanitize(message)


# =====================================================================
# Lookup tables
# =====================================================================

_CODE_MESSAGES: dict[int, str] = {
    4: "WhatsApp's rate limit has been reached. Please wait a moment and try again.",
    10: "Permission denied. Your access token may not have the required WhatsApp permissions. Please check your Meta App configuration.",
    190: "Your WhatsApp access token has expired or been revoked. Please reconnect your account with a fresh token.",
    200: "Permission denied for this WhatsApp operation. Verify that your access token has the whatsapp_business_messaging permission.",
    80007: "The recipient's phone number is not a valid WhatsApp number or cannot receive messages.",
    261000: "The WhatsApp Business Account could not be found. Please verify your WABA ID and phone number ID are correct.",
}


_SUBCODE_MESSAGES: dict[int, str] = {
    # 24-hour window — the most common agent-facing restriction
    101013: (
        "This message cannot be sent because more than 24 hours have passed "
        "since the customer's last message. WhatsApp only allows free-form "
        "replies within 24 hours of the customer's last message. Please use a "
        "pre-approved message template to re-open the conversation."
    ),
    131047: (
        "The 24-hour customer service window has closed. You can only send a "
        "pre-approved message template until the customer replies again."
    ),
    # Number registration / migration issues
    132000: (
        "This phone number is not registered with the WhatsApp Business "
        "Platform (Cloud API). If it is currently registered with the WhatsApp "
        "Business App, you must migrate it to the Cloud API first. See the "
        "migration guide on the Channels page."
    ),
    132001: (
        "This phone number is not registered with the WhatsApp Business "
        "Platform. Please complete the number migration from the WhatsApp "
        "Business App to the Cloud API. See the migration guide on the "
        "Channels page."
    ),
    133415: (
        "This phone number is not registered on the Cloud API. Please migrate "
        "it from the WhatsApp Business App. See the migration guide on the "
        "Channels page."
    ),
    # Recipient / opt-out issues
    131030: "The recipient has blocked your number or opted out of WhatsApp messages from your business.",
    131042: "The recipient's phone number does not have an active WhatsApp account.",
    131051: "The recipient's phone number is not in the allowed country list for your WhatsApp Business Account.",
    # Template issues
    132002: "The message template name was not found. Please verify the template name and that it is approved.",
    132006: "The message template is in the wrong language. Please check the template language code.",
    132007: "The message template has not been approved yet. Only approved templates can be sent.",
    132012: "The message template parameters are invalid. Please check the number and type of variables in the template.",
    132015: "The message template is currently paused and cannot be sent.",
    132016: "The message template has been rejected. Please create a new template for review.",
    # Media / content
    131013: "The media type is not supported. WhatsApp supports image, audio, video, document, and sticker attachments.",
    131016: "The message content is too long. WhatsApp text messages are limited to 4096 characters.",
    131021: "The media URL is invalid or unreachable. Please check that the file URL is publicly accessible.",
    # Authentication
    132100: "Your WhatsApp access token is invalid. Please update your credentials in the channel settings.",
    132101: "Your access token does not have permission to perform this action. Please check your system-user token permissions.",
    # Quality / rate
    131048: "Your WhatsApp number's quality rating is too low to send messages right now. Please wait and try again later.",
}


# (substring-to-match-case-insensitively, friendly-message)
# Scanned in order; first match wins.
_MESSAGE_FRAGMENTS: list[tuple[str, str]] = [
    (
        "24 hour",
        (
            "This message cannot be sent because the 24-hour customer service "
            "window has closed. Use a pre-approved message template to reach the "
            "customer again."
        ),
    ),
    (
        "window",
        (
            "The 24-hour messaging window has closed. Only template messages can "
            "be sent until the customer replies."
        ),
    ),
    (
        "not registered",
        (
            "This phone number is not registered with the WhatsApp Business "
            "Platform (Cloud API). If it is connected to the WhatsApp Business "
            "App, please migrate it first. See the migration guide on the Channels "
            "page."
        ),
    ),
    (
        "template",
        (
            "There was an issue with the WhatsApp message template. Please verify "
            "the template name, language, and parameters."
        ),
    ),
    (
        "rate limit",
        ("WhatsApp's rate limit has been reached. Please slow down and retry in a moment."),
    ),
    (
        "access token",
        (
            "Your WhatsApp access token is invalid or expired. Please update your "
            "credentials in the channel settings."
        ),
    ),
    (
        "insufficient",
        (
            "Your access token does not have sufficient permissions. Please check "
            "your Meta system-user token configuration."
        ),
    ),
]


def _sanitize(message: str) -> str:
    """Return a cleaned, user-safe version of a raw Meta error message.

    Strips common Meta-internal references (error types, fbtrace_id, etc.)
    and truncates to a reasonable length. If the message looks too technical,
    a generic fallback is used instead.
    """
    if not message:
        return "WhatsApp could not process this request. Please try again or contact support."

    # Strip fbtrace references and Meta error codes like "(#100)"
    cleaned = message
    for prefix in (
        "WhatsApp send failed: ",
        "WhatsApp verify failed: ",
        "WhatsApp authenticate failed: ",
    ):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break

    # Remove trailing "(fbtrace_id: ...)" artifacts
    if "fbtrace_id" in cleaned.lower():
        cleaned = cleaned.split("(fbtrace_id")[0].strip()

    # Remove Meta error-code prefix like "(#100)" at the start
    if cleaned.startswith("(#") and ")" in cleaned:
        cleaned = cleaned.split(")", 1)[1].strip()

    # If nothing useful remains, use the generic fallback
    if not cleaned or len(cleaned) < 10:
        return "WhatsApp could not process this request. Please verify your settings and try again."

    # Truncate very long messages
    if len(cleaned) > 200:
        cleaned = cleaned[:197] + "..."

    return cleaned
