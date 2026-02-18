import qrcode
import io
from twilio.rest import Client
from django.conf import settings


def send_whatsapp_qr(mobile, student_name, token):
    """
    Send WhatsApp message with QR code link
    """

    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )

    qr_url = f"{settings.FRONTEND_URL}/scan/{token}"

    message_body = f"""
🎓 *Hostel QR Code*

Hi {student_name},

Your QR code for *today* is ready ✅
⏳ Valid for today only

🔗 Scan Link:
{qr_url}

⚠️ Do not share this QR.
"""

    message = client.messages.create(
        body=message_body,
        from_=settings.TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:+91{mobile}",  # 👈 India format
        media_url=[
            f"{settings.PUBLIC_BASE_URL}/media/qr_codes/{token}.png"
        ]
    )

    return message.sid
