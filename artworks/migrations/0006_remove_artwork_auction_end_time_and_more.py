# Generated by Django 5.2.1 on 2025-06-09 21:05

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('artworks', '0005_userprofile'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name='artwork',
            name='auction_end_time',
        ),
        migrations.AddField(
            model_name='artwork',
            name='auction_scheduled_end_time',
            field=models.DateTimeField(blank=True, help_text='Scheduled date and time for the auction to end (can be extended by new bids).', null=True),
        ),
        migrations.AddField(
            model_name='artwork',
            name='auction_signup_deadline',
            field=models.DateTimeField(blank=True, editable=False, help_text='Calculated: Time by which users must register.', null=True),
        ),
        migrations.AddField(
            model_name='artwork',
            name='auction_signup_offset_minutes',
            field=models.PositiveIntegerField(default=30, help_text='Users must sign up at least this many minutes before the auction_start_time. Registration window closes at (auction_start_time - offset).'),
        ),
        migrations.AddField(
            model_name='artwork',
            name='auction_status',
            field=models.CharField(choices=[('draft', 'Draft'), ('pending_signup_window', 'Pending Sign-up Window'), ('signup_open', 'Sign-up Open'), ('awaiting_attendee_approval', 'Awaiting Attendee Approval'), ('ready_to_start', 'Ready to Start'), ('live', 'Live'), ('ended_pending_payment', 'Ended - Pending Payment'), ('completed', 'Completed'), ('cancelled_by_owner', 'Cancelled by Owner'), ('failed_no_bids', 'Failed - No Bids/No Winner'), ('failed_payment', 'Failed - Payment Issue')], default='draft', max_length=30),
        ),
        migrations.AddField(
            model_name='artwork',
            name='auction_winner',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='won_auctions', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='artwork',
            name='auction_winning_price',
            field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='artwork',
            name='last_bid_time',
            field=models.DateTimeField(blank=True, editable=False, help_text='Timestamp of the last valid bid placed.', null=True),
        ),
        migrations.AlterField(
            model_name='artwork',
            name='auction_current_highest_bid',
            field=models.DecimalField(blank=True, decimal_places=2, editable=False, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='artwork',
            name='auction_current_highest_bidder',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='current_bids_on', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='artwork',
            name='auction_minimum_bid',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Minimum starting bid.', max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='artwork',
            name='auction_start_time',
            field=models.DateTimeField(blank=True, help_text='Date and time when the auction bidding begins.', null=True),
        ),
        migrations.CreateModel(
            name='Bid',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('timestamp', models.DateTimeField(default=django.utils.timezone.now)),
                ('artwork', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bids', to='artworks.artwork')),
                ('bidder', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='placed_bids', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Bid',
                'verbose_name_plural': 'Bids',
                'ordering': ['-artwork', '-amount', '-timestamp'],
            },
        ),
        migrations.CreateModel(
            name='AuctionRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('registered_at', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(choices=[('pending', 'Pending Approval'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10)),
                ('owner_reviewed_at', models.DateTimeField(blank=True, help_text='Timestamp when the owner approved/rejected.', null=True)),
                ('artwork', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auction_registrations', to='artworks.artwork')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auction_signups', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Auction Registration',
                'verbose_name_plural': 'Auction Registrations',
                'ordering': ['-registered_at'],
                'unique_together': {('artwork', 'user')},
            },
        ),
    ]
