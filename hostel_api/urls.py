from django.urls import path
from hostel_api.views import (
    AttendanceRequest,
    CreateStudentView,
    StudentsByRoomAPIView,
    AdminAttendanceByRoomView,
    StudentsWithoutRoomView,
    RoomDeleteView,
    StudentQRImageAPI,
    ResendStudentCredentialsView,
    AutoAssignRoomView,
    AllocateRoomView,
    VacateRoomView,
    CreateRoomView,
    BulkCreateRoomView,
    AvailableRoomsView,
    RoomTransferView,
    StudentStayHistoryView,
    RoomOccupancyTimelineView,
    StudentStaySummaryView,
    StudentStayDetailView,
    StudentCurrentFeeView,
    StudentFeeDetailsView,
    StudentListView,
    StudentsWithoutRoomView,
    RoomListView,
    AdminDashboardStatsView,
    RoomOccupancyView,
    StudentStayDurationView,
    FeeSummaryView,
    StudentUpdateView,
    StudentDeleteView,
    CreateHostelFeeConfigView,
    CurrentHostelFeeView,
    HostelFeeConfigListView,
    RoomUpdateView,
    CreateComplaintView,
    ComplaintListView,
    ComplaintDetailView,
    UpdateComplaintStatusView,
    DeleteComplaintView,
)
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    
    # Admin URLs
    path("dashboard-stats", AdminDashboardStatsView.as_view(), name="admin-dashboard-stats"), # used for admin dashboard stats
    path("rooms/occupancy", RoomOccupancyView.as_view(), name="room-occupancy"),  # get room occupancy details count
    path("students/stay", StudentStayDurationView.as_view(), name="student-stay-duration"), # get student stay duration details
    path("fees/summary", FeeSummaryView.as_view(), name="fee-summary"),   # get fee summary details
    
    # Student URLs
    path('students/create', CreateStudentView.as_view(), name='create-student'), # create a new student
    path("students/<int:student_id>/update", StudentUpdateView.as_view(), name="update-student"), # update student details
    path("students/<int:student_id>/delete", StudentDeleteView.as_view(), name="delete-student"), # delete a student
    path("students/<int:student_id>/qr", StudentQRImageAPI.as_view()), # get student QR code image
    path("students/resend-credentials", ResendStudentCredentialsView.as_view(), name="resend-student-credentials"), # resend student credentials via email
    path("students/list", StudentListView.as_view(), name="student-list"), # list all students
    path("students/no-room", StudentsWithoutRoomView.as_view(), name="students-without-room"),# list students without room allocation
    path("students/stay-duration", StudentStaySummaryView.as_view()), # get summary of student stay durations
    path("students/<int:student_id>/stay-duration", StudentStayDetailView.as_view()), # get detailed stay duration for a student
    path("students/<int:student_id>/current-fee", StudentCurrentFeeView.as_view(), name="student-current-fee"), # get current fee details for a student
    path("students/<int:student_id>/fee-details", StudentFeeDetailsView.as_view(), name="student-fee-details"), # get fee details with breakdown (daily/weekly/monthly)
    path("students/<int:student_id>/stay-history", StudentStayHistoryView.as_view(), name="student-stay-history"), # get stay history for a student
    
    # Room URLs
    path("rooms/create", CreateRoomView.as_view(), name="create-room"), # create a new room
    path("rooms/bulk-create", BulkCreateRoomView.as_view(), name="bulk-create-rooms"), # bulk create rooms
    path("rooms/<int:pk>/update", RoomUpdateView.as_view()), # update room details
    path("rooms/<int:room_id>/delete", RoomDeleteView.as_view(), name="room-delete"), # delete a room
    path("rooms/list", RoomListView.as_view(), name="room-list"), # list all rooms
    
    path("rooms/available", AvailableRoomsView.as_view(), name="available-rooms"), # list available rooms
    path("rooms/allocate", AllocateRoomView.as_view(), name="allocate-room"), # allocate a room to a student
    path("rooms/auto-assign", AutoAssignRoomView.as_view(), name="auto-assign-room"), # automatically assign available room
    path("rooms/vacate/<int:allocation_id>", VacateRoomView.as_view(), name="vacate-room"),   # vacate a room for a student
    path("rooms/transfer", RoomTransferView.as_view(), name="room-transfer"), # transfer a student to another room
    path("rooms/occupancy-timeline", RoomOccupancyTimelineView.as_view(), name="room-occupancy-timeline"), # get room occupancy timeline data

    # Hostel Fee Config URLs
    path("fees/config/create", CreateHostelFeeConfigView.as_view()), # create a new hostel fee configuration
    path("fees/config/current", CurrentHostelFeeView.as_view()), # get the current hostel fee configuration
    path("fees/config/list", HostelFeeConfigListView.as_view()), # list all hostel fee configurations
 
    # Attendance URLs
    path("attendance", AttendanceRequest.as_view(), name="attendance"),
    path("attendance/students/<int:room_id>", StudentsByRoomAPIView.as_view(), name="attendance-students-by-room"),
    path("ad/attendance/students/<int:room_id>", AdminAttendanceByRoomView.as_view(), name="admin-attendance-by-room"),
    
    # Complaint Management URLs
    path("complaints/create", CreateComplaintView.as_view(), name="create-complaint"), # create a new complaint
    path("complaints/list", ComplaintListView.as_view(), name="complaint-list"), # list all complaints with filters
    path("complaints/<int:complaint_id>", ComplaintDetailView.as_view(), name="complaint-detail"), # get complaint details
    path("complaints/<int:complaint_id>/update-status", UpdateComplaintStatusView.as_view(), name="update-complaint-status"), # update complaint status
    path("complaints/<int:complaint_id>/delete", DeleteComplaintView.as_view(), name="delete-complaint"), # delete a complaint
]

urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT
)
