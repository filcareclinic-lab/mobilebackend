from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0003_appointment_checkup_result'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='needs_laboratory',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='appointment',
            name='laboratory_requirement',
            field=models.TextField(blank=True, default=''),
        ),
    ]
