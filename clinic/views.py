import hashlib
import json
import os
import urllib.error
import time
import urllib.parse
import urllib.request
import uuid
from django.conf import settings
from django.utils import timezone

from django.db import transaction
from django.db.models import Count, Q
from rest_framework import permissions, response, status
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Appointment, Doctor, Notification, Schedule, Specialization, Staff, User
from .serializers import (
    AdminDoctorCreateSerializer,
    AdminDoctorUpdateSerializer,
    AdminScheduleWriteSerializer,
    AdminStaffCreateSerializer,
    AdminStaffUpdateSerializer,
    AppointmentSerializer,
    ClinicTokenObtainPairSerializer,
    DoctorSerializer,
    NotificationSerializer,
    PatientBookingSerializer,
    SignupVerificationConfirmSerializer,
    SignupVerificationRequestSerializer,
    ScheduleSerializer,
    ScheduleWriteSerializer,
    SpecializationSerializer,
    StaffSerializer,
    UserSerializer,
)


def upload_lab_result_image_to_cloudinary(image_data: str) -> str:
    image_data = image_data.strip()
    if not image_data:
        return ''
    if image_data.startswith('http://') or image_data.startswith('https://'):
        return image_data

    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', '').strip()
    api_key = os.environ.get('CLOUDINARY_API_KEY', '').strip()
    api_secret = os.environ.get('CLOUDINARY_API_SECRET', '').strip()
    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError('Cloudinary is not configured.')

    timestamp = str(int(time.time()))
    to_sign = f'timestamp={timestamp}'
    signature = hashlib.sha1(f'{to_sign}{api_secret}'.encode('utf-8')).hexdigest()

    boundary = f'----CloudinaryBoundary{uuid.uuid4().hex}'
    parts = []

    def add_field(name: str, value: str) -> None:
        parts.append(f'--{boundary}\r\n'.encode('utf-8'))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode('utf-8'))
        parts.append(value.encode('utf-8'))
        parts.append(b'\r\n')

    add_field('file', image_data)
    add_field('api_key', api_key)
    add_field('timestamp', timestamp)
    add_field('signature', signature)
    parts.append(f'--{boundary}--\r\n'.encode('utf-8'))

    payload = b''.join(parts)

    request = urllib.request.Request(
        f'https://api.cloudinary.com/v1_1/{cloud_name}/image/upload',
        data=payload,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response_obj:
            data = json.loads(response_obj.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            detail = json.loads(raw).get('error', {}).get('message') or raw
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f'Cloudinary upload failed: {detail}') from exc

    secure_url = data.get('secure_url') or data.get('url')
    if not secure_url:
        raise RuntimeError('Cloudinary upload did not return an image URL.')
    return secure_url


def send_brevo_transactional_email(*, recipient_email: str, recipient_name: str, subject: str, text_content: str) -> None:
    api_key = getattr(settings, "BREVO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BREVO_API_KEY is not set in backend/.env.")

    sender_email = getattr(settings, "MAILER_FROM_EMAIL", "").strip()
    sender_name = getattr(settings, "MAILER_FROM_NAME", "").strip()
    if not sender_email:
        raise RuntimeError("MAILER_FROM_EMAIL is not set in backend/.env.")

    payload = {
        "sender": {
            "email": sender_email,
        },
        "to": [
            {
                "email": recipient_email,
                "name": recipient_name,
            }
        ],
        "subject": subject,
        "textContent": text_content,
    }
    if sender_name:
        payload["sender"]["name"] = sender_name

    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=getattr(settings, "EMAIL_TIMEOUT", 15)) as response_obj:
            response_obj.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("message") or json.loads(raw).get("code") or raw
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"Brevo API email send failed: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Brevo API email send failed: {exc.reason}") from exc


def send_account_credentials_email(*, recipient_name: str, recipient_email: str, role_label: str, password: str) -> None:
    subject = f"Your FilCare Clinic {role_label} account details"
    greeting_name = recipient_name.strip() or "there"
    body = (
        f"Hello {greeting_name},\n\n"
        f"Your {role_label.lower()} account has been created for FilCare Clinic.\n"
        f"Email: {recipient_email}\n"
        f"Password: {password}\n\n"
        "Please log in and change your password immediately after your first sign-in.\n"
    )
    send_brevo_transactional_email(
        recipient_email=recipient_email,
        recipient_name=greeting_name,
        subject=subject,
        text_content=body,
    )


def send_signup_verification_email(*, recipient_name: str, recipient_email: str, verification_code: str) -> None:
    subject = "Your FilCare Clinic verification code"
    greeting_name = recipient_name.strip() or "there"
    body = (
        f"Hello {greeting_name},\n\n"
        "Use the verification code below to complete your FilCare Clinic signup:\n\n"
        f"{verification_code}\n\n"
        "This code expires in 10 minutes.\n"
    )
    send_brevo_transactional_email(
        recipient_email=recipient_email,
        recipient_name=greeting_name,
        subject=subject,
        text_content=body,
    )


def format_email_delivery_hint(exc: Exception) -> str:
    from_email = getattr(settings, "MAILER_FROM_EMAIL", "")
    api_key = getattr(settings, "BREVO_API_KEY", "").strip()
    if api_key:
        return (
            f"{exc}. Brevo API is configured with from address '{from_email}'. "
            "Make sure that sender is verified in Brevo, or use an authenticated domain sender."
        )
    return str(exc)


class IsAdminUserRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == User.Role.ADMIN)


class IsDoctorRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == User.Role.DOCTOR)


class IsStaffRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == User.Role.STAFF)


def cleanup_expired_schedules(doctor=None):
    """
    Remove expired schedules that are no longer linked to appointments.
    We keep booked schedules intact so appointment history is not lost.
    """
    now = timezone.localtime()
    expired = Schedule.objects.filter(
        Q(date__lt=now.date()) | Q(date=now.date(), end_time__lte=now.time())
    )
    if doctor is not None:
        expired = expired.filter(doctor=doctor)
    expired = expired.filter(appointments__isnull=True).distinct()
    deleted_count, _ = expired.delete()
    return deleted_count



class SignupVerificationRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SignupVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = serializer.save()
        try:
            send_signup_verification_email(
                recipient_name=f"{verification.first_name} {verification.last_name}",
                recipient_email=verification.email,
                verification_code=verification.raw_code,
            )
        except Exception as exc:
            verification.delete()
            return response.Response(
                {
                    "detail": "Unable to send the verification email.",
                    "error": format_email_delivery_hint(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return response.Response(
            {
                "message": "Verification code sent to your email.",
                "email": verification.email,
            },
            status=status.HTTP_200_OK,
        )


class PatientSignupView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SignupVerificationConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = {
            "message": "Patient account created successfully.",
            "user": UserSerializer(user).data,
        }
        return response.Response(data, status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]
    serializer_class = ClinicTokenObtainPairSerializer


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return response.Response(UserSerializer(request.user).data)


class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        notifications = Notification.objects.filter(user=user).order_by("-created_at")[:5]
        payload = {
            "user": UserSerializer(user).data,
            "notifications": NotificationSerializer(notifications, many=True).data,
        }

        if user.role == User.Role.ADMIN:
            doctors = Doctor.objects.select_related("user").annotate(staff_count=Count("staff_members")).order_by("user__last_name", "user__first_name")
            staff_members = Staff.objects.select_related("user", "assigned_doctor__user").order_by("user__last_name", "user__first_name")
            payload["stats"] = {
                "total_schedules": Schedule.objects.count(),
                "total_doctors": User.objects.filter(role=User.Role.DOCTOR).count(),
                "total_staff": User.objects.filter(role=User.Role.STAFF).count(),
                "total_patients": User.objects.filter(role=User.Role.PATIENT).count(),
                "total_appointments": Appointment.objects.count(),
                "pending_appointments": Appointment.objects.filter(status=Appointment.Status.PENDING).count(),
                "unread_notifications": Notification.objects.filter(user=user, is_read=False).count(),
            }
            payload["doctors"] = DoctorSerializer(doctors, many=True).data
            payload["staff_members"] = StaffSerializer(staff_members, many=True).data
            payload["recent_appointments"] = AppointmentSerializer(
                Appointment.objects.select_related("patient", "doctor__user", "handled_by__user", "schedule")
                .order_by("-created_at")[:5],
                many=True,
            ).data
            return response.Response(payload)

        if user.role == User.Role.DOCTOR:
            doctor = getattr(user, "doctor_profile", None)
            cleanup_expired_schedules(doctor)
            doctor_appointments = Appointment.objects.filter(doctor=doctor) if doctor else Appointment.objects.none()
            doctor_schedules = Schedule.objects.filter(doctor=doctor) if doctor else Schedule.objects.none()
            payload["profile"] = (
                {
                    "specialization": doctor.specialization.name if doctor.specialization else "",
                    "contact_number": doctor.contact_number,
                }
                if doctor
                else None
            )
            payload["stats"] = {
                "appointments_today": doctor_appointments.filter(appointment_date=today).count(),
                "upcoming_appointments": doctor_appointments.filter(
                    appointment_date__gte=today,
                    status=Appointment.Status.PENDING,
                ).count(),
                "completed_appointments": doctor_appointments.filter(status=Appointment.Status.COMPLETED).count(),
                "total_schedules": doctor_schedules.count(),
                "available_schedules": doctor_schedules.filter(is_available=True).count(),
                "unread_notifications": Notification.objects.filter(user=user, is_read=False).count(),
            }
            payload["recent_appointments"] = AppointmentSerializer(
                doctor_appointments.select_related("patient", "doctor__user", "handled_by__user", "schedule")
                .order_by("appointment_date", "appointment_time")[:5],
                many=True,
            ).data
            return response.Response(payload)

        if user.role == User.Role.STAFF:
            staff = getattr(user, "staff_profile", None)
            doctor = staff.assigned_doctor if staff else None
            doctor_appointments = Appointment.objects.filter(doctor=doctor) if doctor else Appointment.objects.none()
            payload["profile"] = (
                {
                    "position": staff.position,
                    "contact_number": staff.contact_number,
                }
                if staff
                else None
            )
            payload["stats"] = {
                "pending_appointments": doctor_appointments.filter(
                    status__in=[Appointment.Status.PENDING, Appointment.Status.CANCEL_REQUESTED]
                ).count(),
                "confirmed_appointments": doctor_appointments.filter(
                    status=Appointment.Status.CONFIRMED
                ).count(),
                "handled_appointments": doctor_appointments.filter(
                    status__in=[Appointment.Status.COMPLETED, Appointment.Status.CANCELLED]
                ).count(),
                "unread_notifications": Notification.objects.filter(user=user, is_read=False).count(),
            }
            payload["recent_appointments"] = AppointmentSerializer(
                Appointment.objects.select_related("patient", "doctor__user", "handled_by__user", "schedule")
                .order_by("-created_at")[:5],
                many=True,
            ).data
            return response.Response(payload)

        patient_appointments = Appointment.objects.filter(patient=user)
        payload["stats"] = {
            "appointments_today": patient_appointments.filter(
                appointment_date=today,
                status__in=[Appointment.Status.PENDING, Appointment.Status.CONFIRMED]
            ).count(),
            "upcoming_appointments": patient_appointments.filter(
                appointment_date__gte=today,
                status=Appointment.Status.PENDING
            ).count(),
            "confirmed_appointments": patient_appointments.filter(
                status=Appointment.Status.CONFIRMED
            ).count(),
            "completed_appointments": patient_appointments.filter(
                status=Appointment.Status.COMPLETED
            ).count(),
            "unread_notifications": Notification.objects.filter(user=user, is_read=False).count(),
        }
        payload["recent_appointments"] = AppointmentSerializer(
            patient_appointments.select_related("patient", "doctor__user", "handled_by__user", "schedule")
            .order_by("appointment_date", "appointment_time")[:5],
            many=True,
        ).data
        return response.Response(payload)


# Patient booking views
class PatientSpecializationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        specs = Specialization.objects.filter(
            doctor__isnull=False
        ).distinct().order_by('name')
        return response.Response(SpecializationSerializer(specs, many=True).data)


class PatientDoctorListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        spec_id = request.query_params.get('specialization_id')
        doctors = Doctor.objects.select_related('user', 'specialization').annotate(
            staff_count=Count('staff_members')
        )
        if spec_id:
            doctors = doctors.filter(specialization_id=spec_id)
        doctors = doctors.order_by('user__last_name', 'user__first_name')
        return response.Response(DoctorSerializer(doctors, many=True).data)


class PatientDoctorScheduleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, doctor_id):
        from django.utils import timezone
        today = timezone.localdate()
        schedules = Schedule.objects.filter(
            doctor_id=doctor_id,
            is_available=True,
            date__gte=today,
        ).order_by('date', 'start_time')
        return response.Response(ScheduleSerializer(schedules, many=True).data)


class PatientBookAppointmentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PatientBookingSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        appointment = serializer.save()
        return response.Response(
            AppointmentSerializer(Appointment.objects.select_related(
                'patient', 'doctor__user', 'schedule', 'handled_by__user'
            ).get(pk=appointment.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class PatientAppointmentListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        appointments = Appointment.objects.select_related(
            'patient', 'doctor__user', 'schedule', 'handled_by__user'
        ).filter(
            patient=request.user
        ).order_by('-appointment_date', '-appointment_time')
        return response.Response(AppointmentSerializer(appointments, many=True).data)


class PatientSubmitLabResultView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            appointment = Appointment.objects.select_related(
                'doctor__user', 'doctor__specialization'
            ).get(pk=pk, patient=request.user)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found or no lab required.'}, status=status.HTTP_404_NOT_FOUND)

        if not (appointment.needs_laboratory or appointment.lab_result_status == 'rejected'):
            return response.Response({'detail': 'Appointment not found or no lab required.'}, status=status.HTTP_404_NOT_FOUND)

        image_data = request.data.get('lab_result_image', '').strip()
        description = request.data.get('lab_result_description', '').strip()
        if not image_data and not description:
            return response.Response({'detail': 'Please provide a lab result photo or description.'}, status=status.HTTP_400_BAD_REQUEST)

        if image_data:
            try:
                image_data = upload_lab_result_image_to_cloudinary(image_data)
            except Exception as exc:
                return response.Response(
                    {'detail': f'Unable to upload lab result image: {exc}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        appointment.lab_result_image = image_data
        appointment.lab_result_description = description
        appointment.lab_result_submitted = True
        appointment.lab_result_status = 'pending_review'
        appointment.lab_result_reject_reason = ''
        # Keep needs_laboratory=True until doctor approves
        appointment.needs_laboratory = True
        appointment.save()

        # Notify doctor
        Notification.objects.create(
            user=appointment.doctor.user,
            message=(
                f"{request.user.get_full_name()} has submitted their laboratory result "
                f"for the appointment on {appointment.appointment_date}. Please review and approve or reject."
            ),
        )
        return response.Response(AppointmentSerializer(appointment).data)


class DoctorReviewLabResultView(APIView):
    permission_classes = [IsDoctorRole]

    def post(self, request, pk):
        doctor = getattr(request.user, 'doctor_profile', None)
        if not doctor:
            return response.Response({'detail': 'Doctor profile not found.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            appointment = Appointment.objects.select_related(
                'patient', 'doctor__user', 'doctor__specialization'
            ).get(pk=pk, doctor=doctor, lab_result_submitted=True, lab_result_status='pending_review')
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found or lab result not pending review.'}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get('action', '').strip()  # 'approve' or 'reject'
        if action not in ('approve', 'reject'):
            return response.Response({'detail': 'action must be approve or reject.'}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'approve':
            appointment.lab_result_status = 'approved'
            appointment.needs_laboratory = False  # unblock rebooking
            appointment.lab_result_reject_reason = ''
            appointment.save()
            # Notify patient
            Notification.objects.create(
                user=appointment.patient,
                message=(
                    f"Your laboratory result for the appointment with "
                    f"Dr. {doctor.user.get_full_name()} on {appointment.appointment_date} "
                    f"has been approved. You can now book appointments with "
                    f"{doctor.specialization.name if doctor.specialization else 'this'} doctors again."
                ),
            )
            # Notify same-specialization doctors
            if doctor.specialization:
                for other in Doctor.objects.filter(
                    specialization=doctor.specialization
                ).select_related('user').exclude(pk=doctor.pk):
                    Notification.objects.create(
                        user=other.user,
                        message=(
                            f"{appointment.patient.get_full_name()}'s laboratory result has been approved by "
                            f"Dr. {doctor.user.get_full_name()}. They can now book with "
                            f"{doctor.specialization.name} doctors."
                        ),
                    )
        else:
            reject_reason = request.data.get('reject_reason', '').strip()
            if not reject_reason:
                return response.Response({'detail': 'reject_reason is required when rejecting.'}, status=status.HTTP_400_BAD_REQUEST)
            appointment.lab_result_status = 'rejected'
            appointment.lab_result_reject_reason = reject_reason
            appointment.lab_result_submitted = True
            appointment.needs_laboratory = True
            appointment.save()
            # Notify patient
            Notification.objects.create(
                user=appointment.patient,
                message=(
                    f"Your laboratory result was rejected by Dr. {doctor.user.get_full_name()}. "
                    f"Reason: {reject_reason}. Please resubmit your lab result."
                ),
            )

        return response.Response(AppointmentSerializer(appointment).data)


class PatientCancelRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            appointment = Appointment.objects.select_related(
                'doctor__user', 'schedule'
            ).prefetch_related(
                'doctor__staff_members__user'
            ).get(pk=pk, patient=request.user)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found.'}, status=status.HTTP_404_NOT_FOUND)

        if appointment.status not in (
            Appointment.Status.PENDING, Appointment.Status.CONFIRMED
        ):
            return response.Response(
                {'detail': 'Only pending or confirmed appointments can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cancel_reason = request.data.get('cancel_reason', '').strip()
        if not cancel_reason:
            return response.Response({'detail': 'Cancel reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

        appointment.status = Appointment.Status.CANCEL_REQUESTED
        appointment.cancel_reason = cancel_reason
        appointment.save()

        patient_name = request.user.get_full_name()

        # Notify doctor
        Notification.objects.create(
            user=appointment.doctor.user,
            message=(
                f"{patient_name} has requested to cancel their appointment "
                f"on {appointment.appointment_date} at "
                f"{appointment.appointment_time.strftime('%I:%M %p')}. "
                f"Reason: {cancel_reason}"
            ),
        )
        # Notify assigned staff
        for staff in appointment.doctor.staff_members.select_related('user').all():
            Notification.objects.create(
                user=staff.user,
                message=(
                    f"{patient_name} requested cancellation of appointment with "
                    f"Dr. {appointment.doctor.user.get_full_name()} "
                    f"on {appointment.appointment_date}."
                ),
            )

        return response.Response(AppointmentSerializer(appointment).data)


class ApproveCancellationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if user.role not in (User.Role.DOCTOR, User.Role.STAFF, User.Role.ADMIN):
            return response.Response({'detail': 'Not authorized.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            appointment = Appointment.objects.select_related(
                'patient', 'doctor__user', 'schedule'
            ).get(pk=pk, status=Appointment.Status.CANCEL_REQUESTED)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found or not pending cancellation.'}, status=status.HTTP_404_NOT_FOUND)

        # Restore schedule availability
        schedule = appointment.schedule
        schedule.is_available = True
        schedule.save()

        appointment.status = Appointment.Status.CANCELLED
        appointment.save()

        # Notify patient
        Notification.objects.create(
            user=appointment.patient,
            message=(
                f"Your cancellation request for the appointment with "
                f"Dr. {appointment.doctor.user.get_full_name()} "
                f"on {appointment.appointment_date} has been approved."
            ),
        )

        return response.Response(AppointmentSerializer(appointment).data)


class RejectCancellationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        if user.role not in (User.Role.DOCTOR, User.Role.STAFF, User.Role.ADMIN):
            return response.Response({'detail': 'Not authorized.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            appointment = Appointment.objects.select_related(
                'patient', 'doctor__user'
            ).get(pk=pk, status=Appointment.Status.CANCEL_REQUESTED)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found or not pending cancellation.'}, status=status.HTTP_404_NOT_FOUND)

        # Revert to pending
        appointment.status = Appointment.Status.PENDING
        appointment.cancel_reason = ''
        appointment.save()

        # Notify patient
        Notification.objects.create(
            user=appointment.patient,
            message=(
                f"Your cancellation request for the appointment with "
                f"Dr. {appointment.doctor.user.get_full_name()} "
                f"on {appointment.appointment_date} has been rejected. "
                f"Your appointment remains active."
            ),
        )

        return response.Response(AppointmentSerializer(appointment).data)


class NotificationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
        return response.Response(NotificationSerializer(notifications, many=True).data)


class MarkNotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            notif = Notification.objects.get(pk=pk, user=request.user)
        except Notification.DoesNotExist:
            return response.Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        notif.is_read = True
        notif.save()
        return response.Response(NotificationSerializer(notif).data)


class MarkAllNotificationsReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return response.Response({'detail': 'All notifications marked as read.'})


class SpecializationListCreateView(APIView):
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        return response.Response(SpecializationSerializer(Specialization.objects.order_by('name'), many=True).data)

    def post(self, request):
        serializer = SpecializationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        spec = serializer.save()
        return response.Response(SpecializationSerializer(spec).data, status=status.HTTP_201_CREATED)


class MarkAppointmentDoneView(APIView):
    permission_classes = [IsDoctorRole]

    def post(self, request, pk):
        doctor = getattr(request.user, 'doctor_profile', None)
        if not doctor:
            return response.Response({'detail': 'Doctor profile not found.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            appointment = Appointment.objects.select_related(
                'patient', 'doctor__user'
            ).get(pk=pk, doctor=doctor)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found.'}, status=status.HTTP_404_NOT_FOUND)

        if appointment.status not in (Appointment.Status.PENDING, Appointment.Status.CONFIRMED):
            return response.Response(
                {'detail': 'Only pending or confirmed appointments can be marked as done.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        checkup_result = request.data.get('checkup_result', '').strip()
        if not checkup_result:
            return response.Response({'detail': 'Checkup result is required.'}, status=status.HTTP_400_BAD_REQUEST)

        appointment.status = Appointment.Status.COMPLETED
        appointment.checkup_result = checkup_result
        appointment.save()

        # Notify patient
        Notification.objects.create(
            user=appointment.patient,
            message=(
                f"Your appointment with Dr. {doctor.user.get_full_name()} "
                f"on {appointment.appointment_date} has been completed. "
                f"Doctor's note: {checkup_result}"
            ),
        )

        return response.Response(AppointmentSerializer(appointment).data)


# Doctor: view own appointments
class DoctorAppointmentListView(APIView):
    permission_classes = [IsDoctorRole]

    def get(self, request):
        doctor = getattr(request.user, 'doctor_profile', None)
        if not doctor:
            return response.Response([], status=status.HTTP_200_OK)
        appointments = Appointment.objects.select_related(
            'patient', 'doctor__user', 'schedule', 'handled_by__user'
        ).filter(doctor=doctor).order_by('-appointment_date', '-appointment_time')
        return response.Response(AppointmentSerializer(appointments, many=True).data)


# Staff: view appointments of assigned doctor
class StaffAppointmentListView(APIView):
    permission_classes = [IsStaffRole]

    def get(self, request):
        staff = getattr(request.user, 'staff_profile', None)
        if not staff or not staff.assigned_doctor:
            return response.Response([], status=status.HTTP_200_OK)
        appointments = Appointment.objects.select_related(
            'patient', 'doctor__user', 'schedule', 'handled_by__user'
        ).filter(doctor=staff.assigned_doctor).order_by('-appointment_date', '-appointment_time')
        return response.Response(AppointmentSerializer(appointments, many=True).data)


class StaffConfirmAppointmentView(APIView):
    permission_classes = [IsStaffRole]

    def post(self, request, pk):
        staff = getattr(request.user, 'staff_profile', None)
        if not staff or not staff.assigned_doctor:
            return response.Response({'detail': 'No assigned doctor.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            appointment = Appointment.objects.select_related(
                'patient', 'doctor__user'
            ).get(pk=pk, doctor=staff.assigned_doctor, status=Appointment.Status.COMPLETED)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found or not completed yet.'}, status=status.HTTP_404_NOT_FOUND)

        appointment.status = Appointment.Status.CONFIRMED
        appointment.handled_by = staff
        appointment.save()

        Notification.objects.create(
            user=appointment.patient,
            message=(
                f"Your appointment with Dr. {appointment.doctor.user.get_full_name()} "
                f"on {appointment.appointment_date} has been reviewed and confirmed by the clinic staff. "
                f"No laboratory requirement needed."
            ),
        )
        return response.Response(AppointmentSerializer(appointment).data)


class StaffRequireLaboratoryView(APIView):
    permission_classes = [IsStaffRole]

    def post(self, request, pk):
        staff = getattr(request.user, 'staff_profile', None)
        if not staff or not staff.assigned_doctor:
            return response.Response({'detail': 'No assigned doctor.'}, status=status.HTTP_400_BAD_REQUEST)

        lab_requirement = request.data.get('laboratory_requirement', '').strip()
        if not lab_requirement:
            return response.Response({'detail': 'Laboratory requirement description is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            appointment = Appointment.objects.select_related(
                'patient', 'doctor__user', 'doctor__specialization'
            ).get(pk=pk, doctor=staff.assigned_doctor, status=Appointment.Status.COMPLETED)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found or not completed yet.'}, status=status.HTTP_404_NOT_FOUND)

        appointment.needs_laboratory = True
        appointment.laboratory_requirement = lab_requirement
        appointment.handled_by = staff
        appointment.status = Appointment.Status.CONFIRMED
        appointment.save()

        patient = appointment.patient
        doctor = appointment.doctor
        specialization = doctor.specialization

        # Notify patient
        Notification.objects.create(
            user=patient,
            message=(
                f"Dr. {doctor.user.get_full_name()} requires you to complete a laboratory test "
                f"before your next appointment. Required: {lab_requirement}. "
                f"You cannot book with doctors of the same specialization until this is resolved."
            ),
        )

        # Notify all doctors with the same specialization
        if specialization:
            same_spec_doctors = Doctor.objects.filter(
                specialization=specialization
            ).select_related('user').exclude(pk=doctor.pk)
            for other_doctor in same_spec_doctors:
                Notification.objects.create(
                    user=other_doctor.user,
                    message=(
                        f"Patient {patient.get_full_name()} has a pending laboratory requirement "
                        f"({lab_requirement}) from Dr. {doctor.user.get_full_name()}. "
                        f"This patient cannot book with {specialization.name} doctors until completed."
                    ),
                )

        return response.Response(AppointmentSerializer(appointment).data)


# Admin: view all appointments
class AdminAppointmentListView(APIView):
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        appointments = Appointment.objects.select_related(
            'patient', 'doctor__user', 'schedule', 'handled_by__user'
        ).order_by('-appointment_date', '-appointment_time')
        return response.Response(AppointmentSerializer(appointments, many=True).data)


class AdminAppointmentDetailView(APIView):
    permission_classes = [IsAdminUserRole]

    def delete(self, request, pk):
        try:
            appointment = Appointment.objects.select_related('schedule', 'patient', 'doctor__user').get(pk=pk)
        except Appointment.DoesNotExist:
            return response.Response({'detail': 'Appointment not found.'}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            schedule = appointment.schedule
            appointment.delete()
            if schedule:
                schedule.is_available = True
                schedule.save(update_fields=['is_available'])

        return response.Response(status=status.HTTP_204_NO_CONTENT)


class AdminPatientListView(APIView):
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        patients = User.objects.filter(role=User.Role.PATIENT).order_by('last_name', 'first_name')
        return response.Response(UserSerializer(patients, many=True).data)


# Doctor: manage own schedules
class DoctorScheduleListCreateView(APIView):
    permission_classes = [IsDoctorRole]

    def get(self, request):
        doctor = getattr(request.user, 'doctor_profile', None)
        if not doctor:
            return response.Response([], status=status.HTTP_200_OK)
        cleanup_expired_schedules(doctor)
        schedules = Schedule.objects.filter(doctor=doctor).order_by('date', 'start_time')
        return response.Response(ScheduleSerializer(schedules, many=True).data)

    def post(self, request):
        doctor = getattr(request.user, 'doctor_profile', None)
        if not doctor:
            return response.Response({'detail': 'Doctor profile not found.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = serializer.save(doctor=doctor)
        return response.Response(ScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


class DoctorScheduleDetailView(APIView):
    permission_classes = [IsDoctorRole]

    def get_object(self, pk, doctor):
        return Schedule.objects.get(pk=pk, doctor=doctor)

    def put(self, request, pk):
        doctor = getattr(request.user, 'doctor_profile', None)
        try:
            schedule = self.get_object(pk, doctor)
        except Schedule.DoesNotExist:
            return response.Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ScheduleWriteSerializer(schedule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(ScheduleSerializer(Schedule.objects.select_related('doctor__user').get(pk=pk)).data)

    def delete(self, request, pk):
        doctor = getattr(request.user, 'doctor_profile', None)
        try:
            schedule = self.get_object(pk, doctor)
        except Schedule.DoesNotExist:
            return response.Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        schedule.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)


# Staff: view assigned doctor's schedules
class StaffDoctorScheduleView(APIView):
    permission_classes = [IsStaffRole]

    def get(self, request):
        staff = getattr(request.user, 'staff_profile', None)
        if not staff or not staff.assigned_doctor:
            return response.Response([], status=status.HTTP_200_OK)
        cleanup_expired_schedules(staff.assigned_doctor)
        schedules = Schedule.objects.filter(doctor=staff.assigned_doctor).order_by('date', 'start_time')
        return response.Response(ScheduleSerializer(schedules, many=True).data)


# Admin: create schedules for any doctor, view all
class AdminScheduleListCreateView(APIView):
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        cleanup_expired_schedules()
        schedules = Schedule.objects.select_related('doctor__user').order_by('date', 'start_time')
        return response.Response(ScheduleSerializer(schedules, many=True).data)

    def post(self, request):
        serializer = AdminScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = serializer.save()
        return response.Response(
            ScheduleSerializer(Schedule.objects.select_related('doctor__user').get(pk=schedule.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AdminScheduleDetailView(APIView):
    permission_classes = [IsAdminUserRole]

    def put(self, request, pk):
        try:
            schedule = Schedule.objects.get(pk=pk)
        except Schedule.DoesNotExist:
            return response.Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = ScheduleWriteSerializer(schedule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(ScheduleSerializer(Schedule.objects.select_related('doctor__user').get(pk=pk)).data)

    def delete(self, request, pk):
        try:
            schedule = Schedule.objects.get(pk=pk)
        except Schedule.DoesNotExist:
            return response.Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        schedule.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class AdminDoctorListCreateView(APIView):
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        doctors = Doctor.objects.select_related("user").annotate(staff_count=Count("staff_members")).order_by("user__last_name", "user__first_name")
        return response.Response(DoctorSerializer(doctors, many=True).data)

    def post(self, request):
        serializer = AdminDoctorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data["password"]
        doctor = serializer.save()
        email_warning = None
        try:
            send_account_credentials_email(
                recipient_name=doctor.user.get_full_name(),
                recipient_email=doctor.user.email,
                role_label="Doctor",
                password=password,
            )
        except Exception as exc:
            email_warning = f"Doctor account created, but email could not be sent: {format_email_delivery_hint(exc)}"
        return response.Response(
            {
                **DoctorSerializer(
                    Doctor.objects.select_related("user").annotate(staff_count=Count("staff_members")).get(pk=doctor.pk)
                ).data,
                **({"email_warning": email_warning} if email_warning else {}),
            },
            status=status.HTTP_201_CREATED,
        )


class AdminDoctorDetailView(APIView):
    permission_classes = [IsAdminUserRole]

    def get_object(self, pk):
        return Doctor.objects.select_related("user").annotate(staff_count=Count("staff_members")).get(pk=pk)

    def put(self, request, pk):
        doctor = self.get_object(pk)
        serializer = AdminDoctorUpdateSerializer(data=request.data, context={"doctor": doctor})
        serializer.is_valid(raise_exception=True)
        updated_doctor = serializer.update(doctor, serializer.validated_data)
        refreshed = Doctor.objects.select_related("user").annotate(staff_count=Count("staff_members")).get(pk=updated_doctor.pk)
        return response.Response(DoctorSerializer(refreshed).data)

    def delete(self, request, pk):
        doctor = self.get_object(pk)
        doctor.user.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class AdminDoctorAssignStaffView(APIView):
    permission_classes = [IsAdminUserRole]

    def post(self, request, pk):
        try:
            doctor = Doctor.objects.get(pk=pk)
        except Doctor.DoesNotExist:
            return response.Response({"detail": "Doctor not found."}, status=status.HTTP_404_NOT_FOUND)
        staff_id = request.data.get("staff_id")
        if not staff_id:
            return response.Response({"detail": "staff_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = Staff.objects.select_related("user", "assigned_doctor__user").get(pk=staff_id)
        except Staff.DoesNotExist:
            return response.Response({"detail": "Staff not found."}, status=status.HTTP_404_NOT_FOUND)
        staff.assigned_doctor = doctor
        staff.save()
        return response.Response(StaffSerializer(staff).data)


class AdminStaffListCreateView(APIView):
    permission_classes = [IsAdminUserRole]

    def get(self, request):
        staff_members = Staff.objects.select_related("user", "assigned_doctor__user").order_by("user__last_name", "user__first_name")
        return response.Response(StaffSerializer(staff_members, many=True).data)

    def post(self, request):
        serializer = AdminStaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data["password"]
        staff = serializer.save()
        email_warning = None
        try:
            send_account_credentials_email(
                recipient_name=staff.user.get_full_name(),
                recipient_email=staff.user.email,
                role_label="Staff",
                password=password,
            )
        except Exception as exc:
            email_warning = f"Staff account created, but email could not be sent: {format_email_delivery_hint(exc)}"
        return response.Response(
            {
                **StaffSerializer(Staff.objects.select_related("user", "assigned_doctor__user").get(pk=staff.pk)).data,
                **({"email_warning": email_warning} if email_warning else {}),
            },
            status=status.HTTP_201_CREATED,
        )


class AdminStaffDetailView(APIView):
    permission_classes = [IsAdminUserRole]

    def get_object(self, pk):
        return Staff.objects.select_related("user", "assigned_doctor__user").get(pk=pk)

    def put(self, request, pk):
        staff = self.get_object(pk)
        serializer = AdminStaffUpdateSerializer(data=request.data, context={"staff": staff})
        serializer.is_valid(raise_exception=True)
        updated_staff = serializer.update(staff, serializer.validated_data)
        refreshed = Staff.objects.select_related("user", "assigned_doctor__user").get(pk=updated_staff.pk)
        return response.Response(StaffSerializer(refreshed).data)

    def delete(self, request, pk):
        staff = self.get_object(pk)
        staff.user.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)
