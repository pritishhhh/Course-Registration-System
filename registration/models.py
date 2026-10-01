from django.conf import settings
from django.db import models


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    student_id = models.PositiveIntegerField(unique=True)

    def __str__(self):
        return self.user.username


class Course(models.Model):
    course_id = models.AutoField(primary_key=True)
    course_code = models.TextField(unique=True)
    title = models.TextField()
    credits = models.SmallIntegerField(default=3)

    class Meta:
        managed = False
        db_table = "courses"

    def __str__(self):
        return f"{self.course_code}: {self.title}"


class Term(models.Model):
    term_id = models.AutoField(primary_key=True)
    name = models.TextField()
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "terms"

    def __str__(self):
        return self.name


class CourseSection(models.Model):
    section_id = models.AutoField(primary_key=True)
    course = models.ForeignKey(Course, on_delete=models.PROTECT, db_column="course_id")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, db_column="term_id")
    section_code = models.TextField()
    instructor = models.TextField(null=True, blank=True)
    capacity = models.PositiveIntegerField()
    seats_filled = models.PositiveIntegerField(default=0, editable=False)
    waitlist_capacity = models.PositiveIntegerField(default=10)
    version = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        managed = False
        db_table = "course_sections"

    def __str__(self):
        return f"{self.course.course_code}-{self.section_code} ({self.term.name})"
