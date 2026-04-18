from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0006_appointment_lab_result_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedule',
            name='appointment_pay',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
