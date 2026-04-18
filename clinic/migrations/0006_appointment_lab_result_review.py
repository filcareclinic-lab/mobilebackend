from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0005_appointment_lab_result'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='lab_result_description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='appointment',
            name='lab_result_status',
            field=models.CharField(
                blank=True, default='',
                choices=[('pending_review', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='appointment',
            name='lab_result_reject_reason',
            field=models.TextField(blank=True, default=''),
        ),
    ]
