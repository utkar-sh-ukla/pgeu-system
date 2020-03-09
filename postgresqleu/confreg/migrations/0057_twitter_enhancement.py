# -*- coding: utf-8 -*-
# Generated by Django 1.11.18 on 2019-08-21 16:24
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone
import postgresqleu.util.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('confreg', '0056_track_speakerreg'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='conferencetweetqueue',
            options={'ordering': ['sent', 'datetime'], 'verbose_name': 'Conference Tweet', 'verbose_name_plural': 'Conference Tweets'},
        ),
        migrations.AddField(
            model_name='conferencetweetqueue',
            name='approved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='conferencetweetqueue',
            name='author',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='conferencetweetqueue',
            name='image',
            field=postgresqleu.util.fields.ImageBinaryField(blank=True, max_length=1000000, null=True),
        ),
        migrations.AddField(
            model_name='conferencetweetqueue',
            name='sent',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='conferencetweetqueue',
            name='datetime',
            field=models.DateTimeField(default=timezone.now, help_text='Date and time to send tweet', verbose_name='Date and time'),
        ),
    ]
