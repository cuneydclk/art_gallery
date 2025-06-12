# artworks/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from .models import Artwork, Comment, Transaction, GallerySetting, UserProfile, AuctionRegistration, Bid # AuctionRegistration Added
from .forms import (CommentForm, GuestCommentForm, ArtworkDirectSaleForm, 
                    DekontUploadForm, UserProfileForm,
                    ArtworkAuctionSettingsForm, PlaceBidForm)
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q
from django.db import transaction as db_transaction
from decimal import Decimal


def artwork_list_view(request):
    artworks = Artwork.objects.all().order_by('-created_at')
    context = {
        'artworks': artworks,
        'page_title': 'Art Gallery'
    }
    return render(request, 'artworks/artwork_list.html', context)

def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('artworks:artwork_list')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form, 'page_title': 'Sign Up'})

@login_required
def my_art_view(request):
    owned_artworks = Artwork.objects.filter(current_owner=request.user).order_by('-created_at')
    context = {
        'owned_artworks': owned_artworks,
        'page_title': 'My Art'
    }
    return render(request, 'artworks/my_art.html', context)

def artwork_detail_view(request, slug): # SINGLE DEFINITION OF THIS VIEW
    artwork = get_object_or_404(Artwork, slug=slug)
    comments = artwork.comments.all().order_by('-created_at')

    # Ensure artwork status is up-to-date
    artwork.get_effective_auction_status_and_save() 
    
    print(f"--- Entering artwork_detail_view for slug: {slug} ---") 
    print(f"Request method: {request.method}") 
    print(f"Artwork current auction status: {artwork.auction_status}")

    # Initialize forms
    comment_form_initial = CommentForm() if request.user.is_authenticated else None
    guest_comment_form_initial = GuestCommentForm()
    direct_sale_form_initial = None
    auction_settings_form_initial = None

    if request.user.is_authenticated and request.user == artwork.current_owner:
        print("User is owner, initializing owner forms.") 
        direct_sale_form_initial = ArtworkDirectSaleForm(instance=artwork)
        auction_settings_form_initial = ArtworkAuctionSettingsForm(instance=artwork)

    # These will hold the forms to be rendered (possibly with errors)
    comment_form_to_render = comment_form_initial
    guest_comment_form_to_render = guest_comment_form_initial
    direct_sale_form_to_render = direct_sale_form_initial
    auction_settings_form_to_render = auction_settings_form_initial
   
    # User Auction Interaction Data for THIS artwork
    user_can_register_for_this_auction = False
    user_auction_registration_on_this_artwork = None
    if request.user.is_authenticated:
        # Make sure artwork status is fresh before checking registration eligibility
        # artwork.get_effective_auction_status_and_save() # Already called above
        user_can_register_for_this_auction = artwork.can_user_register_for_auction(request.user)
        user_auction_registration_on_this_artwork = artwork.get_user_auction_registration(request.user)
        print(f"User: {request.user.username}, Can register for this auction: {user_can_register_for_this_auction}, Existing reg: {user_auction_registration_on_this_artwork}")
    
    if request.method == 'POST':
        print(f"POST data: {request.POST}") 

        if 'submit_comment' in request.POST:
            print("Processing: submit_comment") 
            comment_form_processing = CommentForm(request.POST) if request.user.is_authenticated else GuestCommentForm(request.POST)
            if comment_form_processing.is_valid(): 
                print("Comment form IS VALID")
                new_comment = comment_form_processing.save(commit=False)
                new_comment.artwork = artwork
                if request.user.is_authenticated:
                    new_comment.user = request.user
                new_comment.save()
                messages.success(request, 'Your comment has been posted!')
                return redirect('artworks:artwork_detail', slug=artwork.slug)
            else:
                print(f"Comment form IS INVALID. Errors: {comment_form_processing.errors.as_json()}")
                messages.error(request, 'There was an error posting your comment.')
                if request.user.is_authenticated:
                    comment_form_to_render = comment_form_processing
                else:
                    guest_comment_form_to_render = comment_form_processing

        elif 'submit_sale_settings' in request.POST and request.user.is_authenticated and request.user == artwork.current_owner:
            print("Processing: submit_sale_settings")
            direct_sale_form_processing = ArtworkDirectSaleForm(request.POST, instance=artwork)
            if direct_sale_form_processing.is_valid(): 
                print("Direct sale form IS VALID")
                updated_artwork = direct_sale_form_processing.save(commit=False)
                if updated_artwork.is_for_sale_direct:
                    updated_artwork.is_for_auction = False 
                    updated_artwork.auction_status = 'draft' 
                updated_artwork.save()
                messages.success(request, 'Direct sale settings updated successfully!')
                return redirect('artworks:artwork_detail', slug=artwork.slug)
            else:
                print(f"Direct sale form IS INVALID. Errors: {direct_sale_form_processing.errors.as_json()}")
                messages.error(request, 'Error updating direct sale settings.')
                direct_sale_form_to_render = direct_sale_form_processing

        elif 'submit_auction_settings' in request.POST and request.user.is_authenticated and request.user == artwork.current_owner:
            print("Processing: submit_auction_settings")
            auction_settings_form_processing = ArtworkAuctionSettingsForm(request.POST, instance=artwork)
            if auction_settings_form_processing.is_valid():
                print("Auction form IS VALID") 
                updated_artwork = auction_settings_form_processing.save(commit=False)
                if updated_artwork.is_for_auction:
                    updated_artwork.is_for_sale_direct = False
                    updated_artwork.direct_sale_price = None
                    if updated_artwork.auction_status in ['draft', None, 'cancelled_by_owner', 'completed', 'failed_no_bids', 'failed_payment'] or not updated_artwork.auction_status:
                        now = timezone.now()
                        if updated_artwork.auction_start_time and updated_artwork.auction_signup_deadline:
                            if now < updated_artwork.auction_signup_deadline:
                                updated_artwork.auction_status = 'signup_open' 
                            elif now < updated_artwork.auction_start_time:
                                updated_artwork.auction_status = 'awaiting_attendee_approval'
                            else: 
                                updated_artwork.auction_status = 'live' 
                        else:
                             updated_artwork.auction_status = 'draft' 
                else: 
                    updated_artwork.auction_status = 'draft'
                
                print(f"Saving artwork. is_for_auction: {updated_artwork.is_for_auction}, status: {updated_artwork.auction_status}")
                updated_artwork.save() 
                messages.success(request, 'Auction settings updated successfully!')
                print("Redirecting after successful auction update.")
                # After successful save, re-fetch artwork to get latest state for context
                artwork = get_object_or_404(Artwork, slug=slug) # Re-fetch
                artwork.get_effective_auction_status_and_save() # Update status again if needed
                user_can_register_for_this_auction = artwork.can_user_register_for_auction(request.user) if request.user.is_authenticated else False
                user_auction_registration_on_this_artwork = artwork.get_user_auction_registration(request.user) if request.user.is_authenticated else None
                # No need to redirect here if we want to show the updated state immediately
                # but typically a redirect after POST is good practice (PRG pattern)
                # For now, let's keep the redirect for simplicity of state.
                return redirect('artworks:artwork_detail', slug=artwork.slug)

            else:
                print(f"Auction form IS INVALID. Errors: {auction_settings_form_processing.errors.as_json(escape_html=True)}") 
                messages.error(request, 'Error updating auction settings. Please check the details provided.')
                auction_settings_form_to_render = auction_settings_form_processing
        else:
            print("POST request, but no recognized submit button found in POST data for owner actions, or user not owner.")

    context = {
        'artwork': artwork, # artwork object, potentially updated by get_effective_auction_status_and_save
        'comments': comments,
        'comment_form': comment_form_to_render,
        'guest_comment_form': guest_comment_form_to_render,
        'direct_sale_form': direct_sale_form_to_render,
        'auction_settings_form': auction_settings_form_to_render,
        'page_title': artwork.title,
        'user_can_register_for_this_auction': user_can_register_for_this_auction,
        'user_auction_registration_on_this_artwork': user_auction_registration_on_this_artwork,
    }
    print(f"--- Context for template: Can register: {user_can_register_for_this_auction}, User Reg Obj: {user_auction_registration_on_this_artwork} ---")
    print(f"--- Rendering template artwork_detail.html for auction_status: {artwork.auction_status} ---")
    return render(request, 'artworks/artwork_detail.html', context)

@login_required
def initiate_buy_view(request, artwork_slug):
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    if not artwork.is_for_sale_direct or not artwork.direct_sale_price:
        messages.error(request, "This artwork is not currently for direct sale.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    if artwork.current_owner == request.user:
        messages.error(request, "You cannot buy your own artwork.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    existing_transaction = Transaction.objects.filter(
        artwork=artwork, buyer=request.user, status__in=['pending_payment', 'pending_approval']
    ).first()
    if existing_transaction:
        messages.info(request, "You already have a pending purchase for this artwork.")
        return redirect('artworks:payment_and_dekont_upload', transaction_id=existing_transaction.id)
    if request.method == 'POST':
        transaction = Transaction.objects.create(
            artwork=artwork, buyer=request.user, seller=artwork.current_owner,
            sale_type='direct_buy', final_price=artwork.direct_sale_price, status='pending_payment'
        )
        messages.success(request, f"Purchase initiated for '{artwork.title}'. Please proceed with payment and dekont upload.")
        return redirect('artworks:payment_and_dekont_upload', transaction_id=transaction.id)
    messages.error(request, "Invalid request method for initiating purchase.")
    return redirect('artworks:artwork_detail', slug=artwork.slug)

@login_required
def payment_and_dekont_upload_view(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    if transaction.status not in ['pending_payment', 'pending_approval']:
        messages.error(request, "This transaction is not awaiting payment or dekont upload.")
        return redirect('artworks:artwork_detail', slug=transaction.artwork.slug) 
    gallery_settings = GallerySetting.load()
    if request.method == 'POST':
        form = DekontUploadForm(request.POST, request.FILES, instance=transaction)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.status = 'pending_approval'
            transaction.dekont_uploaded_at = timezone.now()
            transaction.save()
            messages.success(request, "Dekont uploaded successfully. We will review it shortly.")
            return redirect('artworks:transaction_status', transaction_id=transaction.id)
    else:
        form = DekontUploadForm(instance=transaction)
    context = {
        'transaction': transaction, 'artwork': transaction.artwork, 'form': form,
        'gallery_settings': gallery_settings, 'page_title': f"Payment for {transaction.artwork.title}"
    }
    return render(request, 'artworks/payment_dekont_upload.html', context)

@login_required
def transaction_status_view(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    context = {
        'transaction': transaction, 'artwork': transaction.artwork,
        'page_title': f"Transaction Status for {transaction.artwork.title}"
    }
    return render(request, 'artworks/transaction_status.html', context)

@login_required
def edit_profile_view(request):
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('artworks:edit_profile')
    else:
        form = UserProfileForm(instance=profile)
    context = {
        'form': form, 'page_title': 'Edit Your Profile & Bank Details'
    }
    return render(request, 'artworks/edit_profile.html', context)

@login_required
def available_auctions_view(request):
    now = timezone.now()
    potential_auctions_qs = Artwork.objects.filter(
        is_for_auction=True
    ).exclude(
        auction_status__in=['draft', 'completed', 'failed_no_bids', 'failed_payment', 'cancelled_by_owner']
    ).order_by('auction_start_time')

    auctions_data = []
    for artwork_item in potential_auctions_qs: # Renamed artwork to artwork_item to avoid conflict
        current_status = artwork_item.get_effective_auction_status_and_save()
        if current_status in ['draft', 'completed', 'failed_no_bids', 'failed_payment', 'cancelled_by_owner']:
            continue

        user_registration_status_text = None # Renamed for clarity
        can_register = False
        registration_obj = None

        if request.user.is_authenticated:
            registration_obj = artwork_item.get_user_auction_registration(request.user)
            if registration_obj:
                user_registration_status_text = registration_obj.get_status_display()
            else:
                if artwork_item.can_user_register_for_auction(request.user):
                    can_register = True
                    user_registration_status_text = "Available to Register" 
                elif artwork_item.auction_status == 'signup_open' and artwork_item.current_owner == request.user:
                    user_registration_status_text = "You are the owner"
        
        auctions_data.append({
            'artwork': artwork_item, # Use artwork_item here
            'current_status_display': artwork_item.get_auction_status_display(),
            'user_registration_status': user_registration_status_text, 
            'can_register_now': can_register,
            'registration': registration_obj,
            'time_until_start': artwork_item.time_until_auction_starts,
            'time_until_signup_deadline': artwork_item.time_until_signup_deadline,
        })
    context = {
        'auctions_data': auctions_data,
        'page_title': 'Available Auctions'
    }
    return render(request, 'artworks/available_auctions.html', context)

@login_required
def auction_register_view(request, artwork_slug): # artwork_slug matches the URL pattern
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    
    # Ensure status is up-to-date before processing registration
    artwork.get_effective_auction_status_and_save()

    if request.method == 'POST':
        print(f"Attempting registration for artwork: {artwork.title}, user: {request.user.username}") # DEBUG

        if artwork.current_owner == request.user:
            messages.error(request, "You cannot register for an auction on your own artwork.")
            return redirect('artworks:artwork_detail', slug=artwork.slug)

        if not artwork.can_user_register_for_auction(request.user):
            # can_user_register_for_auction already checks if signup is active and if user is already registered.
            # Provide a more specific message if possible based on why they can't register.
            existing_registration = artwork.get_user_auction_registration(request.user)
            if existing_registration:
                messages.warning(request, f"You are already registered for this auction with status: {existing_registration.get_status_display()}.")
            elif artwork.auction_status != 'signup_open':
                 messages.error(request, "Auction sign-up is not currently active for this artwork.")
            else: # Some other reason (e.g., specific user block - not implemented yet)
                messages.error(request, "You are not eligible to register for this auction at this time.")
            return redirect('artworks:artwork_detail', slug=artwork.slug)

        # If all checks pass, create the registration
        try:
            registration, created = AuctionRegistration.objects.get_or_create(
                artwork=artwork,
                user=request.user,
                defaults={'status': 'pending'} # Default status is 'pending'
            )
            if created:
                messages.success(request, f"Successfully registered for the auction of '{artwork.title}'. Your registration is pending owner approval.")
                print(f"Registration CREATED for artwork: {artwork.title}, user: {request.user.username}") # DEBUG
            else:
                # This case should ideally be caught by can_user_register_for_auction
                messages.info(request, f"You were already registered for this auction. Current status: {registration.get_status_display()}.")
                print(f"Registration already EXISTED for artwork: {artwork.title}, user: {request.user.username}, status: {registration.status}") # DEBUG
        
        except Exception as e: # Catch any other potential errors during creation
            messages.error(request, f"An error occurred while trying to register for the auction: {e}")
            print(f"ERROR during registration for artwork: {artwork.title}, user: {request.user.username}, error: {e}") # DEBUG

        return redirect('artworks:artwork_detail', slug=artwork.slug)
    else:
        # GET request to this URL is not typical for this action, redirect away.
        messages.error(request, "Invalid request method for auction registration.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    
@login_required
def manage_auction_registrations_view(request, artwork_slug):
    artwork = get_object_or_404(Artwork, slug=artwork_slug, current_owner=request.user) # Ensure owner
    
    # It's good practice to update the status in case time-based transitions occurred
    artwork.get_effective_auction_status_and_save()

    # Only allow management if auction is in a state where approvals make sense
    # (e.g., after signup closes and before auction starts, or even during signup_open if owner wants to pre-approve)
    # For now, let's be a bit flexible, but primarily targeting 'awaiting_attendee_approval'.
    # Or if it's 'signup_open' and they want to review early.
    if artwork.auction_status not in ['signup_open', 'awaiting_attendee_approval', 'ready_to_start']:
        messages.warning(request, "Attendee management is not available for this auction's current status.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    registrations = AuctionRegistration.objects.filter(artwork=artwork).order_by('registered_at')

    if request.method == 'POST':
        action = request.POST.get('action')
        registration_id = request.POST.get('registration_id')

        if not action or not registration_id:
            messages.error(request, "Invalid action or missing registration ID.")
            return redirect('artworks:manage_auction_registrations', artwork_slug=artwork.slug)

        try:
            registration_to_update = AuctionRegistration.objects.get(id=registration_id, artwork=artwork)
            
            if action == 'approve':
                registration_to_update.status = 'approved'
                registration_to_update.owner_reviewed_at = timezone.now()
                registration_to_update.save()
                messages.success(request, f"Registration for {registration_to_update.user.username} approved.")
                print(f"Registration ID {registration_id} for {artwork.title} APPROVED by owner.") # DEBUG
            elif action == 'reject':
                registration_to_update.status = 'rejected'
                registration_to_update.owner_reviewed_at = timezone.now()
                registration_to_update.save()
                messages.success(request, f"Registration for {registration_to_update.user.username} rejected.")
                print(f"Registration ID {registration_id} for {artwork.title} REJECTED by owner.") # DEBUG
            else:
                messages.error(request, "Unknown action.")
            
            # Check if all pending registrations are reviewed, if so, owner might want to "finalize"
            # or system could auto-move to 'ready_to_start' if conditions met.
            # For now, status change to 'ready_to_start' is manual or via get_effective_auction_status_and_save
            # if start time is very near.

        except AuctionRegistration.DoesNotExist:
            messages.error(request, "Registration not found.")
        except Exception as e:
            messages.error(request, f"An error occurred: {e}")
            print(f"Error processing registration action: {e}") # DEBUG
        
        return redirect('artworks:manage_auction_registrations', artwork_slug=artwork.slug)

    context = {
        'artwork': artwork,
        'registrations': registrations,
        'page_title': f"Manage Registrations for '{artwork.title}'"
    }
    return render(request, 'artworks/manage_auction_registrations.html', context)

@login_required
def auction_bidding_page_view(request, artwork_slug):
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    
    current_artwork_status = artwork.get_effective_auction_status_and_save()
    print(f"Entering bidding page for {artwork.title}, status: {current_artwork_status}")

    if current_artwork_status != 'live':
        messages.warning(request, "This auction is not currently live.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    user_registration = artwork.get_user_auction_registration(request.user)
    is_approved_attendee = user_registration and user_registration.status == 'approved'
    is_owner = artwork.current_owner == request.user

    if not is_approved_attendee and not is_owner:
        messages.error(request, "You are not an approved attendee for this auction.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    
    highest_bid_obj = Bid.objects.filter(artwork=artwork).order_by('-amount', '-timestamp').first()

    current_highest_bid_amount = None # Initialize
    current_highest_bidder = None   # Initialize

    # Try to use denormalized fields first for performance, then verify/override with Bid table
    # This part can be simplified if denormalized fields are always trusted to be up-to-date by place_bid_view
    temp_artwork_highest_bid = artwork.auction_current_highest_bid
    temp_artwork_highest_bidder = artwork.auction_current_highest_bidder

    if highest_bid_obj:
        current_highest_bid_amount = highest_bid_obj.amount
        current_highest_bidder = highest_bid_obj.bidder
        if temp_artwork_highest_bid != current_highest_bid_amount:
            print(f"Warning: Denormalized highest_bid on Artwork ({temp_artwork_highest_bid}) differs from Bid table ({current_highest_bid_amount}). Using Bid table.")
    elif temp_artwork_highest_bid is not None : # No bids in Bid table, but denormalized field has a value (should be min_bid if logic is consistent)
        # This case implies an issue or that minimum bid was stored in denormalized field as "current highest"
        # For safety, if Bid table is empty, current_highest_bid should be None initially.
        # The template will then show the minimum bid.
        print(f"Warning: No bids in Bid table, but artwork.auction_current_highest_bid is {temp_artwork_highest_bid}. Setting current_highest_bid_amount to None.")
        current_highest_bid_amount = None 
        current_highest_bidder = None


    # Determine minimum next bid
    if current_highest_bid_amount is not None: # A bid exists
        min_next_bid = current_highest_bid_amount + Decimal('1.00')
    elif artwork.auction_minimum_bid is not None: # No bids yet, use auction's minimum bid
        min_next_bid = artwork.auction_minimum_bid
    else:
        # This case should ideally not happen for a live auction (auction_minimum_bid should be required)
        messages.error(request, "Auction configuration error: Minimum bid not set.")
        return redirect('artworks:artwork_detail', slug=artwork.slug) # Or a more generic error page

    bid_form = None
    if is_approved_attendee and not is_owner:
        bid_form = PlaceBidForm(initial={'bid_amount': min_next_bid.quantize(Decimal('0.01')) if min_next_bid else None})


    # --- Time remaining and soft close logic ---
    now = timezone.now()
    time_remaining_seconds = 0
    auction_end_message = None
    soft_close_extension_seconds = 3 * 60  # 3 minutes

    effective_end_time = artwork.auction_scheduled_end_time # This is a datetime object or None
    is_soft_close_active = False

    if not effective_end_time: # Should not happen for a live auction
        messages.error(request, "Auction configuration error: Scheduled end time not set.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)


    if artwork.last_bid_time:
        potential_soft_close_end = artwork.last_bid_time + timedelta(seconds=soft_close_extension_seconds)
        if potential_soft_close_end > effective_end_time:
            effective_end_time = potential_soft_close_end
            is_soft_close_active = True
            print(f"Soft close active. New effective end: {effective_end_time}")

    if now >= effective_end_time:
        auction_end_message = "Auction has ended. Processing results..."
        print(f"Bidding page: Auction for {artwork.title} should end. Now: {now}, Effective End: {effective_end_time}")
        # Actual finalization (setting winner, etc.) will be handled more explicitly in Phase 6
        # or triggered robustly by place_bid_view if a bid makes it end.
    else:
        time_remaining_delta = effective_end_time - now
        time_remaining_seconds = int(time_remaining_delta.total_seconds())


    # --- Quick Bid Amounts ---
    quick_bid_amounts = []
    # Base for quick bids: either current highest, or if none, the minimum bid for the auction
    base_for_quick_bids_val = current_highest_bid_amount if current_highest_bid_amount is not None else artwork.auction_minimum_bid

    if base_for_quick_bids_val is not None: # Ensure base_for_quick_bids_val is not None
        # The first quick bid should be the minimum next valid bid
        # min_next_bid is already calculated correctly above
        
        current_bidding_ref_point = min_next_bid # Start suggestions from min_next_bid

        if current_bidding_ref_point is not None: # Ensure this isn't None
            # Ensure we are not suggesting bids lower than the required minimum for the auction
            if artwork.auction_minimum_bid is not None and current_bidding_ref_point < artwork.auction_minimum_bid:
                 current_bidding_ref_point = artwork.auction_minimum_bid
            
            quick_bid_amounts.append(current_bidding_ref_point)
            quick_bid_amounts.append(current_bidding_ref_point + Decimal('10.00'))
            quick_bid_amounts.append(current_bidding_ref_point + Decimal('50.00'))
            quick_bid_amounts.append(current_bidding_ref_point + Decimal('100.00'))
            
            # Filter and sanitize quick bids
            valid_quick_bids = []
            # Minimum bid to consider for any quick bid is the auction's minimum bid
            auction_abs_min_bid = artwork.auction_minimum_bid if artwork.auction_minimum_bid is not None else Decimal('0.01')
            # Current highest bid to compare against
            current_high_for_check = current_highest_bid_amount if current_highest_bid_amount is not None else Decimal('-1.00') # Value lower than any valid bid

            for qb_decimal in sorted(list(set(quick_bid_amounts))):
                if qb_decimal > current_high_for_check and qb_decimal >= auction_abs_min_bid:
                    valid_quick_bids.append(qb_decimal.quantize(Decimal('0.01'))) # Ensure 2 decimal places
            
            quick_bid_amounts = valid_quick_bids[:4] # Show up to 4 distinct, valid quick bids


    context = {
        'artwork': artwork,
        'bid_form': bid_form,
        'current_highest_bid': current_highest_bid_amount, # This is a Decimal or None
        'current_highest_bidder': current_highest_bidder,
        'min_next_bid': min_next_bid, # This is a Decimal or None
        'is_approved_attendee': is_approved_attendee,
        'is_owner': is_owner,
        'time_remaining_seconds': time_remaining_seconds,
        'auction_end_message': auction_end_message,
        'is_soft_close_active': is_soft_close_active,
        'effective_end_time_for_display': effective_end_time,
        'quick_bid_amounts': quick_bid_amounts, # List of Decimals
        'page_title': f"Live Bidding: {artwork.title}"
    }
    return render(request, 'artworks/auction_bidding_page.html', context)

@login_required
@db_transaction.atomic # Ensures all database operations in this view are one transaction
def place_bid_view(request, artwork_slug):
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    
    # Re-check and update status
    current_artwork_status = artwork.get_effective_auction_status_and_save()

    if current_artwork_status != 'live':
        messages.error(request, "This auction is not currently live or has just ended.")
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork.slug) # Or artwork_detail

    user_registration = artwork.get_user_auction_registration(request.user)
    if not user_registration or user_registration.status != 'approved':
        messages.error(request, "You are not an approved attendee for this auction.")
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork.slug) # Or artwork_detail
    
    if artwork.current_owner == request.user:
        messages.error(request, "As the owner, you cannot bid on your own artwork.")
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork.slug)

    if request.method == 'POST':
        form = PlaceBidForm(request.POST)
        if form.is_valid():
            bid_amount = form.cleaned_data['bid_amount']
            now = timezone.now()
            
            print(f"User {request.user.username} attempting to bid {bid_amount} on {artwork.title}") # DEBUG

            # --- Critical Section: Determine current highest bid and validate new bid ---
            # Lock the artwork row for update to prevent race conditions when getting highest bid and placing new one.
            # artwork_locked = Artwork.objects.select_for_update().get(pk=artwork.pk) # Use this if high concurrency is expected
            # For now, we rely on the @db_transaction.atomic and careful ordering.

            highest_bid_obj = Bid.objects.filter(artwork=artwork).order_by('-amount', '-timestamp').first()
            current_highest_bid_val = artwork.auction_minimum_bid # Start with minimum if no bids
            if highest_bid_obj:
                current_highest_bid_val = highest_bid_obj.amount
            
            # Ensure the bid is higher than the current highest (or minimum if no bids)
            # And also strictly greater than any existing bid (or equal to minimum if it's the first bid)
            required_min_bid = artwork.auction_minimum_bid
            if highest_bid_obj:
                 # A common rule: bid must be at least current_highest + a minimum increment (e.g. $1)
                 # For simplicity now, just greater than current_highest_bid_val
                if bid_amount <= current_highest_bid_val:
                    messages.error(request, f"Your bid must be higher than the current highest bid of ${current_highest_bid_val:.2f}.")
                    return redirect('artworks:auction_bidding_page', artwork_slug=artwork.slug)
            elif bid_amount < artwork.auction_minimum_bid: # First bid must meet minimum
                 messages.error(request, f"Your first bid must be at least the minimum bid of ${artwork.auction_minimum_bid:.2f}.")
                 return redirect('artworks:auction_bidding_page', artwork_slug=artwork.slug)


            # --- All checks passed, create the bid and update artwork ---
            Bid.objects.create(
                artwork=artwork,
                bidder=request.user,
                amount=bid_amount,
                timestamp=now 
            )
            
            artwork.auction_current_highest_bid = bid_amount
            artwork.auction_current_highest_bidder = request.user
            artwork.last_bid_time = now
            
            # Soft close: if the bid is within X minutes of scheduled end, or after, extend the scheduled end time
            soft_close_extension = timedelta(seconds=3 * 60) # 3 minutes
            # Check if the current scheduled end time needs extension
            if artwork.auction_scheduled_end_time: # Ensure it's set
                if (now + soft_close_extension) > artwork.auction_scheduled_end_time and \
                   (artwork.auction_scheduled_end_time - now) < soft_close_extension :
                    new_scheduled_end_time = now + soft_close_extension
                    artwork.auction_scheduled_end_time = new_scheduled_end_time
                    print(f"Soft close triggered by bid. New scheduled end for {artwork.title}: {new_scheduled_end_time}") #DEBUG
                    messages.info(request, f"Auction extended! New end time: {new_scheduled_end_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")


            artwork.save(update_fields=[
                'auction_current_highest_bid', 
                'auction_current_highest_bidder', 
                'last_bid_time',
                'auction_scheduled_end_time' # If soft close extended it
            ])
            messages.success(request, f"Your bid of ${bid_amount:.2f} has been placed successfully!")
            print(f"Bid of {bid_amount} by {request.user.username} PLACED on {artwork.title}") # DEBUG

            # --- Check if auction should end NOW (after this bid) ---
            # This is a simplified check. A more robust system might have a separate finalization mechanism.
            effective_end_time = artwork.auction_scheduled_end_time # The potentially extended time
            if artwork.last_bid_time: # Should always be true here
                 # The auction ends if current time is past (last_bid_time + soft_close_extension)
                 # OR if current time is past scheduled_end_time (if no bids extended it)
                 # This condition is tricky, as the bid itself sets last_bid_time to 'now'
                 # The check in auction_bidding_page_view is more for display timeout.
                 # True finalization will be more explicit in Phase 6.
                 # For now, the auction continues until no bids for `soft_close_extension` period AFTER scheduled end.
                 pass


        else: # Form is not valid (e.g., non-decimal input)
            # errors = form.errors.as_json() # For debugging
            messages.error(request, "Invalid bid amount submitted. Please enter a valid number.")
            print(f"Invalid bid form submission: {form.errors.as_json()}") # DEBUG
        
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork.slug)
    else:
        # Should not be accessed via GET
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    
@login_required
def auction_bidding_page_view(request, artwork_slug):
    print(f"[DEBUG] 0. Entered auction_bidding_page_view for slug: {artwork_slug}")
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    
    artwork.get_effective_auction_status_and_save() # Update status first
    artwork = Artwork.objects.get(pk=artwork.pk) # Re-fetch for freshest data
    current_artwork_status = artwork.auction_status
    print(f"[DEBUG] 1. Initial status for '{artwork.title}': {current_artwork_status}")

    now = timezone.now()
    print(f"[DEBUG] Server 'now': {now}")

    effective_end_time = artwork.auction_scheduled_end_time
    if not effective_end_time:
        messages.error(request, f"Config Error for '{artwork.title}': Scheduled end time missing.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    soft_close_extension_seconds = 3 * 60 
    is_soft_close_active = False
    if artwork.last_bid_time:
        potential_soft_close_end = artwork.last_bid_time + timedelta(seconds=soft_close_extension_seconds)
        if potential_soft_close_end > effective_end_time:
            effective_end_time = potential_soft_close_end
            is_soft_close_active = True
    print(f"[DEBUG] Calculated effective_end_time for '{artwork.title}': {effective_end_time}")

    # --- Attempt to finalize if time has passed and auction was live ---
    if current_artwork_status == 'live' and now >= effective_end_time:
        print(f"[DEBUG] 5. ENTERED FINALIZE BLOCK for '{artwork.title}': now ({now}) >= effective_end_time ({effective_end_time}) is TRUE.")
        transaction_result = artwork.finalize_auction()
        # artwork instance IS MODIFIED by finalize_auction and saved within it.
        # So, artwork.auction_status, artwork.auction_winner etc. are now up-to-date.
        current_artwork_status = artwork.auction_status # Update local variable
        print(f"[DEBUG] 6. Status after finalize_auction for '{artwork.title}': {current_artwork_status}")

        if current_artwork_status == 'ended_pending_payment' and transaction_result:
            winner_username = artwork.auction_winner.username if artwork.auction_winner else "N/A"
            msg = f"Auction for '{artwork.title}' has ended! Winner: {winner_username}."
            
            if request.user.is_authenticated and artwork.auction_winner and request.user.id == artwork.auction_winner.id:
                msg += " Please proceed to payment."
                messages.success(request, msg)
                print(f"[DEBUG] Finalize Block: Redirecting WINNER {request.user.username} to payment for transaction {transaction_result.id}")
                return redirect('artworks:payment_and_dekont_upload', transaction_id=transaction_result.id)
            else:
                msg += " Awaiting payment from winner."
                messages.success(request, msg)
                print(f"[DEBUG] Finalize Block: Redirecting NON-WINNER {request.user.username if request.user.is_authenticated else 'Anon'} to artwork detail for '{artwork.title}'")
                return redirect('artworks:artwork_detail', slug=artwork.slug)
        elif current_artwork_status == 'failed_no_bids':
            messages.info(request, f"Auction for '{artwork.title}' ended: No valid winning bids.")
            print(f"[DEBUG] Finalize Block: Redirecting to artwork detail for '{artwork.title}' (failed_no_bids)")
            return redirect('artworks:artwork_detail', slug=artwork.slug)
        elif current_artwork_status == 'failed_payment':
             messages.error(request, f"Auction for '{artwork.title}' ended with a transaction setup issue.")
             print(f"[DEBUG] Finalize Block: Redirecting to artwork detail for '{artwork.title}' (failed_payment)")
             return redirect('artworks:artwork_detail', slug=artwork.slug)
        elif current_artwork_status not in ['live']: 
            messages.info(request, f"The auction for '{artwork.title}' has concluded (Status: {artwork.get_auction_status_display()}).")
            print(f"[DEBUG] Finalize Block: Redirecting to artwork detail for '{artwork.title}' (concluded with status: {current_artwork_status})")
            return redirect('artworks:artwork_detail', slug=artwork.slug)
        else: 
             print(f"[DEBUG] Warning: finalize_auction was called for '{artwork.title}' but status is still 'live'. Letting page render.")
             # This case allows the page to render if, for some reason, finalize_auction didn't change status from 'live'
    else: # Finalize block was skipped
        print(f"[DEBUG] 5. SKIPPED FINALIZE BLOCK for '{artwork.title}'.")
        if current_artwork_status != 'live': print(f"  - Reason: Status is '{current_artwork_status}', not 'live'.")
        if effective_end_time and now < effective_end_time: print(f"  - Reason: now ({now}) < effective_end_time ({effective_end_time}). Remaining: {effective_end_time - now}")
    
    # --- Post-Finalization Check & Permission Logic ---
    # current_artwork_status variable should reflect the true state after any finalization attempt above.
    print(f"[DEBUG] 7. Status before render/permission checks for '{artwork.title}': {current_artwork_status}")

    # If auction just ended and this user is the winner, and they weren't redirected from the block above
    # (e.g., they refreshed the page after it was finalized by another request/process)
    if current_artwork_status == 'ended_pending_payment':
        print(f"[DEBUG] Post-finalize state: Status is 'ended_pending_payment' for '{artwork.title}'.")
        if artwork.auction_winner and request.user.is_authenticated and request.user.id == artwork.auction_winner.id:
            try:
                # Try to find the transaction that should have been created by finalize_auction
                win_transaction = Transaction.objects.get(artwork=artwork, buyer=artwork.auction_winner, sale_type='auction_win')
                # Check if this transaction is still pending payment (it should be)
                if win_transaction.status == 'pending_payment':
                    messages.success(request, f"You won the auction for '{artwork.title}'! Please proceed to payment.")
                    print(f"[DEBUG] Post-finalize state: Redirecting WINNER {request.user.username} to payment for transaction {win_transaction.id}")
                    return redirect('artworks:payment_and_dekont_upload', transaction_id=win_transaction.id)
                else:
                    # Winner, but transaction is not pending_payment (e.g. already approved/rejected). They see the rendered page.
                    print(f"[DEBUG] Post-finalize state: Winner {request.user.username}, but transaction {win_transaction.id} status is {win_transaction.status}. Rendering page.")
            except Transaction.DoesNotExist:
                messages.error(request, "Error: Winning transaction details not found. Please contact support.")
                print(f"[DEBUG] Post-finalize state: ERROR - Winning transaction not found for winner {artwork.auction_winner.username} on '{artwork.title}'")
                return redirect('artworks:artwork_detail', slug=artwork.slug) 
            except Transaction.MultipleObjectsReturned:
                messages.error(request, "Error: System error regarding your win. Please contact support.")
                print(f"[DEBUG] Post-finalize state: ERROR - Multiple transactions for winner {artwork.auction_winner.username} on '{artwork.title}'")
                return redirect('artworks:artwork_detail', slug=artwork.slug)
        # If not the winner, or if winner but transaction not pending_payment, they will see the rendered bidding page showing auction ended.

    # If auction is no longer suitable for active bidding display (and not handled by a redirect yet)
    if current_artwork_status not in ['live', 'ended_pending_payment']:
        print(f"[DEBUG] 8. Redirecting from bidding page for '{artwork.title}' as status '{current_artwork_status}' is not live/ended_pending_payment for display.")
        messages.info(request, f"The auction for '{artwork.title}' is not currently active for bidding (Status: {artwork.get_auction_status_display()}).")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    # --- Prepare for Rendering Bidding Page (if still live or just ended for viewing) ---
    user_registration = artwork.get_user_auction_registration(request.user)
    is_approved_attendee = user_registration and user_registration.status == 'approved'
    is_owner = artwork.current_owner == request.user
    print(f"[DEBUG] 9. Permissions for '{artwork.title}': approved_attendee={is_approved_attendee}, is_owner={is_owner}")

    if not is_approved_attendee and not is_owner: 
        print(f"[DEBUG] 10. Redirecting from bidding page for '{artwork.title}' (not approved and not owner)")
        messages.error(request, "You are not an approved attendee for this auction.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    highest_bid_obj = Bid.objects.filter(artwork=artwork).order_by('-amount', '-timestamp').first()
    current_highest_bid_amount = highest_bid_obj.amount if highest_bid_obj else None
    current_highest_bidder = highest_bid_obj.bidder if highest_bid_obj else None
    
    min_next_bid = None
    if current_highest_bid_amount is not None:
        min_next_bid = current_highest_bid_amount + Decimal('1.00')
    elif artwork.auction_minimum_bid is not None:
        min_next_bid = artwork.auction_minimum_bid
    
    bid_form = None
    auction_end_message = None 
    time_remaining_seconds = 0 

    if current_artwork_status == 'live': 
        if is_approved_attendee and not is_owner:
            form_initial_bid = min_next_bid.quantize(Decimal('0.01')) if min_next_bid else None
            bid_form = PlaceBidForm(initial={'bid_amount': form_initial_bid })
        
        if effective_end_time and now < effective_end_time: # Recalculate based on current 'now'
             current_time_remaining_delta = effective_end_time - now
             time_remaining_seconds = max(0, int(current_time_remaining_delta.total_seconds()))
        else: 
             time_remaining_seconds = 0
             if not auction_end_message: 
                  auction_end_message = "Auction has ended." # General message if not set by finalize
    elif current_artwork_status == 'ended_pending_payment':
        winner_username_display = artwork.auction_winner.username if artwork.auction_winner else 'N/A'
        auction_end_message = f"Auction ended! Winner: {winner_username_display}. Awaiting payment."
        bid_form = None # No bidding form if auction has ended

    quick_bid_amounts = [] # Calculate quick bids as before
    if current_artwork_status == 'live' and min_next_bid is not None : 
        base_for_quick_bids_val = min_next_bid
        quick_bid_amounts.append(base_for_quick_bids_val)
        quick_bid_amounts.append(base_for_quick_bids_val + Decimal('10.00'))
        quick_bid_amounts.append(base_for_quick_bids_val + Decimal('50.00'))
        quick_bid_amounts.append(base_for_quick_bids_val + Decimal('100.00'))
        valid_quick_bids = []
        auction_abs_min_bid = artwork.auction_minimum_bid if artwork.auction_minimum_bid is not None else Decimal('0.01')
        current_high_for_check = current_highest_bid_amount if current_highest_bid_amount is not None else Decimal('-1.00')
        for qb_decimal in sorted(list(set(quick_bid_amounts))):
            if qb_decimal > current_high_for_check and qb_decimal >= auction_abs_min_bid:
                valid_quick_bids.append(qb_decimal.quantize(Decimal('0.01')))
        quick_bid_amounts = valid_quick_bids[:4]
    
    print(f"[DEBUG] 11. Preparing to render bidding page for '{artwork.title}'. Status: {current_artwork_status}, Time Rem: {time_remaining_seconds}s, BidForm: {'Yes' if bid_form else 'No'}")
    context = {
        'artwork': artwork, 'bid_form': bid_form, 
        'current_highest_bid': current_highest_bid_amount, 'current_highest_bidder': current_highest_bidder,
        'min_next_bid': min_next_bid, 'is_approved_attendee': is_approved_attendee, 'is_owner': is_owner,
        'time_remaining_seconds': time_remaining_seconds, 'auction_end_message': auction_end_message,
        'is_soft_close_active': is_soft_close_active, 'effective_end_time_for_display': effective_end_time, 
        'quick_bid_amounts': quick_bid_amounts, 'page_title': f"Live Bidding: {artwork.title}"
    }
    return render(request, 'artworks/auction_bidding_page.html', context)

@login_required
@db_transaction.atomic
def place_bid_view(request, artwork_slug): # MODIFIED
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    
    # Lock the artwork row for this transaction to prevent race conditions on bid placement
    # This ensures that checking current highest bid and placing a new one is atomic.
    artwork_locked = Artwork.objects.select_for_update().get(pk=artwork.pk)
    
    # Use the locked instance for all checks and updates within this transaction
    current_artwork_status = artwork_locked.get_effective_auction_status_and_save()

    if current_artwork_status != 'live':
        messages.error(request, "This auction is not currently live or has just ended.")
        # Redirect to bidding page to show current state, or detail page if preferred
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork_locked.slug)

    user_registration = artwork_locked.get_user_auction_registration(request.user)
    if not user_registration or user_registration.status != 'approved':
        messages.error(request, "You are not an approved attendee for this auction.")
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork_locked.slug)
    
    if artwork_locked.current_owner == request.user:
        messages.error(request, "As the owner, you cannot bid on your own artwork.")
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork_locked.slug)

    if request.method == 'POST':
        form = PlaceBidForm(request.POST)
        if form.is_valid():
            bid_amount = form.cleaned_data['bid_amount']
            now = timezone.now()
            print(f"User {request.user.username} attempting to bid {bid_amount} on {artwork_locked.title}")

            # --- Determine current highest bid using the locked artwork instance ---
            highest_bid_obj = Bid.objects.filter(artwork=artwork_locked).order_by('-amount', '-timestamp').first()
            current_highest_bid_val = artwork_locked.auction_minimum_bid 
            if highest_bid_obj:
                current_highest_bid_val = highest_bid_obj.amount
            
            if current_highest_bid_val is None: # Should not happen if auction_minimum_bid is required
                messages.error(request, "Auction configuration error: Cannot determine current bid baseline.")
                return redirect('artworks:auction_bidding_page', artwork_slug=artwork_locked.slug)

            if bid_amount <= current_highest_bid_val:
                messages.error(request, f"Your bid of ${bid_amount:.2f} must be higher than the current bid of ${current_highest_bid_val:.2f}.")
                return redirect('artworks:auction_bidding_page', artwork_slug=artwork_locked.slug)
            # No need for artwork_locked.auction_minimum_bid check here if current_highest_bid_val already considers it.

            # --- All checks passed, create the bid and update artwork ---
            Bid.objects.create(
                artwork=artwork_locked, bidder=request.user, amount=bid_amount, timestamp=now 
            )
            
            artwork_locked.auction_current_highest_bid = bid_amount
            artwork_locked.auction_current_highest_bidder = request.user
            artwork_locked.last_bid_time = now
            
            updated_fields_for_artwork = ['auction_current_highest_bid', 'auction_current_highest_bidder', 'last_bid_time']

            # Soft close logic: If the bid extends the auction
            soft_close_extension = timedelta(seconds=3 * 60) # 3 minutes
            new_potential_end_time = now + soft_close_extension

            if artwork_locked.auction_scheduled_end_time is None or new_potential_end_time > artwork_locked.auction_scheduled_end_time :
                 # This condition means: either the auction was about to end (now is close to scheduled_end_time)
                 # OR this bid is creating a new, later end time due to soft close.
                 artwork_locked.auction_scheduled_end_time = new_potential_end_time
                 updated_fields_for_artwork.append('auction_scheduled_end_time')
                 messages.info(request, f"Auction extended due to your bid! New end time: {artwork_locked.auction_scheduled_end_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                 print(f"Soft close triggered by bid. New scheduled end for {artwork_locked.title}: {artwork_locked.auction_scheduled_end_time}")
            
            artwork_locked.save(update_fields=updated_fields_for_artwork)
            messages.success(request, f"Your bid of ${bid_amount:.2f} has been placed successfully!")
            print(f"Bid of {bid_amount} by {request.user.username} PLACED on {artwork_locked.title}")

            # --- Check if auction should end NOW (after this bid made it the LATEST action) ---
            # The auction effectively ends if `now` (the time of this bid) is >= the `artwork_locked.auction_scheduled_end_time`
            # that was in place *before* this bid potentially extended it.
            # However, the critical check is: if (now >= effective_end_time as determined by this bid's last_bid_time)
            
            # The auction ends if current time `now` is >= `artwork_locked.last_bid_time + soft_close_extension`
            # No, this is not right. The auction ends if no new bid arrives before artwork_locked.last_bid_time + soft_close_extension
            # This view has just PLACED a bid. So the auction is, by definition, NOT ending with THIS action alone
            # unless this bid was placed EXACTLY at the `effective_end_time` and somehow that time didn't get extended.
            # The `auction_bidding_page_view` upon next load, or a background task, is better for timed-out finalization.

            # For now, we don't call finalize_auction() here directly after placing a bid.
            # The next time auction_bidding_page_view loads, it will check if effective_end_time has passed.
            # Or, a winning bid might be determined if this bid was placed *after* the previously calculated effective_end_time
            # (meaning the auction should have already closed but this bid is coming in late - which should be prevented by status check).

        else: 
            messages.error(request, "Invalid bid amount submitted. Please enter a valid number.")
            print(f"Invalid bid form submission: {form.errors.as_json()}")
        
        return redirect('artworks:auction_bidding_page', artwork_slug=artwork_locked.slug)
    else:
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    
    