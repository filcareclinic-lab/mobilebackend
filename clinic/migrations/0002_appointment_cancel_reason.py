from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='cancel_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='appointment',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('confirmed', 'Confirmed'),
                    ('completed', 'Completed'),
                    ('cancelled', 'Cancelled'),
                    ('cancel_requested', 'Cancel Requested'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
