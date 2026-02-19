# students/serializers.py
from rest_framework import serializers
from django.utils.crypto import get_random_string 
from .models import Attendance, Student, Room, RoomAllocation, HostelFeeConfig, Complaint
from account.models import Role, User
from django.utils.timezone import now
from django.db import IntegrityError, transaction
from django.db.models import F
from twilio.rest import Client
from django.conf import settings
import pywhatkit as kit
from django.http import JsonResponse
from rest_framework import status
import base64
from .util import generate_or_refresh_qr, generate_qr_image    
from django.utils import timezone
from django.db import transaction
from rest_framework import serializers


# shared utility -------------------------------------------------------------

def send_whatsapp(to_mobile: str, body: str, media_url: str | None = None) -> str:
    
    

    to_whatsapp = f"whatsapp:+91{to_mobile}"  # include country code

    client = Client(account_sid, auth_token)
    params = {
        "from_": from_whatsapp,
        "body": body,
        "to": to_whatsapp,
    }
    if media_url:
        params["media_url"] = [media_url]

    msg = client.messages.create(**params)
    print(f"WhatsApp message sent with SID: {msg.sid}")
    return msg.sid


# room assignment helpers ----------------------------------------------------

def _find_candidate_room(student: Student):
    """Return the best available Room instance for the student or ``None``.

    The lookup avoids using the ``available`` property because it is not a
    real database field; instead we compare capacity vs occupied.  This helper
    is used by both the actual allocator and the dry‑run logic.
    """

    avail = Room.objects.filter(capacity__gt=F("occupied"))
    # prefer same-year
    year_rooms = avail.filter(roomallocation__student__year=student.year)
    if year_rooms.exists():
        candidates = year_rooms
    else:
        course_rooms = avail.filter(roomallocation__student__course=student.course)
        if course_rooms.exists():
            candidates = course_rooms
        else:
            candidates = avail

    return candidates.order_by("occupied").first()


def auto_assign_room(student: Student):
    """Try to allocate an available room for *student*.

    Preference order:
    1. rooms that already contain students in the same year
    2. rooms that contain students on the same course
    3. any available room

    Returns the created :class:`RoomAllocation` or ``None`` if no room could
    be found.
    """

    if getattr(student, "room", None):
        return None

    room = _find_candidate_room(student)
    if not room:
        return None

    allocation = RoomAllocation.objects.create(
        student=student,
        room=room,
        is_active=True,
    )
    room.occupied = F("occupied") + 1
    room.save(update_fields=["occupied"])

    student.hostel_block = room.block
    student.room_number = room.room_number
    student.room = room
    student.save(update_fields=["hostel_block", "room_number", "room"])

    return allocation



class StudentCreateSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField()
    mobile_number = serializers.CharField()
    register_number = serializers.CharField()
    course = serializers.CharField()
    year = serializers.IntegerField()
    parent_name = serializers.CharField()
    parent_mobile = serializers.CharField()

    # ✅ Email uniqueness check
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Student with this email already exists."
            )
        return value

    # ✅ Register number uniqueness check
    def validate_register_number(self, value):
        if Student.objects.filter(register_number=value).exists():
            raise serializers.ValidationError(
                "Student with this register number already exists."
            )
        return value

    @transaction.atomic
    def create(self, validated_data):
        password = get_random_string(8)

        student_role = Role.objects.get(name="STUDENT")
        try:
            user = User.objects.create_user(
                email=validated_data["email"],
                name=validated_data["name"],
                tc=True,
                password=password
            )
            user.role = student_role
            user.is_active = True
            user.save()

            student = Student.objects.create(
                user=user,  
                register_number=validated_data["register_number"],
                mobile_number=validated_data["mobile_number"],
                course=validated_data["course"],
                year=validated_data["year"],
                parent_name=validated_data["parent_name"],
                parent_mobile=validated_data["parent_mobile"],
            )
            
            # build QR and send using shared helper
            qr = generate_or_refresh_qr(student)
            qr_image_url = f"{settings.PUBLIC_BASE_URL}{qr.image.url}"
            body = f"""
🎓 *Student Admission Confirmed*

👤 Name: {student.user.name}
🆔 Register No: {student.register_number}
🎓 Course: {student.course}
📅 Year: {student.year}

"""
            try:
                sid = send_whatsapp(
                    validated_data["mobile_number"],
                    body,
                )
                print(f"WhatsApp SID for new student: {sid}")
            except Exception as exc:
                raise serializers.ValidationError(
                    f"Student created but failed to send WhatsApp: {exc}"
                )

            # automatically allocate a room if possible
            allocation = auto_assign_room(student)
            if allocation:
                print(f"Auto assigned room {allocation.room} to student {student.id}")
            else:
                print("No available room to auto assign")

            return student

        except IntegrityError as e:
            print("Integrity Error: Rolling back transaction", str(e))
            raise serializers.ValidationError(
                "Student already exists with this email or register number."
            )
    
class StudentUpdateSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.name", required=False)
    email = serializers.EmailField(source="user.email", required=False)

    class Meta:
        model = Student
        fields = [
            "name",
            "email",
            "mobile_number",
            "course",
            "year",
            "parent_name",
            "parent_mobile",
        ]

    def validate_email(self, value):
        user = self.instance.user
        if User.objects.exclude(id=user.id).filter(email=value).exists():
            raise serializers.ValidationError("Email already in use.")
        return value

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})

        # Update User
        if user_data:
            for attr, value in user_data.items():
                setattr(instance.user, attr, value)
            instance.user.save()

        # Update Student
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance
        
class ResendStudentCredentialsSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value, role__name="STUDENT").exists():
            raise serializers.ValidationError("Student with this email does not exist.")
        return value

    def save(self):
        user = User.objects.get(email=self.validated_data["email"])
        student = Student.objects.get(user=user)

        # Generate new password
        new_password = get_random_string(8)
        user.set_password(new_password)
        user.save()

        # Send WhatsApp message using shared helper
        body = (
            f"📲 *Hostel login credentials*\n"
            f"Email: {user.email}\n"
            f"Password: {new_password}\n"
            f"(You can change it after first login)"
        )
        send_whatsapp(student.mobile_number, body)

        return user

class AutoRoomAssignSerializer(serializers.Serializer):
    """Serializer for assigning a room to a student automatically."""

    student_id = serializers.IntegerField()

    def validate_student_id(self, value):
        try:
            student = Student.objects.get(id=value, is_active=True)
        except Student.DoesNotExist:
            raise serializers.ValidationError("Student not found")
        if getattr(student, "room", None):
            raise serializers.ValidationError("Student already has a room")
        self.student = student
        return value

    def create(self, validated_data):
        allocation = auto_assign_room(self.student)
        if not allocation:
            raise serializers.ValidationError("No available room to assign")
        return allocation

class RoomAllocateSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    room_id = serializers.IntegerField()

    @transaction.atomic
    def validate(self, data):
        try:
            student = Student.objects.get(id=data["student_id"], is_active=True)
        except Student.DoesNotExist:
            raise serializers.ValidationError("Invalid or inactive student")

        try:
            room = Room.objects.get(id=data["room_id"])
        except Room.DoesNotExist:
            raise serializers.ValidationError("Invalid room")

        if not room.available:
            raise serializers.ValidationError("Room is fully occupied")

        if RoomAllocation.objects.filter(student=student, is_active=True).exists():
            raise serializers.ValidationError("Student already has a room")

        data["student"] = student
        data["room"] = room
        return data

    @transaction.atomic
    def create(self, validated_data):
        student = validated_data["student"]
        room = validated_data["room"]

        # 1️⃣ Create allocation
        allocation = RoomAllocation.objects.create(
            student=student,
            room=room,
            is_active=True
        )

        # 2️⃣ Update room occupancy
        room.occupied += 1
        room.save(update_fields=["occupied"])

        # 3️⃣ Update student table with block & room
        student.hostel_block = room.block   # now it's just a CharField
        student.room_number = room.room_number
        student.room = room          # ✅ save room reference
        student.save(update_fields=["hostel_block", "room_number"])

        return allocation

class RoomCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room 
        fields = ["block", "room_number", "capacity"]

    def validate(self, data):
        if Room.objects.filter(
            block=data["block"],
            room_number=data["room_number"]
        ).exists():
            raise serializers.ValidationError(
                "Room already exists in this block"
            )
        return data

class RoomUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ["block", "room_number", "capacity"]

    def validate_capacity(self, value):
        if value < 1:
            raise serializers.ValidationError("Capacity must be at least 1.")
        return value

    def validate(self, attrs):
        """
        Prevent duplicate room number in same block
        """
        room = self.instance
        block = attrs.get("block", room.block)
        room_number = attrs.get("room_number", room.room_number)

        if Room.objects.exclude(id=room.id).filter(
            block=block, room_number=room_number
        ).exists():
            raise serializers.ValidationError(
                "Room with this number already exists in this block."
            )

        return attrs

class BulkRoomCreateSerializer(serializers.Serializer):
    block = serializers.CharField()
    start_room = serializers.IntegerField()
    end_room = serializers.IntegerField()
    capacity = serializers.IntegerField(default=2)

    def create(self, validated_data):
        rooms = []
        for number in range(
            validated_data["start_room"],
            validated_data["end_room"] + 1
        ):
            rooms.append(
                Room(
                    block=validated_data["block"],
                    room_number=str(number),
                    capacity=validated_data["capacity"]
                )
            )
        return Room.objects.bulk_create(rooms, ignore_conflicts=True)
    
class RoomTransferSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    new_room_id = serializers.IntegerField()

    def save(self):
        

        student_id = self.validated_data["student_id"]
        new_room_id = self.validated_data["new_room_id"]

        with transaction.atomic():

            try:
                student = Student.objects.get(id=student_id)
            except Student.DoesNotExist:
                raise serializers.ValidationError("Student does not exist")
            new_room = Room.objects.get(id=new_room_id)

            # 1️⃣ Get current active allocation
            current_allocation = RoomAllocation.objects.filter(
                student=student,
                is_active=True
            ).select_related("room").first()

            # 2️⃣ Vacate old room
            if current_allocation:
                current_allocation.vacated_at = timezone.now() 
                current_allocation.is_active = False
                current_allocation.save()

                # Optional: decrease occupied count
                current_allocation.room.occupied -= 1
                current_allocation.room.save()

            # 3️⃣ Check new room capacity
            if new_room.occupied >= new_room.capacity:
                raise serializers.ValidationError("Room is already full")

            # 4️⃣ Create new allocation
            new_allocation = RoomAllocation.objects.create(
                student=student,
                room=new_room,
                allocated_at=timezone.now(),
                is_active=True
            )

            # 5️⃣ Increase occupied count
            new_room.occupied += 1
            new_room.save()

        return {
            "student_id": student.id,
            "old_room": current_allocation.room.room_number if current_allocation else None,
            "new_room": new_room.room_number
        }

    @transaction.atomic
    def create(self, validated_data):
        student = validated_data["student"]
        new_room = validated_data["new_room"]
        old_allocation = validated_data["current_allocation"]
        old_room = old_allocation.room

        # 1️⃣ Vacate old room
        old_allocation.is_active = False
        old_allocation.vacated_at = now()
        old_allocation.save()

        old_room.occupied = max(0, old_room.occupied - 1)
        old_room.save()

        # 2️⃣ Allocate new room
        new_allocation = RoomAllocation.objects.create(
            student=student,
            room=new_room,
            is_active=True
        )

        new_room.occupied += 1
        new_room.save()

        return {
            "old_room": f"{old_room.block}-{old_room.room_number}",
            "new_room": f"{new_room.block}-{new_room.room_number}",
            "allocation_id": new_allocation.id
        }

class StudentStayHistorySerializer(serializers.ModelSerializer):
    room = serializers.SerializerMethodField()
    days = serializers.SerializerMethodField()

    class Meta:
        model = RoomAllocation
        fields = [
            "id",
            "room",
            "allocated_at",
            "vacated_at",
            "is_active",
            "days",
        ]

    def get_room(self, obj):
        return {
            "room_id": obj.room.id,
            "block": obj.room.block,
            "room_number": obj.room.room_number
        }

    def get_days(self, obj):
        """Calculate number of days stayed.

        If vacated_at is None use current time.  Return integer days difference.
        """
        end = obj.vacated_at or now()
        return (end.date() - obj.allocated_at.date()).days

class OccupancyTimelineSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.name")
    register_number = serializers.CharField(source="student.register_number")
    status = serializers.SerializerMethodField()

    class Meta:
        model = RoomAllocation
        fields = [
            "student_name",
            "register_number",
            "allocated_at",
            "vacated_at",
            "status"
        ]

    def get_status(self, obj):
        return "Currently Staying" if obj.is_active else "Vacated"
    
class StudentStaySerializer(serializers.ModelSerializer):
    room = serializers.SerializerMethodField()
    days = serializers.SerializerMethodField()

    class Meta:
        model = RoomAllocation
        fields = ("room", "allocated_at", "vacated_at", "days")

    def get_room(self, obj):
        return f"{obj.room.block}-{obj.room.room_number}"

    def get_days(self, obj):
        end_date = obj.vacated_at or now()
        return (end_date.date() - obj.allocated_at.date()).days
    
class HostelFeeConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = HostelFeeConfig
        fields = ["id", "daily_fee", "effective_from", "created_at"]
        
class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.name", read_only=True)

    class Meta:
        model = Attendance
        fields = "__all__"


class StudentFeeDetailsSerializer(serializers.Serializer):
    """
    Serializer for student fee details based on room occupancy duration
    """
    student_id = serializers.IntegerField(read_only=True)
    student_name = serializers.CharField(read_only=True)
    register_number = serializers.CharField(read_only=True)
    room = serializers.CharField(read_only=True)
    daily_fee = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_days = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    allocated_at = serializers.DateTimeField(read_only=True)
    vacated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    duration_type = serializers.CharField(read_only=True)
    breakdown = serializers.ListField(read_only=True)

class CreateComplaintSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new complaint
    """
    class Meta:
        model = Complaint
        fields = ['id', 'student', 'category', 'description', 'status', 'assigned_to', 'created_at']
        read_only_fields = ['id', 'status', 'assigned_to', 'created_at']

    def validate_category(self, value):
        valid_categories = ['maintenance', 'cleanliness', 'noise', 'food', 'security', 'water', 'electricity', 'other']
        if value.lower() not in valid_categories:
            raise serializers.ValidationError(
                f"Category must be one of: {', '.join(valid_categories)}"
            )
        return value.lower()

    def validate_description(self, value):
        if len(value) < 10:
            raise serializers.ValidationError("Description must be at least 10 characters long.")
        return value


class ComplaintListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing complaints with related student information
    """
    student_name = serializers.CharField(source='student.user.name', read_only=True)
    student_email = serializers.CharField(source='student.user.email', read_only=True)
    register_number = serializers.CharField(source='student.register_number', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True, allow_null=True)

    class Meta:
        model = Complaint
        fields = ['id', 'student', 'student_name', 'student_email', 'register_number', 
                  'category', 'description', 'status', 'assigned_to', 'assigned_to_name', 'created_at']
        read_only_fields = ['id', 'created_at']


class ComplaintDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for detailed complaint information
    """
    student_name = serializers.CharField(source='student.user.name', read_only=True)
    student_email = serializers.CharField(source='student.user.email', read_only=True)
    student_phone = serializers.CharField(source='student.mobile_number', read_only=True)
    register_number = serializers.CharField(source='student.register_number', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.name', read_only=True, allow_null=True)

    class Meta:
        model = Complaint
        fields = ['id', 'student', 'student_name', 'student_email', 'student_phone', 
                  'register_number', 'category', 'description', 'status', 'assigned_to', 
                  'assigned_to_name', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_status(self, value):
        valid_statuses = ['OPEN', 'IN_PROGRESS', 'CLOSED']
        if value not in valid_statuses:
            raise serializers.ValidationError(
                f"Status must be one of: {', '.join(valid_statuses)}"
            )
        return value