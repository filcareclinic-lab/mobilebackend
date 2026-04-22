from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0008_signupverification'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='lab_result',
            field=models.CharField(choices=[('with lab result', 'With lab result'), ('none', 'None')], default='none', max_length=20),
        ),
    ]
