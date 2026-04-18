from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Appointment, Doctor, Notification, Schedule, Specialization, Staff, User


class SpecializationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Specialization
        fields = ('id', 'name')

    def validate_name(self, value):
        qs = Specialization.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A specialization with this name already exists.')
        return value


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "full_name",
            "email",
            "role",
            "created_at",
        )
        read_only_fields = ("id", "created_at", "full_name")

    def get_full_name(self, obj):
        return obj.get_full_name()


class DoctorSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    staff_count = serializers.IntegerField(read_only=True)
    specialization = serializers.SerializerMethodField()
    specialization_id = serializers.IntegerField(source='specialization.id', read_only=True, allow_null=True)

    class Meta:
        model = Doctor
        fields = ('id', 'user', 'specialization', 'specialization_id', 'contact_number', 'staff_count')

    def get_specialization(self, obj):
        return obj.specialization.name if obj.specialization else ''


class StaffSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    assigned_doctor = DoctorSerializer(read_only=True)

    class Meta:
        model = Staff
        fields = ("id", "user", "assigned_doctor", "position", "contact_number")


class ScheduleSerializer(serializers.ModelSerializer):
    doctor = DoctorSerializer(read_only=True)

    class Meta:
        model = Schedule
        fields = ("id", "doctor", "date", "start_time", "end_time", "appointment_pay", "is_available")


class ScheduleWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = ("date", "start_time", "end_time", "appointment_pay", "is_available")

    def validate(self, attrs):
        if attrs.get("start_time") and attrs.get("end_time"):
            if attrs["start_time"] >= attrs["end_time"]:
                raise serializers.ValidationError("End time must be after start time.")
        if attrs.get("appointment_pay") is not None and attrs["appointment_pay"] <= 0:
            raise serializers.ValidationError({"appointment_pay": "Appointment pay must be greater than zero."})
        return attrs


class AdminScheduleWriteSerializer(serializers.Serializer):
    doctor_id = serializers.IntegerField()
    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    appointment_pay = serializers.DecimalField(max_digits=10, decimal_places=2)
    is_available = serializers.BooleanField(default=True)

    def validate_doctor_id(self, value):
        if not Doctor.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Doctor not found.")
        return value

    def validate(self, attrs):
        if attrs["start_time"] >= attrs["end_time"]:
            raise serializers.ValidationError("End time must be after start time.")
        if attrs["appointment_pay"] <= 0:
            raise serializers.ValidationError({"appointment_pay": "Appointment pay must be greater than zero."})
        return attrs

    def create(self, validated_data):
        return Schedule.objects.create(
            doctor_id=validated_data["doctor_id"],
            date=validated_data["date"],
            start_time=validated_data["start_time"],
            end_time=validated_data["end_time"],
            appointment_pay=validated_data["appointment_pay"],
            is_available=validated_data["is_available"],
        )


class PatientBookingSerializer(serializers.Serializer):
    schedule_id = serializers.IntegerField()
    reason = serializers.CharField()

    def validate_schedule_id(self, value):
        try:
            schedule = Schedule.objects.select_related('doctor__specialization').get(pk=value, is_available=True)
        except Schedule.DoesNotExist:
            raise serializers.ValidationError('Schedule not found or not available.')
        from django.utils import timezone
        if schedule.date < timezone.localdate():
            raise serializers.ValidationError('Cannot book a past schedule.')
        # Block if patient has a pending lab requirement for same specialization
        patient = self.context['request'].user
        spec = schedule.doctor.specialization
        if spec:
            blocked = Appointment.objects.filter(
                patient=patient,
                doctor__specialization=spec,
            ).exclude(status=Appointment.Status.CANCELLED).filter(
                Q(needs_laboratory=True) |
                Q(lab_result_status='pending_review') |
                Q(lab_result_status='rejected')
            ).exists()
            if blocked:
                raise serializers.ValidationError(
                    f'You have an unresolved laboratory requirement for {spec.name} doctors. '
                    f'Please complete or resubmit your laboratory test before booking again.'
                )
        return value

    @transaction.atomic
    def create(self, validated_data):
        patient = self.context['request'].user
        schedule = Schedule.objects.select_related('doctor__user').prefetch_related(
            'doctor__staff_members__user'
        ).get(pk=validated_data['schedule_id'])
        doctor = schedule.doctor

        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            schedule=schedule,
            appointment_date=schedule.date,
            appointment_time=schedule.start_time,
            reason=validated_data['reason'],
            status=Appointment.Status.PENDING,
        )
        schedule.is_available = False
        schedule.save()

        # Notify the doctor
        Notification.objects.create(
            user=doctor.user,
            message=(
                f"New appointment booked by {patient.get_full_name()} "
                f"on {schedule.date} at {schedule.start_time.strftime('%I:%M %p')}. "
                f"Reason: {validated_data['reason']}"
            ),
        )

        # Notify assigned staff of the doctor
        for staff in doctor.staff_members.select_related('user').all():
            Notification.objects.create(
                user=staff.user,
                message=(
                    f"New appointment for Dr. {doctor.user.get_full_name()} "
                    f"booked by {patient.get_full_name()} "
                    f"on {schedule.date} at {schedule.start_time.strftime('%I:%M %p')}."
                ),
            )

        # Notify all admins
        for admin in User.objects.filter(role=User.Role.ADMIN):
            Notification.objects.create(
                user=admin,
                message=(
                    f"{patient.get_full_name()} booked an appointment with "
                    f"Dr. {doctor.user.get_full_name()} "
                    f"on {schedule.date} at {schedule.start_time.strftime('%I:%M %p')}."
                ),
            )

        # Confirm to the patient
        Notification.objects.create(
            user=patient,
            message=(
                f"Your appointment with Dr. {doctor.user.get_full_name()} "
                f"on {schedule.date} at {schedule.start_time.strftime('%I:%M %p')} "
                f"has been booked. Status: Pending."
            ),
        )

        return appointment


class AppointmentSerializer(serializers.ModelSerializer):
    patient = UserSerializer(read_only=True)
    doctor = DoctorSerializer(read_only=True)
    schedule = ScheduleSerializer(read_only=True)
    handled_by = StaffSerializer(read_only=True)

    class Meta:
        model = Appointment
        fields = (
            "id",
            "patient",
            "doctor",
            "schedule",
            "handled_by",
            "appointment_date",
            "appointment_time",
            "status",
            "reason",
            "cancel_reason",
            "checkup_result",
            "needs_laboratory",
            "laboratory_requirement",
            "lab_result_image",
            "lab_result_description",
            "lab_result_submitted",
            "lab_result_status",
            "lab_result_reject_reason",
            "created_at",
        )


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ("id", "message", "is_read", "created_at")


class PatientSignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = (
            "first_name",
            "middle_name",
            "last_name",
            "email",
            "password",
            "confirm_password",
        )

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")
        user = User.objects.create_user(
            role=User.Role.PATIENT,
            password=password,
            **validated_data,
        )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email", "").lower()
        password = attrs.get("password")
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )
        if not user:
            raise serializers.ValidationError("Invalid email or password.")
        attrs["user"] = user
        return attrs


class ClinicTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.EMAIL_FIELD

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class AdminDoctorCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    specialization_id = serializers.IntegerField(allow_null=True, required=False)
    contact_number = serializers.CharField(max_length=20)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_specialization_id(self, value):
        if value is not None and not Specialization.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Specialization not found.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        user = User.objects.create_user(
            first_name=validated_data["first_name"],
            middle_name=validated_data.get("middle_name", ""),
            last_name=validated_data["last_name"],
            email=validated_data["email"],
            password=validated_data["password"],
            role=User.Role.DOCTOR,
        )
        doctor = Doctor.objects.create(
            user=user,
            specialization_id=validated_data.get("specialization_id"),
            contact_number=validated_data["contact_number"],
        )
        return doctor


class AdminDoctorUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    specialization_id = serializers.IntegerField(allow_null=True, required=False)
    contact_number = serializers.CharField(max_length=20)

    def validate_email(self, value):
        doctor = self.context["doctor"]
        if User.objects.filter(email__iexact=value).exclude(pk=doctor.user_id).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_specialization_id(self, value):
        if value is not None and not Specialization.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Specialization not found.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        user = instance.user
        user.first_name = validated_data["first_name"]
        user.middle_name = validated_data.get("middle_name", "")
        user.last_name = validated_data["last_name"]
        user.email = validated_data["email"]
        user.save()

        instance.specialization_id = validated_data.get("specialization_id")
        instance.contact_number = validated_data["contact_number"]
        instance.save()
        return instance


class AdminStaffCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    assigned_doctor_id = serializers.IntegerField(required=False, allow_null=True)
    position = serializers.CharField(max_length=255)
    contact_number = serializers.CharField(max_length=20)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_assigned_doctor_id(self, value):
        if value is None:
            return value
        if not Doctor.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Assigned doctor was not found.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        doctor_id = validated_data.pop("assigned_doctor_id", None)
        user = User.objects.create_user(
            first_name=validated_data["first_name"],
            middle_name=validated_data.get("middle_name", ""),
            last_name=validated_data["last_name"],
            email=validated_data["email"],
            password=validated_data["password"],
            role=User.Role.STAFF,
        )
        staff = Staff.objects.create(
            user=user,
            assigned_doctor_id=doctor_id,
            position=validated_data["position"],
            contact_number=validated_data["contact_number"],
        )
        return staff


class AdminStaffUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    assigned_doctor_id = serializers.IntegerField(required=False, allow_null=True)
    position = serializers.CharField(max_length=255)
    contact_number = serializers.CharField(max_length=20)

    def validate_email(self, value):
        staff = self.context["staff"]
        if User.objects.filter(email__iexact=value).exclude(pk=staff.user_id).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_assigned_doctor_id(self, value):
        if value is None:
            return value
        if not Doctor.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Assigned doctor was not found.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        user = instance.user
        user.first_name = validated_data["first_name"]
        user.middle_name = validated_data.get("middle_name", "")
        user.last_name = validated_data["last_name"]
        user.email = validated_data["email"]
        user.save()

        instance.assigned_doctor_id = validated_data.get("assigned_doctor_id")
        instance.position = validated_data["position"]
        instance.contact_number = validated_data["contact_number"]
        instance.save()
        return instance
