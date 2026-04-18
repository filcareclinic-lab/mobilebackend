from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0002_appointment_cancel_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='checkup_result',
            field=models.TextField(blank=True, default=''),
        ),
    ]
