
# students/utils/qr_utils.py
import uuid
import qrcode
from django.utils import timezone
from hostel_api.models import StudentQR
from django.utils.timezone import now
from decimal import Decimal
from io import BytesIO
from django.core.files.base import ContentFile
from django.conf import settings

def calculate_fee(allocation, daily_fee):
    start = allocation.allocated_at.date()
    end = allocation.vacated_at.date() if allocation.vacated_at else now().date()

    days = (end - start).days + 1
    amount = Decimal(days) * Decimal(daily_fee)

    return days, amount

def generate_or_refresh_qr(student):
    today = timezone.now().date()

    qr, created = StudentQR.objects.get_or_create(
        student=student,
        defaults={
            "token": uuid.uuid4(),
            "valid_date": today,
            "is_active": True
        }
    )

    # 🔁 Refresh QR once per day
    if not created and qr.valid_date != today:
        qr.token = uuid.uuid4()
        qr.valid_date = today
        qr.is_active = True
        qr.image = None  # remove old image

    # 🖼 Generate image only if not exists
    if not qr.image:
        qr_data = f"{settings.FRONTEND_URL}/qr/verify/{qr.token}"

        img = qrcode.make(qr_data)
        buffer = BytesIO()
        img.save(buffer, format="PNG")

        qr.image.save(
            f"student_{student.id}_{today}.png",
            ContentFile(buffer.getvalue()),
            save=False
        )

    qr.save()
    return qr

def generate_qr_image(token):
    qr = qrcode.make(token)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()
