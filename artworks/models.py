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
    
    # Direct Sale Status
    is_for_sale_direct = models.BooleanField(default=False)
    direct_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Auction Status & Settings
    AUCTION_STATUS_CHOICES = [
        ('draft', 'Draft'), # Not yet configured or explicitly set as draft
        ('pending_signup_window', 'Pending Sign-up Window'), # Configured, sign-up window not yet open
        ('signup_open', 'Sign-up Open'), # Actively accepting registrations
        ('awaiting_attendee_approval', 'Awaiting Attendee Approval'), # Sign-up window closed, owner reviews
        ('ready_to_start', 'Ready to Start'), # Approvals done, waiting for auction_start_time
        ('live', 'Live'), # Auction is currently active
        ('ended_pending_payment', 'Ended - Pending Payment'), # Winner declared, waiting for payment
        ('completed', 'Completed'), # Payment approved, artwork transferred
        ('cancelled_by_owner', 'Cancelled by Owner'), # Owner cancelled the auction
        ('failed_no_bids', 'Failed - No Bids/No Winner'), # Auction ended, no valid bids
        ('failed_payment', 'Failed - Payment Issue'), # Winner failed to pay
    ]
    is_for_auction = models.BooleanField(default=False)
    auction_start_time = models.DateTimeField(null=True, blank=True, help_text="Date and time when the auction bidding begins.")
    auction_scheduled_end_time = models.DateTimeField(null=True, blank=True, help_text="Scheduled date and time for the auction to end (can be extended by new bids).")
    auction_minimum_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Minimum starting bid.")
    
    auction_signup_offset_minutes = models.PositiveIntegerField(
        default=30, 
        help_text="Users must sign up at least this many minutes before the auction_start_time. Registration window closes at (auction_start_time - offset)."
    )
    auction_signup_deadline = models.DateTimeField(null=True, blank=True, editable=False, help_text="Calculated: Time by which users must register.")
    
    auction_status = models.CharField(max_length=30, choices=AUCTION_STATUS_CHOICES, default='draft')
    
    # Auction Runtime Fields (updated during live auction)
    auction_current_highest_bid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, editable=False) # Denormalized for quick display
    auction_current_highest_bidder = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="current_bids_on", editable=False) # Denormalized
    last_bid_time = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last valid bid placed.", editable=False)
    
    # Auction Outcome
    auction_winner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="won_auctions", editable=False)
    auction_winning_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            original_slug = self.slug
            counter = 1
            while Artwork.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f'{original_slug}-{counter}'
                counter += 1
        
        # Calculate signup deadline if auction times are set
        if self.is_for_auction and self.auction_start_time and self.auction_signup_offset_minutes is not None:
            self.auction_signup_deadline = self.auction_start_time - timedelta(minutes=self.auction_signup_offset_minutes)
        else:
            self.auction_signup_deadline = None

        # Basic logic: if not for auction, clear auction fields (can be expanded)
        if not self.is_for_auction:
            self.auction_start_time = None
            self.auction_scheduled_end_time = None
            self.auction_minimum_bid = None
            self.auction_status = 'draft' 
            # Clear other auction-related fields as necessary
            self.auction_current_highest_bid = None
            self.auction_current_highest_bidder = None
            self.last_bid_time = None
            self.auction_winner = None
            self.auction_winning_price = None
        
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_auction_signup_active(self):
        """Checks if the auction sign-up window is currently open."""
        if not self.is_for_auction or not self.auction_start_time or not self.auction_signup_deadline:
            return False
        now = timezone.now()
        # Check status first, then time for robustness
        if self.auction_status != 'signup_open':
            return False
        return now < self.auction_signup_deadline
    
    @property
    def is_auction_live_now(self):
        """Checks if the auction is currently live based on status."""
        # More complex time checks can be added if status management is not perfectly immediate
        return self.is_for_auction and self.auction_status == 'live'

    @property
    def time_until_auction_starts(self):
        """Returns timedelta until auction starts, or None if not applicable/started."""
        if self.is_for_auction and self.auction_start_time and \
           self.auction_status not in ['live', 'ended_pending_payment', 'completed', 'failed_no_bids', 'failed_payment', 'cancelled_by_owner']:
            now = timezone.now()
            if self.auction_start_time > now:
                return self.auction_start_time - now
        return None

    @property
    def time_until_signup_deadline(self):
        """Returns timedelta until signup deadline, or None if not applicable/passed."""
        if self.is_for_auction and self.auction_signup_deadline and self.auction_status == 'signup_open':
            now = timezone.now()
            if self.auction_signup_deadline > now:
                return self.auction_signup_deadline - now
        return None
    
    def get_effective_auction_status_and_save(self):
        """
        Updates the auction status based on current time and existing status.
        This should be called periodically (e.g., by a task or before displaying status)
        to ensure statuses like 'live' or 'awaiting_attendee_approval' are set correctly.
        Returns the current (possibly updated) status string.
        """
        if not self.is_for_auction: # If not for auction at all
            if self.auction_status != 'draft':
                self.auction_status = 'draft'
                # Consider clearing other auction fields here too, though model save also does it
                self.save(update_fields=['auction_status'])
            return self.auction_status

        now = timezone.now()
        original_status = self.auction_status
        changed_fields = []

        # Only proceed with time-based transitions if the auction is in a state that expects them
        if self.auction_status in ['pending_signup_window', 'signup_open', 'awaiting_attendee_approval', 'ready_to_start']:
            if self.auction_start_time and self.auction_signup_deadline: # Ensure core times are set
                if self.auction_status == 'pending_signup_window':
                    # Logic to transition from pending_signup_window to signup_open
                    # This depends on when you want signups to officially open.
                    # For now, assume it's handled by admin/owner setting it to 'signup_open' or
                    # if now is after some predefined "signup_opens_at" time (not yet implemented)
                    # and before auction_signup_deadline.
                    # Let's assume if it's pending, and deadline is in future, it becomes signup_open
                    if now < self.auction_signup_deadline: # A simplified condition
                         self.auction_status = 'signup_open'

                if self.auction_status == 'signup_open':
                    if now >= self.auction_signup_deadline:
                        self.auction_status = 'awaiting_attendee_approval'
                
                elif self.auction_status == 'awaiting_attendee_approval':
                    # This status typically changes based on owner actions (approving attendees).
                    # It could auto-transition to 'ready_to_start' if all are reviewed,
                    # or if start time is very close.
                    # For now, this method won't auto-transition out of it without owner action.
                    # However, if somehow it's in this state and start time passes, it should go live.
                    if now >= self.auction_start_time:
                        self.auction_status = 'live'


                elif self.auction_status == 'ready_to_start': # Owner has finalized approvals
                    if now >= self.auction_start_time:
                        self.auction_status = 'live'
            else: # Core times not set, ensure it's draft if not already some end-state
                if self.auction_status not in ['draft', 'completed', 'failed_no_bids', 'failed_payment', 'cancelled_by_owner']:
                    self.auction_status = 'draft'
        
        # If auction status has changed from its original value during this check
        if original_status != self.auction_status:
            changed_fields.append('auction_status')
        
        # Always ensure signup deadline is current if auction is on and start time is set
        # This is also handled in the main save, but good to be explicit if we save here
        if self.is_for_auction and self.auction_start_time and self.auction_signup_offset_minutes is not None:
            new_deadline = self.auction_start_time - timedelta(minutes=self.auction_signup_offset_minutes)
            if self.auction_signup_deadline != new_deadline:
                self.auction_signup_deadline = new_deadline
                if 'auction_signup_deadline' not in changed_fields:
                    changed_fields.append('auction_signup_deadline')

        if changed_fields:
            self.save(update_fields=changed_fields) 
            print(f"Artwork '{self.title}': Auction state updated. Status: '{self.auction_status}', Deadline: '{self.auction_signup_deadline}'. Changed fields: {changed_fields}")

        return self.auction_status

    def can_user_register_for_auction(self, user):
        if not user or not user.is_authenticated:
            return False
        
        # Call get_effective_auction_status_and_save to ensure status is current
        # self.get_effective_auction_status_and_save() # Be careful with recursive saves if called from save() itself.
                                                    # Better to call this explicitly in views before checking.

        if self.auction_status != 'signup_open': # Rely on the (potentially updated) status
            return False
            
        now = timezone.now()
        if not self.auction_signup_deadline or now >= self.auction_signup_deadline: # Double check deadline
            return False

        if self.current_owner == user: 
            return False
        
        from artworks.models import AuctionRegistration # Local import to avoid circularity
        if AuctionRegistration.objects.filter(artwork=self, user=user).exists():
            return False 
        return True

    def get_user_auction_registration(self, user):
        if not user or not user.is_authenticated:
            return None
        from artworks.models import AuctionRegistration 
        try:
            return AuctionRegistration.objects.get(artwork=self, user=user)
        except AuctionRegistration.DoesNotExist:
            return None
        
    def finalize_auction(self):
        print(f"[finalize_auction] Called for: {self.title}, Current Status: {self.auction_status}")

        # Prevent re-finalizing if already in a terminal auction state
        if self.auction_status in ['ended_pending_payment', 'completed', 'failed_no_bids', 'failed_payment', 'cancelled_by_owner']:
            print(f"[finalize_auction] Auction '{self.title}' already in a terminal state: {self.auction_status}. No action.")
            # Return existing transaction if applicable, or None
            if self.auction_status == 'ended_pending_payment' and self.auction_winner:
                try:
                    # Attempt to find the transaction associated with this win
                    return Transaction.objects.get(artwork=self, buyer=self.auction_winner, sale_type='auction_win')
                except Transaction.DoesNotExist:
                    return None # Should not happen if status is ended_pending_payment correctly
            return None

        # This method assumes the *time* for auction end has passed.
        # It now focuses on determining outcome based on bids.

        highest_bid = Bid.objects.filter(artwork=self).order_by('-amount', '-timestamp').first()
        
        original_status_before_finalize = self.auction_status # For debugging/logging
        changed_fields_artwork = []

        if highest_bid and self.auction_minimum_bid is not None and highest_bid.amount >= self.auction_minimum_bid:
            print(f"[finalize_auction] Winning bid found for '{self.title}': {highest_bid.amount} by {highest_bid.bidder.username}")
            self.auction_status = 'ended_pending_payment'
            self.auction_winner = highest_bid.bidder
            self.auction_winning_price = highest_bid.amount
            
            changed_fields_artwork.extend(['auction_status', 'auction_winner', 'auction_winning_price'])
            
            if self.current_owner and self.auction_winner:
                try:
                    # Using get_or_create makes this method more idempotent regarding transaction creation
                    transaction_obj, created = Transaction.objects.get_or_create(
                        artwork=self,
                        buyer=self.auction_winner,
                        seller=self.current_owner, 
                        sale_type='auction_win', # Key for uniqueness with artwork & buyer for an auction
                        defaults={
                            'final_price': self.auction_winning_price,
                            'status': 'pending_payment'
                        }
                    )
                    if created:
                        print(f"[finalize_auction] Transaction CREATED for '{self.title}'. ID: {transaction_obj.id}")
                    else:
                        print(f"[finalize_auction] Transaction already EXISTED for '{self.title}'. ID: {transaction_obj.id}, Status: {transaction_obj.status}")
                        # If transaction existed, ensure its price is correct (shouldn't change for auction win)
                        if transaction_obj.final_price != self.auction_winning_price:
                            transaction_obj.final_price = self.auction_winning_price
                            transaction_obj.save(update_fields=['final_price'])
                        # If it existed and was, e.g., 'cancelled', this logic doesn't automatically reopen it.
                        # This might need more complex handling if an auction can be "re-won" by the same person
                        # after a previous transaction failed. For now, get_or_create is good.

                    self.save(update_fields=changed_fields_artwork)
                    print(f"[finalize_auction] Artwork '{self.title}' saved. New status: {self.auction_status}")
                    return transaction_obj
                except Exception as e:
                    print(f"[finalize_auction] ERROR creating/getting transaction for '{self.title}': {e}")
                    self.auction_status = 'failed_payment' # Or a more specific error status
                    self.auction_winner = None # Clear winner if transaction fails
                    self.auction_winning_price = None
                    changed_fields_artwork = ['auction_status', 'auction_winner', 'auction_winning_price'] # Reset list for save
                    self.save(update_fields=changed_fields_artwork)
                    return None
            else: # Should not happen if highest_bid and owner are present
                print(f"[finalize_auction] Critical error: Missing current_owner or auction_winner for '{self.title}' despite a winning bid.")
                self.auction_status = 'failed_payment' # Indicate an internal error
                changed_fields_artwork = ['auction_status']
                self.save(update_fields=changed_fields_artwork)
                return None
        else: 
            print(f"[finalize_auction] No valid winning bid for '{self.title}'. Highest bid object: {highest_bid}. Min bid: {self.auction_minimum_bid}")
            self.auction_status = 'failed_no_bids'
            self.auction_winner = None
            self.auction_winning_price = None
            changed_fields_artwork.extend(['auction_status', 'auction_winner', 'auction_winning_price'])
            self.save(update_fields=changed_fields_artwork)
            print(f"[finalize_auction] Artwork '{self.title}' saved. New status: {self.auction_status}")
            return None
        
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