# students/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Student, StudentQR

@receiver(post_save, sender=Student)
def create_student_qr(sender, instance, created, **kwargs):
    if created:
        StudentQR.objects.create(student=instance)
