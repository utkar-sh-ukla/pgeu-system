# -*- coding: utf-8 -*-
# Generated by Django 1.11.10 on 2018-12-19 21:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('confsponsor', '0011_maxsponsors'),
    ]

    operations = [
        migrations.AddField(
            model_name='sponsor',
            name='extra_cc',
            field=models.EmailField(blank=True, max_length=254, verbose_name='Extra information address'),
        ),
    ]
