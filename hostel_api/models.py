# students/models.py
from django.db import models
from account.models import User
import uuid
from django.utils import timezone

class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    
    register_number = models.CharField(max_length=30, unique=True)
    mobile_number = models.CharField(max_length=15)
    
    course = models.CharField(max_length=100)
    year = models.IntegerField()
    hostel_block = models.CharField(max_length=50, blank=True, null=True)
    room_number = models.CharField(max_length=10, blank=True, null=True)

# ✅ add foreign key
    room = models.ForeignKey("Room", on_delete=models.SET_NULL, blank=True, null=True, related_name="students")
    
    parent_name = models.CharField(max_length=100)
    parent_mobile = models.CharField(max_length=15)

    is_active = models.BooleanField(default=True)  # 👈 soft delete
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.name} - {self.register_number}"

class StudentQR(models.Model):
    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        related_name="qr"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    valid_date = models.DateField(default=timezone.now)  # 👈 expires daily
    image = models.ImageField(upload_to="qr_codes/")
    created_at = models.DateTimeField(auto_now_add=True)
    
    def is_valid(self):
        return self.valid_date == timezone.now().date()
    
    def __str__(self):
        return f"QR - {self.student.register_number}"
    
    class Meta:
        unique_together = ("student", "valid_date")

class Room(models.Model):
    block = models.CharField(max_length=50)
    room_number = models.CharField(max_length=10)
    capacity = models.IntegerField(default=2)
    occupied = models.IntegerField(default=0)

    class Meta:
        unique_together = ("block", "room_number")

    def __str__(self):
        return f"{self.block} - {self.room_number}"

    @property
    def available(self):
        return self.capacity > self.occupied
    
class RoomAllocation(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    allocated_at = models.DateTimeField(auto_now_add=True)
    vacated_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "is_active"]),
        ]
        
    def __str__(self):
        return f"{self.student} → {self.room}"
    
class HostelFeeConfig(models.Model):
    daily_fee = models.DecimalField(max_digits=8, decimal_places=2, default=300)
    effective_from = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]
    def __str__(self):
        return f"{self.daily_fee} from {self.effective_from}"
    
class FeeLedger(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    allocation = models.ForeignKey(RoomAllocation, on_delete=models.CASCADE)

    from_date = models.DateField()
    to_date = models.DateField()

    days = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

class Complaint(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    category = models.CharField(max_length=50)
    description = models.TextField()

    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("IN_PROGRESS", "In Progress"),
        ("CLOSED", "Closed"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="OPEN")

    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50)
    model_name = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
class Bed(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="beds")
    bed_number = models.CharField(max_length=10)
    is_occupied = models.BooleanField(default=False)

    class Meta:
        unique_together = ("room", "bed_number")

    def __str__(self):
        return f"{self.room} - Bed {self.bed_number}"

class StudentStay(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)

    check_in = models.DateTimeField()
    check_out = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "is_active"]),
        ]

    def __str__(self):
        return f"{self.student} stay"

class FeePayment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    ledger = models.ForeignKey(FeeLedger, on_delete=models.SET_NULL, null=True, blank=True)

    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField(auto_now_add=True)

    payment_mode = models.CharField(
        max_length=20,
        choices=[
            ("cash", "Cash"),
            ("upi", "UPI"),
            ("bank", "Bank Transfer"),
        ]
    )

    reference_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.student} paid ₹{self.amount_paid}"
    
class GateEntryLog(models.Model):
    ENTRY = "ENTRY"
    EXIT = "EXIT"

    ACTION_CHOICES = [
        (ENTRY, "Entry"),
        (EXIT, "Exit"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    scanned_at = models.DateTimeField(auto_now_add=True)
    scan_date = models.DateField()
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, default=ENTRY)
    is_valid = models.BooleanField(default=True)
    message = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "scan_date"]),
        ]

    def __str__(self):
        return f"{self.student} - {self.scan_date}"
    
class Attendance(models.Model):
    STATUS_CHOICES = (
        ("present", "Present"),
        ("absent", "Absent"),
    )

    student = models.ForeignKey(
        "Student",
        on_delete=models.CASCADE,
        related_name="attendance_records"
    )
    date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.student.name} - {self.date} - {self.status}"  