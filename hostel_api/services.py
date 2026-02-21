import qrcode
import io
import requests
from django.conf import settings


def send_sms_qr(mobile, student_name, token, student_id=None):
    """
    Send SMS message with QR code link
    """
    api_key = "wrdD5vYBEWCNxc3taG4ojQmIpOfHM2UbyglzF0u7hn8q1JVSRsNkd5xPpVyF9c0a4fTms7tn8goi26WO"
    if not api_key:
        raise ValueError("FAST2SMS_API_KEY not configured in settings")

    qr_url = f"{settings.FRONTEND_URL}/scan/{token}"
    api_qr_url = f"{settings.API_BASE_URL}/api/admin/students/{student_id}/qr" if student_id else None

    message_body = f"""🎓 Hostel QR Code

Hi {student_name},

Your QR code for today is ready ✅
Valid for today only

Scan Link:
{qr_url}"""

    if api_qr_url:
        message_body += f"""

Get QR Code API:
{api_qr_url}"""

    message_body += """

Do not share this QR."""

    url = "https://www.fast2sms.com/dev/bulkV2"
    
    payload = {
        "sender_id": "FSTSMS",
        "message": message_body,
        "language": "english",
        "route": "q",
        "numbers": mobile
    }

    headers = {
        "authorization": api_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        print(f"QR SMS sent to {mobile}: {result}")
        return result.get('request_id', 'success')
    except requests.exceptions.RequestException as e:
        print(f"Failed to send QR SMS: {str(e)}")
        raise
