"""Populate an empty portfolio deployment with a small course catalog."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from registration.models import Course, CourseSection, Term


CATALOG = (
    ("CS101", "Introduction to Programming", 4, "A", "Dr. Rao", 30, 15),
    ("CS201", "Data Structures & Algorithms", 4, "A", "Dr. Iyer", 40, 10),
    ("MA110", "Calculus I", 3, "A", "Dr. Mehta", 50, 10),
    ("EC150", "Principles of Economics", 3, "A", "Dr. Shah", 35, 5),
)


class Command(BaseCommand):
    help = "Add a small demo catalog without creating fake student accounts"

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        term, _ = Term.objects.get_or_create(
            name="Demo term",
            defaults={
                "registration_opens_at": now - timedelta(days=1),
                "registration_closes_at": now + timedelta(days=90),
            },
        )
        created = 0
        for code, title, credits, section_code, instructor, capacity, waitlist_capacity in CATALOG:
            course, _ = Course.objects.get_or_create(
                course_code=code, defaults={"title": title, "credits": credits}
            )
            _, new_section = CourseSection.objects.get_or_create(
                course=course,
                term=term,
                section_code=section_code,
                defaults={
                    "instructor": instructor,
                    "capacity": capacity,
                    "waitlist_capacity": waitlist_capacity,
                },
            )
            created += int(new_section)
        self.stdout.write(self.style.SUCCESS(f"Demo catalog ready; {created} sections created."))
