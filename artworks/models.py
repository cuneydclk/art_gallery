# artworks/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta
from decimal import Decimal 

class Artwork(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=255, unique=True, blank=True, help_text="Unique URL-friendly identifier. Leave blank to auto-generate from title.")
    description = models.TextField()
    image_placeholder_url = models.URLField(max_length=500, blank=True, null=True, help_text="URL to a placeholder image for now.")
    current_owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_artworks")
    is_for_sale_direct = models.BooleanField(default=False)
    direct_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    AUCTION_STATUS_CHOICES = [
        ('not_configured', 'Not Configured'),
        ('draft', 'Draft'), # Owner is configuring, might be incomplete.
        ('configured', 'Configured / Upcoming'), # All settings present, awaiting time-based transition.
        ('signup_open', 'Sign-up Open'),
        ('awaiting_start', 'Awaiting Start'), # Sign-up closed, auction start time not yet reached.
        ('live', 'Live Auction'),
    ]
    is_for_auction = models.BooleanField(default=False)
    auction_start_time = models.DateTimeField(null=True, blank=True)
    auction_scheduled_end_time = models.DateTimeField(null=True, blank=True)
    auction_minimum_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    auction_signup_offset_minutes = models.PositiveIntegerField(default=30)
    auction_signup_deadline = models.DateTimeField(null=True, blank=True, editable=False) # Calculated
    auction_status = models.CharField(max_length=30, choices=AUCTION_STATUS_CHOICES, default='not_configured')

    auction_current_highest_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, editable=False)
    auction_current_highest_bidder = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="active_bids_on", editable=False)
    last_bid_time = models.DateTimeField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            original_slug = self.slug
            counter = 1
            while Artwork.objects.filter(slug=self.slug).exclude(pk=self.pk if self.pk else None).exists():
                self.slug = f'{original_slug}-{counter}'
                counter += 1

        # Determine original state if updating an existing artwork
        original_is_for_auction = False
        original_auction_status = 'not_configured' # Default for new or un-auctioned items
        if self.pk: # If this is an update to an existing object
            try:
                # Fetch only the fields needed to avoid recursion if other fields trigger signals/saves
                original_data = Artwork.objects.only('is_for_auction', 'auction_status').get(pk=self.pk)
                original_is_for_auction = original_data.is_for_auction
                original_auction_status = original_data.auction_status
            except Artwork.DoesNotExist:
                pass # Should not happen if self.pk exists, but good practice

        if self.is_for_auction:
            # === Auction is ON ===
            # 1. Calculate signup deadline (must be done before status decisions)
            if self.auction_start_time and self.auction_signup_offset_minutes is not None:
                self.auction_signup_deadline = self.auction_start_time - timedelta(minutes=self.auction_signup_offset_minutes)
            else:
                self.auction_signup_deadline = None # Essential times for deadline calc are missing

            # 2. Determine initial/base auction_status
            #    - If it's being newly enabled OR was previously not properly configured ('not_configured', 'draft')
            #    - AND all required auction times are now set.
            #    Then, set to 'configured'. This is the clean state from which get_effective_auction_status_and_save will transition.
            if (not original_is_for_auction or original_auction_status in ['not_configured', 'draft']) and \
               self.auction_start_time and self.auction_scheduled_end_time and self.auction_minimum_bid is not None:
                print(f"[Artwork Save DEBUG] '{self.title}': Setting auction_status to 'configured'. "
                      f"Was: original_is_for_auction={original_is_for_auction}, original_status='{original_auction_status}'.")
                self.auction_status = 'configured'
            elif not (self.auction_start_time and self.auction_scheduled_end_time and self.auction_minimum_bid is not None):
                # If critical auction settings are missing, but is_for_auction is true,
                # set to 'draft' unless it's already in an active state.
                # Active states ('signup_open', 'awaiting_start', 'live') should not be regressed by this basic save.
                if self.auction_status not in ['signup_open', 'awaiting_start', 'live']:
                    print(f"[Artwork Save DEBUG] '{self.title}': Critical auction times/bid missing, setting to 'draft'. Current status: {self.auction_status}")
                    self.auction_status = 'draft'
            # If it's already in an active state ('signup_open', 'awaiting_start', 'live'),
            # this save() won't change the status. get_effective_auction_status_and_save() or finalize_auction() handles those.

            # 3. Ensure direct sale is off
            if self.is_for_sale_direct:
                self.is_for_sale_direct = False
                self.direct_sale_price = None
                print(f"[Artwork Save DEBUG] '{self.title}': Turned off direct sale because auction is active.")

        else:
            # === Auction is OFF ===
            if original_is_for_auction: # Only log and reset if it *was* for auction
                print(f"[Artwork Save DEBUG] '{self.title}': is_for_auction is now False. Resetting all auction fields.")

            self.auction_start_time = None
            self.auction_scheduled_end_time = None
            self.auction_minimum_bid = None
            # self.auction_signup_offset_minutes = self._meta.get_field('auction_signup_offset_minutes').default # Optionally reset to default
            self.auction_signup_deadline = None
            self.auction_status = 'not_configured' # Definitive state for no auction
            self.auction_current_highest_bid = None
            self.auction_current_highest_bidder = None
            self.last_bid_time = None

        super().save(*args, **kwargs) # Call the "real" save() method.

    class Meta:
        ordering = ['-created_at']

    # ... (Keep all @property methods: is_auction_signup_open_now, is_auction_live_now, etc.) ...
    # ... (Keep get_effective_auction_status_and_save, can_user_register_for_auction, get_user_auction_registration, finalize_auction, cancel_auction_by_owner) ...
    # Make sure these methods are correctly indented under the Artwork class.
    # For brevity, I'm omitting them here, but they should remain as they were in the previous complete solution.
    # I will provide the FULL Artwork class again in the next step if that's easier.

    @property
    def is_auction_signup_open_now(self):
        if not self.is_for_auction or self.auction_status != 'signup_open': return False
        now = timezone.now()
        return self.auction_signup_deadline and now < self.auction_signup_deadline

    @property
    def is_auction_live_now(self):
        return self.is_for_auction and self.auction_status == 'live'
    
    @property
    def time_until_auction_starts(self):
        if self.is_for_auction and self.auction_start_time and \
           self.auction_status in ['configured', 'signup_open', 'awaiting_start']:
            now = timezone.now()
            if self.auction_start_time > now: return self.auction_start_time - now
        return None

    @property
    def time_until_signup_deadline(self):
        if self.is_for_auction and self.auction_signup_deadline and self.auction_status == 'signup_open':
            now = timezone.now()
            if self.auction_signup_deadline > now: return self.auction_signup_deadline - now
        return None
    
    def get_effective_auction_status_and_save(self):
        if not self.is_for_auction:
            if self.auction_status != 'not_configured':
                self.auction_status = 'not_configured'
                super(Artwork, self).save(update_fields=['auction_status']) 
            return self.auction_status

        now = timezone.now()
        original_status = str(self.auction_status) # Make a copy for comparison
        changed_fields = [] 

        expected_deadline = None
        if self.auction_start_time and self.auction_signup_offset_minutes is not None:
            expected_deadline = self.auction_start_time - timedelta(minutes=self.auction_signup_offset_minutes)
        
        if self.auction_signup_deadline != expected_deadline:
            self.auction_signup_deadline = expected_deadline
            if 'auction_signup_deadline' not in changed_fields: changed_fields.append('auction_signup_deadline')

        current_status_before_change = str(self.auction_status) # For logging

        if self.auction_start_time and self.auction_signup_deadline:
            new_status = current_status_before_change

            if current_status_before_change == 'configured':
                if now < self.auction_signup_deadline: new_status = 'signup_open'
                elif now < self.auction_start_time: new_status = 'awaiting_start'
                else: new_status = 'live'
            elif current_status_before_change == 'signup_open':
                if now >= self.auction_signup_deadline:
                    if now < self.auction_start_time: new_status = 'awaiting_start'
                    else: new_status = 'live'
            elif current_status_before_change == 'awaiting_start':
                if now >= self.auction_start_time: new_status = 'live'
            
            if self.auction_status != new_status:
                self.auction_status = new_status
                if 'auction_status' not in changed_fields: changed_fields.append('auction_status')
        
        elif self.is_for_auction and self.auction_status not in ['not_configured', 'draft', 'live']:
             if self.auction_status in ['configured', 'signup_open', 'awaiting_start'] and \
                not (self.auction_start_time and self.auction_scheduled_end_time):
                 print(f"[EFFECTIVE_STATUS WARNING] Artwork '{self.title}': Status '{self.auction_status}' "
                       f"but critical times missing. Reverting to 'draft'.")
                 self.auction_status = 'draft'
                 if 'auction_status' not in changed_fields: changed_fields.append('auction_status')

        if changed_fields:
            # Important: Use super().save to avoid recursion if save() is overridden
            # and to specifically update only these fields.
            super(Artwork, self).save(update_fields=changed_fields) 
            print(f"[EFFECTIVE_STATUS] Artwork '{self.title}': Status changed from '{original_status}' to '{self.auction_status}'. Saved fields: {changed_fields}")
        
        return self.auction_status


    def can_user_register_for_auction(self, user):
        if not user or not user.is_authenticated: return False
        if self.auction_status != 'signup_open': return False
        if self.auction_signup_deadline and timezone.now() >= self.auction_signup_deadline: return False
        if self.current_owner == user: return False
        from artworks.models import AuctionRegistration # Local import for model methods
        if AuctionRegistration.objects.filter(artwork=self, user=user).exists(): return False 
        return True

    def get_user_auction_registration(self, user):
        if not user or not user.is_authenticated: return None
        from artworks.models import AuctionRegistration # Local import
        try: return AuctionRegistration.objects.get(artwork=self, user=user)
        except AuctionRegistration.DoesNotExist: return None
        
    def finalize_auction(self):
        print(f"[finalize_auction] Called for: '{self.title}', Current Status: {self.auction_status}")

        if self.auction_status != 'live':
            if not self.is_for_auction:
                 print(f"[finalize_auction] Auction '{self.title}' is already fully concluded (is_for_auction=False).")
                 return {'outcome': 'already_concluded'}
            if self.auction_scheduled_end_time and timezone.now() >= self.auction_scheduled_end_time:
                 print(f"[finalize_auction] Non-live auction '{self.title}' (status {self.auction_status}) passed scheduled end. Resetting.")
                 self.is_for_auction = False 
                 self.save() # Triggers full reset via main save()
                 return {'outcome': 'no_bids', 'message': 'Auction ended before going live or without bids.'}
            else:
                print(f"[finalize_auction] Auction '{self.title}' (status {self.auction_status}) is not live and has not passed scheduled end.")
                return {'outcome': 'not_live_or_not_ended', 'message': 'Auction not live or end time not reached.'}

        highest_bid = Bid.objects.filter(artwork=self).order_by('-amount', '-timestamp').first()
        outcome_data = {'outcome': 'no_bids', 'message': 'No bids met the criteria.'} 

        if highest_bid and self.auction_minimum_bid is not None and highest_bid.amount >= self.auction_minimum_bid:
            print(f"[finalize_auction] Winning bid for '{self.title}': {highest_bid.amount} by {highest_bid.bidder.username}")
            if self.current_owner and highest_bid.bidder:
                from artworks.models import Transaction # Local import
                try:
                    transaction_obj, created = Transaction.objects.get_or_create(
                        artwork=self, buyer=highest_bid.bidder, seller=self.current_owner, 
                        sale_type='auction_win',
                        defaults={'final_price': highest_bid.amount, 'status': 'pending_payment'}
                    )
                    if created: print(f"[finalize_auction] Transaction CREATED for '{self.title}'. ID: {transaction_obj.id}")
                    else: print(f"[finalize_auction] Transaction already EXISTED for '{self.title}'. ID: {transaction_obj.id}.")
                    
                    outcome_data = {
                        'outcome': 'winner_found', 'transaction': transaction_obj, 
                        'winner': highest_bid.bidder, 'price': highest_bid.amount,
                        'message': f'Winner: {highest_bid.bidder.username}, Price: ${highest_bid.amount:.2f}.'
                    }
                except Exception as e:
                    print(f"[finalize_auction] ERROR creating/getting transaction for '{self.title}': {e}")
                    outcome_data = {'outcome': 'transaction_error', 'message': f'Transaction error: {e}'}
            else:
                print(f"[finalize_auction] Critical error: Missing current_owner or winner for '{self.title}'.")
                outcome_data = {'outcome': 'transaction_error', 'message': 'Missing owner or winner details.'}
        else: 
            if highest_bid:
                 outcome_data['message'] = f'Highest bid ${highest_bid.amount} did not meet min ${self.auction_minimum_bid}.'
            else:
                 outcome_data['message'] = 'No bids placed.'

        self.is_for_auction = False 
        self.save() # This will reset status to 'not_configured' and clear transient fields.
        print(f"[finalize_auction] Artwork '{self.title}' auction attempt concluded. is_for_auction: {self.is_for_auction}, new status: {self.auction_status}.")
        return outcome_data

    def cancel_auction_by_owner(self):
        if self.is_for_auction and self.auction_status in ['configured', 'signup_open', 'awaiting_start', 'live']:
            print(f"Auction for '{self.title}' cancelled by owner. Was: {self.auction_status}")
            self.is_for_auction = False
            self.save() # Triggers full reset
            AuctionRegistration.objects.filter(artwork=self).update(status='cancelled_by_owner_auction_cancel')
            return True
        print(f"Cannot cancel auction for '{self.title}'. Status: {self.auction_status}, is_for_auction: {self.is_for_auction}")
        return False       

class Comment(models.Model):
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, help_text="Registered user who commented, if any.")
    guest_name = models.CharField(max_length=100, blank=True, null=True, help_text="Name of the guest commenter, if not a registered user.")
    text_content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now) 

    def __str__(self):
        if self.user:
            return f"Comment by {self.user.username} on {self.artwork.title}"
        elif self.guest_name:
            return f"Comment by {self.guest_name} (Guest) on {self.artwork.title}"
        else:
            return f"Anonymous comment on {self.artwork.title}"

    class Meta:
        ordering = ['created_at'] 

class Transaction(models.Model):
    TRANSACTION_STATUS_CHOICES = [
        ('pending_payment', 'Pending Payment'), 
        ('pending_approval', 'Pending Approval'), 
        ('approved', 'Approved'),               
        ('rejected', 'Rejected'),               
        ('cancelled', 'Cancelled'),             
    ]
    SALE_TYPE_CHOICES = [
        ('direct_buy', 'Direct Buy'),
        ('auction_win', 'Auction Win'),
    ]

    artwork = models.ForeignKey(Artwork, on_delete=models.PROTECT, related_name='transactions') 
    buyer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='purchases')
    seller = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sales_made') 

    sale_type = models.CharField(max_length=20, choices=SALE_TYPE_CHOICES)
    final_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    dekont_image = models.FileField(upload_to='dekonts/', null=True, blank=True) 
    
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS_CHOICES, default='pending_payment')
    
    initiated_at = models.DateTimeField(auto_now_add=True) 
    dekont_uploaded_at = models.DateTimeField(null=True, blank=True)
    admin_action_at = models.DateTimeField(null=True, blank=True)
    admin_remarks = models.TextField(blank=True, null=True, help_text="Reason for rejection, or other notes.")

    def __str__(self):
        return f"Transaction for {self.artwork.title} by {self.buyer.username if self.buyer else 'N/A'} - Status: {self.get_status_display()}"

    class Meta:
        ordering = ['-initiated_at']

class GallerySetting(models.Model): 
    bank_account_iban = models.CharField(max_length=100, default="TR33 0006 1005 1978 6457 8413 26")
    bank_account_holder = models.CharField(max_length=200, default="Art Gallery İzmir")
    contact_phone = models.CharField(max_length=20, default="+90 555 555 5555")
    payment_instructions = models.TextField(blank=True, help_text="Additional instructions for payment, e.g., reference number format.")

    def __str__(self):
        return "Gallery Payment Settings"

    def save(self, *args, **kwargs): 
        self.pk = 1
        super(GallerySetting, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs): 
        pass

    @classmethod
    def load(cls): 
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
    
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bank_iban = models.CharField(max_length=100, blank=True, null=True, help_text="Your IBAN for receiving payments.")
    bank_account_holder_name = models.CharField(max_length=200, blank=True, null=True, help_text="Full name as on bank account.")

    def __str__(self):
        return f"{self.user.username}'s Profile"

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    # Ensure profile exists before trying to save
    if hasattr(instance, 'profile'):
        instance.profile.save()
    else: # Fallback: if profile somehow doesn't exist, create it.
        UserProfile.objects.get_or_create(user=instance)


# --- NEW AUCTION RELATED MODELS ---

class AuctionRegistration(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='auction_registrations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_signups')
    registered_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    owner_reviewed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the owner approved/rejected.")

    class Meta:
        unique_together = ('artwork', 'user') # User can only register once per auction
        ordering = ['-registered_at']
        verbose_name = "Auction Registration"
        verbose_name_plural = "Auction Registrations"

    def __str__(self):
        return f"{self.user.username} for {self.artwork.title} auction ({self.get_status_display()})"

class Bid(models.Model):
    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='placed_bids')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-artwork', '-amount', '-timestamp'] # Show highest bids for an artwork first
        verbose_name = "Bid"
        verbose_name_plural = "Bids"

    def __str__(self):
        return f"Bid of {self.amount} by {self.bidder.username} on {self.artwork.title}"