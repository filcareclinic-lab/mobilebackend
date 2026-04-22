from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("clinic", "0007_schedule_appointment_pay"),
    ]

    operations = [
        migrations.CreateModel(
            name="SignupVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("first_name", models.CharField(max_length=150)),
                ("middle_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(max_length=150)),
                ("password_hash", models.CharField(max_length=255)),
                ("code_hash", models.CharField(max_length=255)),
                ("code_sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
            ],
        ),
    ]
