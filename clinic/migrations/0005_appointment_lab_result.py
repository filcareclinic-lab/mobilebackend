from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0004_appointment_laboratory'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='lab_result_image',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='appointment',
            name='lab_result_submitted',
            field=models.BooleanField(default=False),
        ),
    ]
