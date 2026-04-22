from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Appointment, Doctor, Notification, Schedule, SignupVerification, Staff, User, Specialization


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "role", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ("last_login", "created_at")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "middle_name", "last_name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "middle_name", "last_name", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "specialization", "contact_number")
    search_fields = ("user__email", "user__first_name", "user__last_name", "specialization")


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "assigned_doctor", "position", "contact_number")
    list_filter = ("position", "assigned_doctor")
    search_fields = ("user__email", "user__first_name", "user__last_name", "position", "assigned_doctor__user__first_name", "assigned_doctor__user__last_name")


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "doctor", "date", "start_time", "end_time", "appointment_pay", "is_available")
    list_filter = ("date", "is_available")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "doctor", "schedule", "handled_by", "appointment_date", "appointment_time", "status")
    list_filter = ("status", "appointment_date")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "is_read", "created_at")
    list_filter = ("is_read", "created_at")

admin.site.register(Specialization)


@admin.register(SignupVerification)
class SignupVerificationAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "attempts", "code_sent_at", "expires_at")
    search_fields = ("email", "first_name", "last_name")
    list_filter = ("code_sent_at", "expires_at", "attempts")
