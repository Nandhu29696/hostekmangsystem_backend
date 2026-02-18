from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from hostel_api.models import Student
from hostel_api.serializers import auto_assign_room, _find_candidate_room


class Command(BaseCommand):
    help = "Automatically assign available rooms to students without one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done but do not modify any data."
        )
        parser.add_argument(
            "--alert-email",
            type=str,
            help="Optional email address to notify if no rooms remain."
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run")
        alert_email = options.get("alert_email") or getattr(settings, "ROOM_ALERT_EMAIL", None)

        students = Student.objects.filter(is_active=True, room__isnull=True)
        if not students.exists():
            self.stdout.write(self.style.SUCCESS("No unassigned students found."))
            return

        assigned = 0
        for student in students:
            if not dry_run:
                allocation = auto_assign_room(student)
            else:
                # only figure out which room would be chosen, do not save anything
                room = _find_candidate_room(student)
                if room:
                    # create a lightweight stand‑in so rest of the logic works
                    class _Dummy:
                        pass
                    allocation = _Dummy()
                    allocation.room = room
                else:
                    allocation = None

            if allocation:
                assigned += 1
                self.stdout.write(
                    f"{'' if dry_run else 'Assigned '}room {allocation.room} to student {student.id}"
                )
            else:
                self.stdout.write(
                    f"No rooms available for student {student.id}"
                )

        self.stdout.write(
            self.style.SUCCESS(f"Finished. {assigned} student(s) {'would be ' if dry_run else ''}assigned.")
        )

        # if there were students unassigned because of lack of rooms, send alert
        if not dry_run and alert_email:
            remaining = Student.objects.filter(is_active=True, room__isnull=True).count()
            if remaining > 0:
                subject = "Hostel room allocation alert"
                message = (
                    f"{remaining} student(s) remain without rooms after assignment command."
                )
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [alert_email])
                self.stdout.write(
                    self.style.WARNING(f"Alert email sent to {alert_email}")
                )
