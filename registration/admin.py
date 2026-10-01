from django.contrib import admin

from .models import Course, CourseSection, StudentProfile, Term


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("course_code", "title", "credits")
    search_fields = ("course_code", "title")


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("name", "registration_opens_at", "registration_closes_at")


@admin.register(CourseSection)
class CourseSectionAdmin(admin.ModelAdmin):
    list_display = ("course", "term", "section_code", "capacity", "seats_filled", "waitlist_capacity")
    list_filter = ("term",)
    readonly_fields = ("seats_filled", "version")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "student_id")
    readonly_fields = ("user", "student_id")
