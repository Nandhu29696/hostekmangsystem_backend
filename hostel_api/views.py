# students/views.py
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from account.models import User
from hostel_api.serializers import (
    StudentCreateSerializer,
    ResendStudentCredentialsSerializer,
    AutoRoomAssignSerializer,
    RoomAllocateSerializer,
    RoomCreateSerializer,
    BulkRoomCreateSerializer,
    RoomTransferSerializer,
    StudentStayHistorySerializer,
    OccupancyTimelineSerializer,
    StudentUpdateSerializer,
    HostelFeeConfigSerializer,
    RoomUpdateSerializer,
    AttendanceSerializer,
    StudentFeeDetailsSerializer,
    CreateComplaintSerializer,
    ComplaintListSerializer,
    ComplaintDetailSerializer
)
from rest_framework import status
from account.permissions import IsAdmin, IsAdminOrWarden
from django.utils.timezone import now
from .models import RoomAllocation, Student, Room, HostelFeeConfig, StudentQR, Attendance, Complaint
from .util import calculate_fee
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Sum, Count
from django.shortcuts import get_object_or_404
import qrcode
from django.http import HttpResponse
from .util import generate_or_refresh_qr  
from .pagination import StandardResultsSetPagination
from datetime import timedelta
from django.db.models import Prefetch
from django.utils.dateparse import parse_date 
from datetime import datetime

 
class CreateStudentView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        if request.user.role.name != "ADMIN":
            return Response({"detail": "Access denied"}, status=403)

        serializer = StudentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "Student created & WhatsApp sent"}, status=201)

class StudentQRImageAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        student = get_object_or_404(Student, id=student_id, is_active=True)
        qr = generate_or_refresh_qr(student)
        
        # Generate QR with direct API endpoint URL (like Flask example)
        # When QR is scanned, it will call the QR attendance endpoint
        # Use API_BASE_URL from settings if available, otherwise build from request
        if settings.API_BASE_URL:
            base_url = settings.API_BASE_URL.rstrip('/')
        else:
            base_url = request.build_absolute_uri('/').rstrip('/')
        print(f"Using base URL for QR: {base_url}")
        qr_url = f"{base_url}/api/admin/attendance/qr-scan/{student.id}"
        print(f"Generated QR URL: {qr_url}")
        img = qrcode.make(qr_url)
        response = HttpResponse(content_type="image/png")
        response["Cache-Control"] = "no-store"  # prevent browser caching
        img.save(response, "PNG")

        return response

class QRScanView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        token = request.data.get("token")

        if not token:
            return Response(
                {"error": "QR token required"},
                status=400
            )

        try:
            qr = StudentQR.objects.select_related("student").get(token=token)
        except StudentQR.DoesNotExist:
            return Response(
                {"error": "Invalid QR code"},
                status=400
            )

        if not qr.is_valid():
            return Response(
                {"error": "QR code expired"},
                status=400
            )

        student = qr.student

        return Response({
            "status": "success",
            "student": {
                "id": student.id,
                "name": student.user.name,
                "register_number": student.register_number,
                "course": student.course,
                "room": student.room.room_number if student.room else None,
            }
        })

class StudentUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def put(self, request, student_id):
        student = get_object_or_404(Student, id=student_id, is_active=True)

        serializer = StudentUpdateSerializer(
            student,
            data=request.data,
            partial=True  # allows PATCH-like update
        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Student updated successfully",
                "student": serializer.data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StudentDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def delete(self, request, student_id):
        student = get_object_or_404(Student, id=student_id, is_active=True)

        # Soft delete
        student.is_active = False
        student.save()

        # Disable login
        student.user.is_active = False
        student.user.save()

        return Response({
            "message": "Student deactivated successfully"
        }, status=status.HTTP_200_OK)

class ResendStudentCredentialsView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = ResendStudentCredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"message": "Login credentials resent successfully"},
            status=status.HTTP_200_OK
        )


class AutoAssignRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    @transaction.atomic
    def post(self, request):
        serializer = AutoRoomAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocation = serializer.save()
        return Response(
            {
                "message": "Room automatically assigned",
                "allocation_id": allocation.id
            },
            status=status.HTTP_201_CREATED
        )
        
class AllocateRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    @transaction.atomic
    def post(self, request):
        serializer = RoomAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        allocation = serializer.save()

        return Response(
            {
                "message": "Room allocated successfully",
                "allocation_id": allocation.id
            },
            status=status.HTTP_201_CREATED
        )

class VacateRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    @transaction.atomic
    def post(self, request, allocation_id):

        try:
            allocation = (
                RoomAllocation.objects
                .select_for_update()
                .get(id=allocation_id)
            )
        except RoomAllocation.DoesNotExist:
            return Response(
                {"detail": "Allocation not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Already vacated (idempotent safety)
        if not allocation.is_active:
            return Response(
                {"detail": "Room already vacated"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Vacate allocation
        allocation.is_active = False
        allocation.vacated_at = now()
        allocation.save()

        # Update room occupancy safely
        room = allocation.room
        if room.occupied > 0:
            room.occupied -= 1
            room.save()

        return Response(
            {
                "message": "Room vacated successfully",
                "room_id": room.id,
                "student_id": allocation.student.id
            },
            status=status.HTTP_200_OK
        )
    
class StudentsWithoutRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        allocated_students = RoomAllocation.objects.filter(
            is_active=True
        ).values_list("student_id", flat=True)

        students = Student.objects.exclude(
            id__in=allocated_students
        )

        data = [
            {
                "id": s.id,
                "name": s.user.name,
                "email": s.user.email,
                "register_number": s.register_number,
                "course": s.course,
                "year": s.year
            }
            for s in students
        ]

        return Response(data)

class AvailableRoomsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        rooms = Room.objects.filter(
            is_active=True,
            current_occupancy__lt=F("capacity")
        )

        data = [
            {
                "id": room.id,
                "hostel_block": room.hostel_block,
                "room_number": room.room_number,
                "capacity": room.capacity,
                "current_occupancy": room.current_occupancy,
                "available_slots": room.capacity - room.current_occupancy
            }
            for room in rooms
        ]

        return Response(data)

class CreateRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = RoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = serializer.save()

        return Response(
            {
                "message": "Room created successfully",
                "room_id": room.id
            },
            status=status.HTTP_201_CREATED
        )

class RoomUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def put(self, request, pk):
        room = get_object_or_404(Room, pk=pk)

        serializer = RoomUpdateSerializer(
            room, data=request.data, partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Room updated successfully",
                    "room": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

class RoomDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def delete(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)

            if room.occupied > 0:
                return Response(
                    {"detail": "Room is occupied. Vacate before deleting."},
                    status=400
                )

            room.delete()
            return Response({"message": "Room deleted successfully"})
        except Room.DoesNotExist:
            return Response({"detail": "Room not found"}, status=404)

class BulkCreateRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = BulkRoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rooms = serializer.save()

        return Response(
            {"created_rooms": len(rooms)},
            status=status.HTTP_201_CREATED
        )
        
class AvailableRoomsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        rooms = Room.objects.all()

        data = [
            {
                "id": room.id,
                "block": room.block,
                "room_number": room.room_number,
                "capacity": room.capacity,
                "occupied": room.occupied,
                "available": room.available
            }
            for room in rooms if room.available
        ]

        return Response(data)

class RoomTransferView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def post(self, request):
        serializer = RoomTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()

        return Response(
            {
                "message": "Room transferred successfully",
                "data": result
            },
            status=status.HTTP_200_OK
        )
        
class StudentStayHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user

        # If student role → allow only own history
        if user.role.name == "STUDENT":
            if not hasattr(user, "student_profile"):
                return Response(
                    {"detail": "Student profile not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
            if user.student_profile.id != student_id:
                return Response(
                    {"detail": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Admin / Warden access
        elif user.role.name not in ["ADMIN", "WARDEN"]:
            return Response(
                {"detail": "Access denied"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response(
                {"detail": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        allocations = RoomAllocation.objects.filter(
            student=student
        ).select_related("room").order_by("-allocated_at")

        serializer = StudentStayHistorySerializer(allocations, many=True)

        return Response({
            "student": {
                "id": student.id,
                "name": student.user.name,
                "register_number": student.register_number
            },
            "stay_history": serializer.data
        })
        
class RoomOccupancyTimelineView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        block = request.query_params.get("block")
        room_id = request.query_params.get("room_id")

        rooms = Room.objects.all()

        if block:
            rooms = rooms.filter(block=block)
        if room_id:
            rooms = rooms.filter(id=room_id)

        response = []

        for room in rooms:
            allocations = RoomAllocation.objects.filter(
                room=room
            ).select_related("student__user").order_by("-allocated_at")
            serializer = OccupancyTimelineSerializer(allocations, many=True)
            response.append({
                "room": f"{room.block}-{room.room_number}",
                "capacity": room.capacity,
                "occupied": room.occupied,
                "timeline": serializer.data
            })

        return Response(response)
    
class StudentStaySummaryView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        data = []

        for student in Student.objects.select_related("user"):
            allocations = RoomAllocation.objects.filter(student=student)

            total_days = 0
            current_room = None
            current_days = 0

            for a in allocations:
                end = a.vacated_at or now()
                days = (end.date() - a.allocated_at.date()).days
                total_days += days

                if a.is_active:
                    current_room = f"{a.room.block}-{a.room.room_number}"
                    current_days = days

            data.append({
                "student_id": student.id,
                "name": student.user.name,
                "register_number": student.register_number,
                "total_days": total_days,
                "current_room": current_room,
                "currently_staying_days": current_days
            })

        return Response(data)
    
class StudentStayDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request, student_id):
        student = Student.objects.select_related("user").get(id=student_id)
        allocations = RoomAllocation.objects.filter(student=student).select_related("room")

        history = []
        total_days = 0

        for a in allocations:
            end = a.vacated_at or now()
            days = (end.date() - a.allocated_at.date()).days
            total_days += days

            history.append({
                "room": f"{a.room.block}-{a.room.room_number}",
                "from": a.allocated_at.date(),
                "to": a.vacated_at.date() if a.vacated_at else "Present",
                "days": days
            })

        return Response({
            "student": student.user.name,
            "register_number": student.register_number,
            "stay_history": history,
            "total_days": total_days
        })
        
class StudentCurrentFeeView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request, student_id):
        allocation = RoomAllocation.objects.filter(
            student_id=student_id,
            is_active=True
        ).select_related("room").first()

        if not allocation:
            return Response({
                "student_id": student_id,
                "days": 0,
                "daily_fee": 0,
                "total_fee": 0,
                "message": "Student has no active room allocation"
            }, status=status.HTTP_200_OK)

        # ✅ SAFE FETCH
        fee_config = HostelFeeConfig.objects.order_by("-effective_from").first()

        if not fee_config:
            return Response({
                "student_id": student_id,
                "room": f"{allocation.room.block}-{allocation.room.room_number}",
                "days": 0,
                "daily_fee": 0,
                "total_fee": 0,
                "message": "Fee configuration not set"
            }, status=status.HTTP_200_OK)

        daily_fee = fee_config.daily_fee
        days, amount = calculate_fee(allocation, daily_fee)

        return Response({
            "student_id": student_id,
            "room": f"{allocation.room.block}-{allocation.room.room_number}",
            "days": days,
            "daily_fee": daily_fee,
            "total_fee": amount
        }, status=status.HTTP_200_OK)


class StudentFeeDetailsView(APIView):
    """
    GET /api/students/<student_id>/fee-details?duration_type=daily|weekly|monthly
    
    Returns fee details for a student based on room occupancy with breakdown by duration type.
    
    Query Parameters:
        - duration_type: "daily" | "weekly" | "monthly" (default: "daily")
    
    Permission: Admin, Warden only
    """
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request, student_id):
        # Get student
        try:
            student = Student.objects.select_related("user").get(id=student_id, is_active=True)
        except Student.DoesNotExist:
            return Response(
                {"error": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get active room allocation
        allocation = RoomAllocation.objects.filter(
            student_id=student_id,
            is_active=True
        ).select_related("room").first()

        if not allocation:
            return Response({
                "student_id": student_id,
                "student_name": student.user.name,
                "register_number": student.register_number,
                "error": "Student has no active room allocation"
            }, status=status.HTTP_200_OK)

        # Get fee configuration
        fee_config = HostelFeeConfig.objects.order_by("-effective_from").first()
        
        if not fee_config:
            return Response({
                "student_id": student_id,
                "student_name": student.user.name,
                "register_number": student.register_number,
                "error": "Fee configuration not set"
            }, status=status.HTTP_200_OK)

        # Get duration type from query parameters
        duration_type = request.GET.get("duration_type", "daily").lower()
        
        if duration_type not in ["daily", "weekly", "monthly"]:
            return Response(
                {"error": 'duration_type must be "daily", "weekly", or "monthly"'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Calculate fee details
        daily_fee = allocation.room.daily_fee if hasattr(allocation.room, 'daily_fee') else fee_config.daily_fee
        total_days, total_amount = calculate_fee(allocation, daily_fee)
        
        # Build breakdown based on duration type
        breakdown = self._calculate_breakdown(allocation, daily_fee, duration_type, total_days)

        response_data = {
            "student_id": student_id,
            "student_name": student.user.name,
            "register_number": student.register_number,
            "room": f"{allocation.room.block}-{allocation.room.room_number}",
            "daily_fee": str(daily_fee),
            "total_days": total_days,
            "total_amount": str(total_amount),
            "allocated_at": allocation.allocated_at.isoformat(),
            "vacated_at": allocation.vacated_at.isoformat() if allocation.vacated_at else None,
            "duration_type": duration_type,
            "breakdown": breakdown
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _calculate_breakdown(self, allocation, daily_fee, duration_type, total_days):
        """
        Calculate fee breakdown based on duration type (daily, weekly, monthly)
        """
        from datetime import timedelta
        
        breakdown = []
        start_date = allocation.allocated_at.date()
        end_date = allocation.vacated_at.date() if allocation.vacated_at else now().date()
        current_date = start_date

        if duration_type == "daily":
            # Daily breakdown
            while current_date <= end_date:
                breakdown.append({
                    "period": current_date.isoformat(),
                    "days": 1,
                    "amount": str(daily_fee)
                })
                current_date += timedelta(days=1)

        elif duration_type == "weekly":
            # Weekly breakdown
            week_start = start_date
            while week_start <= end_date:
                week_end = min(week_start + timedelta(days=6), end_date)
                days_in_week = (week_end - week_start).days + 1
                amount = Decimal(days_in_week) * Decimal(daily_fee)
                
                breakdown.append({
                    "period": f"{week_start.isoformat()} to {week_end.isoformat()}",
                    "days": days_in_week,
                    "amount": str(amount)
                })
                week_start = week_end + timedelta(days=1)

        elif duration_type == "monthly":
            # Monthly breakdown
            month_start = start_date
            while month_start <= end_date:
                # Calculate month end
                if month_start.month == 12:
                    month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)
                
                month_end = min(month_end, end_date)
                days_in_month = (month_end - month_start).days + 1
                amount = Decimal(days_in_month) * Decimal(daily_fee)
                
                breakdown.append({
                    "period": f"{month_start.strftime('%Y-%m')}",
                    "days": days_in_month,
                    "amount": str(amount)
                })
                month_start = month_end + timedelta(days=1)

        return breakdown


class StudentListView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        students = Student.objects.select_related("user").prefetch_related(
            Prefetch(
                "roomallocation_set",
                queryset=RoomAllocation.objects.filter(is_active=True).select_related("room"),
                to_attr="active_allocations"
            )
        ).filter(is_active=True)

        data = []

        for s in students:
            allocation = s.active_allocations[0] if s.active_allocations else None

            data.append({
                "id": s.id,
                "name": s.user.name,
                "email": s.user.email,
                "register_number": s.register_number,
                "course": s.course,
                "year": s.year,
                "mobile_number": s.mobile_number,
                "parent_name": s.parent_name,
                "parent_mobile": s.parent_mobile,
                "created_at": s.created_at,

                # ✅ FIXED ROOM DATA
                "room": {
                    "id": allocation.room.id,
                    "hostel_block": allocation.room.block,
                    "room_number": allocation.room.room_number
                } if allocation else None,

                "is_active": s.is_active
            })

        return Response(data)

class StudentsWithoutRoomView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        allocated_student_ids = RoomAllocation.objects.filter(
            is_active=True
        ).values_list("student_id", flat=True)

        students = Student.objects.select_related("user").exclude(
            id__in=allocated_student_ids
        )

        data = [
            {
                "id": s.id,
                "name": s.user.name,
                "email": s.user.email,
                "register_number": s.register_number,
                "course": s.course,
                "year": s.year,
            }
            for s in students
        ]

        return Response(data)

class RoomListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        rooms = Room.objects.all().order_by("block", "room_number")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(rooms, request)

        data = [
            {
                "id": room.id,
                "block": room.block,
                "room_number": room.room_number,
                "capacity": room.capacity,
                "occupied": room.occupied,
                "available": room.available,
            }
            for room in page
        ]

        return paginator.get_paginated_response(data)

class AdminDashboardStatsView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        total_students = Student.objects.count()

        students_without_room = Student.objects.exclude(
            id__in=RoomAllocation.objects.filter(
                is_active=True
            ).values_list("student_id", flat=True)
        ).count()

        total_rooms = Room.objects.count()

        total_capacity = Room.objects.aggregate(
            total=Sum("capacity")
        )["total"] or 0

        occupied = Room.objects.aggregate(
            total=Sum("occupied")
        )["total"] or 0

        available = total_capacity - occupied

        occupancy_percent = (
            round((occupied / total_capacity) * 100, 2)
            if total_capacity > 0 else 0
        )

        # Recent room allocations
        recent_allocations = RoomAllocation.objects.select_related(
            "student__user", "room"
        ).order_by("-allocated_at")[:5]

        recent_data = [
            {
                "student": alloc.student.user.name,
                "register_number": alloc.student.register_number,
                "room": f"{alloc.room.block}-{alloc.room.room_number}",
                "date": alloc.allocated_at.date(),
            }
            for alloc in recent_allocations
        ]

        return Response({
            "counts": {
                "total_students": total_students,
                "students_without_room": students_without_room,
                "total_rooms": total_rooms,
                "occupied": occupied,
                "available": available,
                "occupancy_percent": occupancy_percent,
            },
            "recent_allocations": recent_data
        })

class RoomOccupancyView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        total_capacity = Room.objects.aggregate(
            total=Sum("capacity")
        )["total"] or 0

        occupied = Room.objects.aggregate(
            total=Sum("occupied")
        )["total"] or 0

        available = total_capacity - occupied

        percentage = round(
            (occupied / total_capacity) * 100, 2
        ) if total_capacity > 0 else 0

        return Response({
            "total_capacity": total_capacity,
            "occupied": occupied,
            "available": available,
            "occupancy_percentage": percentage
        })

class StudentStayDurationView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        allocations = RoomAllocation.objects.select_related(
            "student__user", "room"
        )

        data = []
        for a in allocations:
            end_date = a.vacated_at or now()
            days = (end_date.date() - a.allocated_at.date()).days

            data.append({
                "student": a.student.user.name,
                "register_number": a.student.register_number,
                "room": f"{a.room.block}-{a.room.room_number}",
                "days_stayed": max(days, 1)
            })

        return Response(data)

FEE_PER_DAY = 300

class FeeSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request):
        allocations = RoomAllocation.objects.all()

        total_revenue = 0
        daily_revenue = {}

        for a in allocations:
            start_date = a.allocated_at.date()
            end_date = (a.vacated_at.date() if a.vacated_at else now().date())

            current_date = start_date

            while current_date <= end_date:
                daily_revenue[str(current_date)] = daily_revenue.get(str(current_date), 0) + FEE_PER_DAY
                total_revenue += FEE_PER_DAY
                current_date += timedelta(days=1)

        return Response({
            "total_revenue": total_revenue,
            "daily_revenue": daily_revenue
        })
        
class CurrentHostelFeeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = now().date()

        fee = HostelFeeConfig.objects.filter(
            effective_from__lte=today
        ).order_by("-effective_from").first()

        if not fee:
            return Response({
                "daily_fee": 0,
                "message": "Fee configuration not set"
            })

        return Response(HostelFeeConfigSerializer(fee).data)
    
class CreateHostelFeeConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = HostelFeeConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        effective_from = serializer.validated_data["effective_from"]

        # ❗ Prevent duplicate effective date
        if HostelFeeConfig.objects.filter(effective_from=effective_from).exists():
            return Response(
                {"error": "Fee already exists for this date"},
                status=400
            )

        serializer.save()

        return Response(
            {
                "message": "Hostel fee configuration created",
                "data": serializer.data,
            },
            status=201,
        )

class HostelFeeConfigListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fees = HostelFeeConfig.objects.all()
        serializer = HostelFeeConfigSerializer(fees, many=True)
        return Response(serializer.data)

class AttendanceRequest(APIView):
    """
    POST → Bulk mark attendance
    GET  → Get attendance by date ?date=YYYY-MM-DD
    """

    def post(self, request):
        """
        Expected payload:
        {
            "date": "2026-02-18",
            "records": [
                {"student_id": 1, "status": "present"},
                {"student_id": 2, "status": "absent"}
            ]
        }
        """

        date = request.data.get("date")
        records = request.data.get("records", [])

        if not date or not records:
            return Response(
                {"message": "Date and records are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed_date = parse_date(date)
        if not parsed_date:
            return Response(
                {"message": "Invalid date format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                for record in records:
                    student_id = record.get("student_id")
                    status_value = record.get("status")

                    if status_value not in ["present", "absent"]:
                        continue  # skip invalid status

                    Attendance.objects.update_or_create(
                        student_id=student_id,
                        date=parsed_date,
                        defaults={"status": status_value},
                    )

            return Response(
                {"message": "Attendance saved successfully"},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"message": "Something went wrong"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def get(self, request):
        """
        GET /attendance/?date=2026-02-18
        """

        date = request.GET.get("date")

        if not date:
            return Response(
                {"message": "Date query parameter required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed_date = parse_date(date)
        if not parsed_date:
            return Response(
                {"message": "Invalid date format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        records = Attendance.objects.filter(date=parsed_date)
        serializer = AttendanceSerializer(records, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentsByRoomAPIView(APIView):
    """
    GET /attendance/students/<room_id>

    Returns all active students for a given room.
    """

    def get(self, request, room_id):

        # Ensure room exists
        room = get_object_or_404(Room, id=room_id)

        # Fetch active students in room
        students = (
            Student.objects
            .filter(room_id=room.id, is_active=True)
            .values(
                "id",
                 "register_number",
            )
            .order_by("id")
        )

        return Response(
            {
                "room": {
                    "id": room.id,
                    "room_number": room.room_number,
                },
                "total_students": students.count(),
                "students": list(students),
            },
            status=status.HTTP_200_OK,
        )


class AdminAttendanceByRoomView(APIView):
    """
    GET /api/admin/attendance/students/<room_id>?date=YYYY-MM-DD
    
    Returns all active students in a specific room with their attendance status for a given date.
    
    Permission: Admin, Warden only
    """
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request, room_id):
        """
        Get students in a room with their attendance status for a specific date.
        
        Query Parameters:
            - date: YYYY-MM-DD format (required)
        
        Response:
        {
            "room": {
                "id": 1,
                "room_number": "101",
                "block": "A"
            },
            "date": "2026-02-18",
            "total_students": 2,
            "attendance_summary": {
                "present": 1,
                "absent": 1,
                "not_marked": 0
            },
            "students": [
                {
                    "id": 1,
                    "name": "John Doe",
                    "register_number": "REG001",
                    "course": "B.Tech",
                    "year": 1,
                    "attendance_status": "present"
                },
                {
                    "id": 2,
                    "name": "Jane Smith",
                    "register_number": "REG002",
                    "course": "B.Tech",
                    "year": 1,
                    "attendance_status": "absent"
                }
            ]
        }
        """
        
        # Get date parameter
        date_param = request.GET.get("date")
        
        if not date_param:
            return Response(
                {"error": "Date query parameter is required (format: YYYY-MM-DD)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Parse date
        attendance_date = parse_date(date_param)
        if not attendance_date:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Verify room exists
        room = get_object_or_404(Room, id=room_id)
        
        # Fetch all active students in the room
        students = (
            Student.objects
            .select_related("user")
            .filter(room_id=room_id, is_active=True)
            .order_by("id")
        )
        
        if not students.exists():
            return Response(
                {
                    "room": {
                        "id": room.id,
                        "room_number": room.room_number,
                        "block": room.block
                    },
                    "date": attendance_date.isoformat(),
                    "total_students": 0,
                    "attendance_summary": {
                        "present": 0,
                        "absent": 0,
                        "not_marked": 0
                    },
                    "students": []
                },
                status=status.HTTP_200_OK,
            )
        
        # Build student list with attendance status
        student_list = []
        attendance_counts = {"present": 0, "absent": 0, "not_marked": 0}
        
        for student in students:
            # Get attendance record for this student and date
            attendance = Attendance.objects.filter(
                student=student,
                date=attendance_date
            ).first()
            
            attendance_status = attendance.status if attendance else "not_marked"
            if attendance_status in attendance_counts:
                attendance_counts[attendance_status] += 1
            
            student_data = {
                "id": student.id,
                "name": student.user.name,
                "email": student.user.email,
                "register_number": student.register_number,
                "course": student.course,
                "year": student.year,
                "mobile_number": student.mobile_number,
                "attendance_status": attendance_status
            }
            student_list.append(student_data)
        
        return Response(
            {
                "room": {
                    "id": room.id,
                    "room_number": room.room_number,
                    "block": room.block
                },
                "date": attendance_date.isoformat(),
                "total_students": len(student_list),
                "attendance_summary": attendance_counts,
                "students": student_list
            },
            status=status.HTTP_200_OK,
        )


class CreateComplaintView(APIView):
    """
    POST /api/complaints/create
    
    Create a new complaint for a student.
    
    Permission: Authenticated users
    
    Request Body:
    {
        "student": 1,
        "category": "maintenance",
        "description": "The water supply in the hostel is not working properly"
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreateComplaintSerializer(data=request.data)
        if serializer.is_valid():
            complaint = serializer.save()
            return Response(
                {
                    "message": "Complaint created successfully",
                    "complaint_id": complaint.id,
                    "status": complaint.status
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ComplaintListView(APIView):
    """
    GET /api/complaints/list
    
    List all complaints with filtering and pagination support.
    
    Permission: Admin, Warden only
    
    Query Parameters:
        - status: "OPEN", "IN_PROGRESS", "CLOSED" (optional)
        - category: category name (optional)
        - student_id: student ID (optional)
        - page: page number (optional, default: 1)
    
    Response: List of complaints with student details
    """
    permission_classes = [IsAuthenticated, IsAdminOrWarden]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        # Base queryset
        complaints = (
            Complaint.objects
            .select_related('student__user', 'assigned_to')
            .all()
            .order_by('-created_at')
        )

        # Apply filters
        status_filter = request.GET.get('status')
        category_filter = request.GET.get('category')
        student_id_filter = request.GET.get('student_id')

        if status_filter:
            if status_filter.upper() not in ['OPEN', 'IN_PROGRESS', 'CLOSED']:
                return Response(
                    {"error": "Invalid status. Must be OPEN, IN_PROGRESS, or CLOSED"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            complaints = complaints.filter(status=status_filter.upper())

        if category_filter:
            complaints = complaints.filter(category__icontains=category_filter)

        if student_id_filter:
            try:
                student_id_filter = int(student_id_filter)
                complaints = complaints.filter(student_id=student_id_filter)
            except ValueError:
                return Response(
                    {"error": "Invalid student_id"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Pagination
        paginator = self.pagination_class()
        paginated_complaints = paginator.paginate_queryset(complaints, request)

        serializer = ComplaintListSerializer(paginated_complaints, many=True)
        
        return paginator.get_paginated_response(
            {
                "total_count": paginator.page.paginator.count,
                "complaints": serializer.data
            }
        )


class ComplaintDetailView(APIView):
    """
    GET /api/complaints/<complaint_id>
    
    Retrieve detailed information about a specific complaint.
    
    Permission: Admin, Warden, or the student who filed the complaint
    """
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def get(self, request, complaint_id):
        try:
            complaint = Complaint.objects.select_related(
                'student__user', 'assigned_to'
            ).get(id=complaint_id)
        except Complaint.DoesNotExist:
            return Response(
                {"error": "Complaint not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ComplaintDetailSerializer(complaint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UpdateComplaintStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrWarden]

    def put(self, request, complaint_id):
        try:
            complaint = Complaint.objects.get(id=complaint_id)
        except Complaint.DoesNotExist:
            return Response(
                {"error": "Complaint not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get request data
        new_status = request.data.get('status')
        assigned_to_id = request.data.get('assigned_to')

        # Validate status
        if new_status:
            valid_statuses = ['OPEN', 'IN_PROGRESS', 'CLOSED']
            if new_status.upper() not in valid_statuses:
                return Response(
                    {"error": f"Invalid status. Must be one of {valid_statuses}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            complaint.status = new_status.upper()

        # Assign to user
        if assigned_to_id:
            try:
                assigned_to = get_object_or_404(User, id=assigned_to_id)
                complaint.assigned_to = assigned_to
            except:
                return Response(
                    {"error": "User not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        complaint.save()

        serializer = ComplaintDetailSerializer(complaint)
        return Response(
            {
                "message": "Complaint updated successfully",
                "complaint": serializer.data
            },
            status=status.HTTP_200_OK
        )


class DeleteComplaintView(APIView):
    """
    DELETE /api/complaints/<complaint_id>
    
    Delete a complaint (Admin only)
    
    Permission: Admin only
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def delete(self, request, complaint_id):
        try:
            complaint = Complaint.objects.get(id=complaint_id)
        except Complaint.DoesNotExist:
            return Response(
                {"error": "Complaint not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        complaint_data = {
            "id": complaint.id,
            "student_name": complaint.student.user.name,
            "category": complaint.category
        }

        complaint.delete()

        return Response(
            {
                "message": "Complaint deleted successfully",
                "deleted_complaint": complaint_data
            },
            status=status.HTTP_200_OK
        )
    
class QRCodeAttendanceView(APIView):
    """
    API endpoint to display student details when QR code is scanned.
    Returns HTML page for browser/QR scanner apps, JSON for API clients.
    """
    authentication_classes = []  # Allow unauthenticated access for mobile QR scanners
    permission_classes = []
    
    def get(self, request, student_id):
        """Handle GET request when QR scanner redirects via GET"""
        try:
            student = Student.objects.select_related("user", "room").get(
                id=student_id,
                is_active=True
            )
            
            # Check if request is from browser/QR scanner (Accept header)
            accept_header = request.META.get('HTTP_ACCEPT', '')
            is_browser = 'text/html' in accept_header or 'application/xhtml' in accept_header
            
            # Record attendance
            today = datetime.now().date()
            Attendance.objects.get_or_create(
                student=student,
                date=today,
                defaults={"status": "present"}
            )
            
            if is_browser:
                # Return HTML for mobile QR scanner apps
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Attendance Captured</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            min-height: 100vh;
                            margin: 0;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        }}
                        .container {{
                            background: white;
                            padding: 40px;
                            border-radius: 10px;
                            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
                            text-align: center;
                            max-width: 500px;
                        }}
                        .success {{
                            color: #28a745;
                            font-size: 48px;
                            margin-bottom: 20px;
                        }}
                        h1 {{
                            color: #333;
                            margin: 10px 0;
                        }}
                        .student-info {{
                            background: #f8f9fa;
                            padding: 20px;
                            border-radius: 8px;
                            margin: 20px 0;
                            text-align: left;
                        }}
                        .info-row {{
                            display: flex;
                            justify-content: space-between;
                            padding: 8px 0;
                            border-bottom: 1px solid #dee2e6;
                        }}
                        .info-row:last-child {{
                            border-bottom: none;
                        }}
                        .label {{
                            font-weight: bold;
                            color: #666;
                        }}
                        .value {{
                            color: #333;
                        }}
                        .message {{
                            color: #666;
                            margin-top: 20px;
                            font-size: 14px;
                        }}
                        .date {{
                            font-weight: bold;
                            color: #667eea;
                            font-size: 16px;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="success">✅</div>
                        <h1>Attendance Captured!</h1>
                        <div class="student-info">
                            <div class="info-row">
                                <span class="label">Name:</span>
                                <span class="value">{student.user.name}</span>
                            </div>
                            <div class="info-row">
                                <span class="label">Register Number:</span>
                                <span class="value">{student.register_number}</span>
                            </div>
                            <div class="info-row">
                                <span class="label">Course:</span>
                                <span class="value">{student.course}</span>
                            </div>
                            <div class="info-row">
                                <span class="label">Room:</span>
                                <span class="value">{student.room.room_number if student.room else 'Not Assigned'}</span>
                            </div>
                            <div class="info-row">
                                <span class="label">Date:</span>
                                <span class="value">{today}</span>
                            </div>
                        </div>
                        <div class="message">
                            Your attendance has been captured for <span class="date">{today}</span>
                        </div>
                    </div>
                </body>
                </html>
                """
                return HttpResponse(html_content, content_type='text/html')
            else:
                # Return JSON for API clients
                return Response({
                    'status': 'success',
                    'message': f'Attendance captured for {student.user.name}',
                    'student': {
                        'id': student.id,
                        'name': student.user.name,
                        'register_number': student.register_number,
                        'course': student.course,
                        'room': student.room.room_number if student.room else None,
                        'status': 'Active' if student.is_active else 'Inactive',
                    },
                    'date': str(today)
                }, status=status.HTTP_200_OK)
            
        except Student.DoesNotExist:
            # Check if browser request
            accept_header = request.META.get('HTTP_ACCEPT', '')
            is_browser = 'text/html' in accept_header or 'application/xhtml' in accept_header
            
            if is_browser:
                html_error = """
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Invalid QR</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            min-height: 100vh;
                            margin: 0;
                            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                        }
                        .container {
                            background: white;
                            padding: 40px;
                            border-radius: 10px;
                            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
                            text-align: center;
                            max-width: 400px;
                        }
                        .error {
                            font-size: 48px;
                            margin-bottom: 20px;
                        }
                        h1 {
                            color: #f5576c;
                            margin: 10px 0;
                        }
                        p {
                            color: #666;
                            font-size: 16px;
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="error">❌</div>
                        <h1>Invalid Student QR</h1>
                        <p>Student not found or inactive</p>
                    </div>
                </body>
                </html>
                """
                return HttpResponse(html_error, content_type='text/html', status=404)
            else:
                return Response({
                    'status': 'error',
                    'message': 'Invalid Student QR ❌'
                }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            accept_header = request.META.get('HTTP_ACCEPT', '')
            is_browser = 'text/html' in accept_header or 'application/xhtml' in accept_header
            
            if is_browser:
                html_error = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Error</title>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            min-height: 100vh;
                            margin: 0;
                            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                        }}
                        .container {{
                            background: white;
                            padding: 40px;
                            border-radius: 10px;
                            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
                            text-align: center;
                            max-width: 400px;
                        }}
                        h1 {{
                            color: #f5576c;
                        }}
                        p {{
                            color: #666;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>Error</h1>
                        <p>{str(e)}</p>
                    </div>
                </body>
                </html>
                """
                return HttpResponse(html_error, content_type='text/html', status=500)
            else:
                return Response({
                    'status': 'error',
                    'message': f'Error: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)