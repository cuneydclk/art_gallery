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

def artwork_detail_view(request, slug):
    artwork_obj = get_object_or_404(Artwork, slug=slug) # Use a distinct name

    # Always ensure status is up-to-date before any logic or rendering
    artwork_obj.get_effective_auction_status_and_save()
    # Re-fetch because get_effective_auction_status_and_save might have saved changes
    artwork = get_object_or_404(Artwork, pk=artwork_obj.pk)

    comments = artwork.comments.all().order_by('-created_at')

    print(f"--- artwork_detail_view for slug: {slug}, Method: {request.method} ---")
    print(f"Artwork current auction status (after effective check): {artwork.auction_status}")

    comment_form_initial = CommentForm() if request.user.is_authenticated else None
    guest_comment_form_initial = GuestCommentForm()
    direct_sale_form_initial = None
    auction_settings_form_initial = None

    if request.user.is_authenticated and request.user == artwork.current_owner:
        direct_sale_form_initial = ArtworkDirectSaleForm(instance=artwork)
        auction_settings_form_initial = ArtworkAuctionSettingsForm(instance=artwork)

    # These will hold the forms to be rendered (possibly with errors from a previous POST)
    comment_form_to_render = comment_form_initial
    guest_comment_form_to_render = guest_comment_form_initial
    direct_sale_form_to_render = direct_sale_form_initial
    auction_settings_form_to_render = auction_settings_form_initial

    if request.method == 'POST':
        print(f"POST data: {request.POST}")

        if 'submit_comment' in request.POST:
            print("Processing: submit_comment")
            form_processor = CommentForm(request.POST) if request.user.is_authenticated else GuestCommentForm(request.POST)
            if form_processor.is_valid():
                new_comment = form_processor.save(commit=False)
                new_comment.artwork = artwork
                if request.user.is_authenticated:
                    new_comment.user = request.user
                new_comment.save()
                messages.success(request, 'Your comment has been posted!')
                return redirect('artworks:artwork_detail', slug=artwork.slug)
            else:
                messages.error(request, 'There was an error posting your comment.')
                if request.user.is_authenticated:
                    comment_form_to_render = form_processor
                else:
                    guest_comment_form_to_render = form_processor

        elif 'submit_sale_settings' in request.POST and request.user.is_authenticated and request.user == artwork.current_owner:
            print("Processing: submit_sale_settings")
            form_processor = ArtworkDirectSaleForm(request.POST, instance=artwork)
            if form_processor.is_valid():
                updated_artwork_instance = form_processor.save(commit=False)
                # Model's save method will handle turning off auction if direct sale is enabled.
                updated_artwork_instance.save()
                messages.success(request, 'Direct sale settings updated successfully!')
                return redirect('artworks:artwork_detail', slug=updated_artwork_instance.slug) # Use slug from saved instance
            else:
                messages.error(request, 'Error updating direct sale settings.')
                direct_sale_form_to_render = form_processor

        elif 'submit_auction_settings' in request.POST and request.user.is_authenticated and request.user == artwork.current_owner:
            print("Processing: submit_auction_settings")
            form_processor = ArtworkAuctionSettingsForm(request.POST, instance=artwork)
            if form_processor.is_valid():
                updated_artwork_instance = form_processor.save(commit=False)

                # The model's save() method will:
                # 1. Turn off direct sale if is_for_auction is true.
                # 2. Calculate auction_signup_deadline.
                # 3. Set auction_status to 'configured' (if new/draft and times are valid) or 'draft' (if times invalid).
                updated_artwork_instance.save()
                print(f"Artwork saved. Status after model save: '{updated_artwork_instance.auction_status}', "
                      f"Signup Deadline: {updated_artwork_instance.auction_signup_deadline}")

                # Now, call get_effective_auction_status_and_save() to transition based on time
                # (e.g., from 'configured' to 'signup_open').
                final_status = updated_artwork_instance.get_effective_auction_status_and_save()
                print(f"Status after get_effective_auction_status_and_save: '{final_status}'")

                messages.success(request, f'Auction settings updated. New status: {updated_artwork_instance.get_auction_status_display()}')
                return redirect('artworks:artwork_detail', slug=updated_artwork_instance.slug) # Use slug from saved instance
            else:
                print(f"Auction form IS INVALID. Errors: {form_processor.errors.as_json(escape_html=True)}")
                messages.error(request, 'Error updating auction settings. Please check the details provided.')
                auction_settings_form_to_render = form_processor
        else:
            print("POST request, but no recognized submit button or user not owner/authenticated.")

    # For GET request or if POST didn't redirect, prepare context with fresh data
    # (artwork was already re-fetched at the beginning of the view after the initial effective status check)
    user_can_register_for_this_auction = artwork.can_user_register_for_auction(request.user) if request.user.is_authenticated else False
    user_auction_registration_on_this_artwork = artwork.get_user_auction_registration(request.user) if request.user.is_authenticated else None

    context = {
        'artwork': artwork,
        'comments': comments,
        'comment_form': comment_form_to_render,
        'guest_comment_form': guest_comment_form_to_render,
        'direct_sale_form': direct_sale_form_to_render,
        'auction_settings_form': auction_settings_form_to_render,
        'page_title': artwork.title,
        'user_can_register_for_this_auction': user_can_register_for_this_auction,
        'user_auction_registration_on_this_artwork': user_auction_registration_on_this_artwork,
    }
    print(f"--- Context for template: Artwork Status: {artwork.auction_status}, Can register: {user_can_register_for_this_auction} ---")
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
    artwork_obj = get_object_or_404(Artwork, slug=artwork_slug)
    
    # Initial status update
    artwork_obj.get_effective_auction_status_and_save()
    artwork = get_object_or_404(Artwork, pk=artwork_obj.pk) # Re-fetch
    current_artwork_status_at_load = str(artwork.auction_status) # Save for logging
    
    print(f"\n[VIEW DEBUG {request.user.username} @ {timezone.now()}] ===== BIDDING PAGE LOAD =====")
    print(f"[VIEW DEBUG] Artwork: '{artwork.title}', Initial Effective Status: '{current_artwork_status_at_load}'")

    now = timezone.now()
    effective_end_time = artwork.auction_scheduled_end_time
    print(f"[VIEW DEBUG] Server Time (now): {now}, Effective End Time: {effective_end_time}")

    if not artwork.is_for_auction:
        messages.info(request, f"The auction for '{artwork.title}' is no longer active.")
        print(f"[VIEW DEBUG] Redirecting: Auction '{artwork.title}' is_for_auction=False.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)
    
    if not effective_end_time and current_artwork_status_at_load == 'live':
        messages.error(request, f"Configuration Error: Auction '{artwork.title}' is live but has no scheduled end time.")
        print(f"[VIEW DEBUG] Redirecting: Auction '{artwork.title}' live but no effective_end_time.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    # --- Attempt to finalize if time has passed and auction was live ---
    if current_artwork_status_at_load == 'live' and effective_end_time and now >= effective_end_time:
        print(f"[VIEW DEBUG] Auction Time UP for '{artwork.title}'. Entering FINALIZE BLOCK.")
        print(f"[VIEW DEBUG]   User: {request.user.username}, Request Path: {request.path}")
        
        finalization_details = None # Initialize
        with db_transaction.atomic():
            artwork_to_finalize = Artwork.objects.select_for_update().get(pk=artwork.pk)
            print(f"[VIEW DEBUG]   Locked Artwork '{artwork_to_finalize.title}'. Status before re-check: '{artwork_to_finalize.auction_status}'")

            if artwork_to_finalize.auction_status == 'live' and \
               artwork_to_finalize.auction_scheduled_end_time and \
               timezone.now() >= artwork_to_finalize.auction_scheduled_end_time:
                
                print(f"[VIEW DEBUG]   Conditions MET for finalization inside lock. Calling finalize_auction().")
                finalization_details = artwork_to_finalize.finalize_auction()
                artwork = artwork_to_finalize 
                print(f"[VIEW DEBUG]   finalize_auction() COMPLETED. Outcome: {finalization_details.get('outcome')}, "
                      f"New Artwork Status: '{artwork.auction_status}', is_for_auction: {artwork.is_for_auction}")
            else:
                artwork = artwork_to_finalize 
                print(f"[VIEW DEBUG]   Conditions for finalization NOT MET inside lock or already finalized by another process.")
                print(f"[VIEW DEBUG]     Locked Artwork Status: '{artwork.auction_status}', Scheduled End: '{artwork.auction_scheduled_end_time}', Now: '{timezone.now()}'")
                if artwork.auction_status != 'live':
                    finalization_details = {'outcome': 'already_concluded_by_another_process'}

        if finalization_details:
            outcome = finalization_details.get('outcome')
            print(f"[VIEW DEBUG] Processing finalize_auction outcome: '{outcome}' for user '{request.user.username}'")
            
            # THIS IS THE BLOCK WITH THE NEW DEBUG LINES
            if outcome == 'winner_found':
                transaction_obj = finalization_details.get('transaction')
                winner_from_details = finalization_details.get('winner') 
                price = finalization_details.get('price')
                
                print(f"[VIEW DEBUG WINNER CHECK] Outcome is 'winner_found'.") # <<< NEW
                print(f"[VIEW DEBUG WINNER CHECK]   finalization_details winner: {winner_from_details} (type: {type(winner_from_details)})") # <<< NEW
                if winner_from_details:
                    print(f"[VIEW DEBUG WINNER CHECK]   finalization_details winner ID: {winner_from_details.id}") # <<< NEW
                print(f"[VIEW DEBUG WINNER CHECK]   request.user: {request.user} (type: {type(request.user)})") # <<< NEW
                if request.user.is_authenticated:
                    print(f"[VIEW DEBUG WINNER CHECK]   request.user ID: {request.user.id}") # <<< NEW
                print(f"[VIEW DEBUG WINNER CHECK]   request.user.is_authenticated: {request.user.is_authenticated}") # <<< NEW

                msg_for_redirect = f"Auction for '{artwork.title}' ended! Winner: {winner_from_details.username if winner_from_details else 'N/A'}."
                
                if request.user.is_authenticated and winner_from_details and winner_from_details.id == request.user.id:
                    print(f"[VIEW DEBUG WINNER CHECK]   User IS winner. Preparing redirect to payment.") # <<< NEW
                    msg_for_redirect += " Congratulations! Please proceed to payment."
                    messages.success(request, msg_for_redirect)
                    if transaction_obj:
                        print(f"[VIEW DEBUG WINNER CHECK]   REDIRECTING WINNER '{request.user.username}' to payment page for TxID: {transaction_obj.id}.") # <<< NEW
                        return redirect('artworks:payment_and_dekont_upload', transaction_id=transaction_obj.id)
                    else:
                         print(f"[VIEW DEBUG WINNER CHECK ERROR]   Winner path, but transaction_obj is None! Redirecting to artwork detail.") # <<< NEW
                         messages.error(request, "Error in auction finalization (tx missing for winner). Contact support.")
                         return redirect('artworks:artwork_detail', slug=artwork.slug)
                else:
                    print(f"[VIEW DEBUG WINNER CHECK]   User IS NOT winner (or issue with objects). Redirecting non-winner/observer.") # <<< NEW
                    msg_for_redirect += " Awaiting payment from winner."
                    messages.success(request, msg_for_redirect)
                    return redirect('artworks:artwork_detail', slug=artwork.slug)
            
            elif outcome == 'no_bids':
                messages.info(request, f"Auction for '{artwork.title}' ended: {finalization_details.get('message', 'No valid bids.')}")
                print(f"[VIEW DEBUG]   NO_BIDS block. Redirecting to artwork detail.")
                return redirect('artworks:artwork_detail', slug=artwork.slug)

            elif outcome == 'transaction_error':
                messages.error(request, f"Auction for '{artwork.title}' ended with an issue: {finalization_details.get('message', 'Please contact support.')}")
                print(f"[VIEW DEBUG]   TRANSACTION_ERROR block. Redirecting to artwork detail.")
                return redirect('artworks:artwork_detail', slug=artwork.slug)
            
            elif outcome == 'already_concluded_by_another_process':
                print(f"[VIEW DEBUG]   ALREADY_CONCLUDED_BY_ANOTHER_PROCESS. Will proceed to post-finalization checks.")
            
            else: 
                print(f"[VIEW DEBUG]   UNHANDLED finalize_auction outcome: '{outcome}'. Message: {finalization_details.get('message')}")
        else: 
            print(f"[VIEW DEBUG]   Finalize_auction was effectively SKIPPED inside lock (e.g. status was not live when checked with lock).")

    current_artwork_status_for_render = str(artwork.auction_status)
    print(f"[VIEW DEBUG] POST-FINALIZE BLOCK / PRE-RENDER for user '{request.user.username}'. Artwork Status: '{current_artwork_status_for_render}'")

    if current_artwork_status_for_render == 'not_configured' and artwork.is_for_auction is False:
        print(f"[VIEW DEBUG]   Artwork is 'not_configured' and not for auction (auction concluded).")
        
        if request.user.is_authenticated:
            print(f"[VIEW DEBUG]   Checking for winning transaction for user '{request.user.username}'...")
            last_win_transaction = Transaction.objects.filter(
                artwork=artwork, buyer=request.user, sale_type='auction_win', status='pending_payment'
            ).order_by('-initiated_at').first()

            if last_win_transaction:
                print(f"[VIEW DEBUG]   WINNING TRANSACTION FOUND (TxID: {last_win_transaction.id}) for user '{request.user.username}'.")
                has_proceed_to_payment_msg = any("Proceed to payment" in m.message for m in messages.get_messages(request))
                if not has_proceed_to_payment_msg:
                     messages.success(request, f"Congratulations! You won the auction for '{artwork.title}'. Please complete your payment.")
                print(f"[VIEW DEBUG]   REDIRECTING WINNER (post-finalize check) '{request.user.username}' to payment page.")
                return redirect('artworks:payment_and_dekont_upload', transaction_id=last_win_transaction.id)
            else:
                print(f"[VIEW DEBUG]   No PENDING winning transaction found for user '{request.user.username}'.")
        
        has_any_end_message = any(m.level >= messages.INFO for m in messages.get_messages(request)) 
        if not has_any_end_message:
            generic_concluded_msg = f"The auction for '{artwork.title}' has concluded (Status: {artwork.get_auction_status_display()})."
            messages.info(request, generic_concluded_msg)
            print(f"[VIEW DEBUG]   Added generic concluded message: \"{generic_concluded_msg}\"")
        else:
            print(f"[VIEW DEBUG]   Skipping generic concluded message as other messages exist.")
            
        print(f"[VIEW DEBUG]   Redirecting to artwork detail page (auction concluded).")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    if current_artwork_status_for_render != 'live':
        print(f"[VIEW DEBUG]   Artwork status is '{current_artwork_status_for_render}' (not 'live'). Redirecting to artwork detail.")
        if not messages.get_messages(request):
            messages.info(request, f"The auction for '{artwork.title}' is not currently live (Status: {artwork.get_auction_status_display()}).")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    print(f"[VIEW DEBUG] Auction '{artwork.title}' is LIVE. Preparing rendering context.")
    user_registration = artwork.get_user_auction_registration(request.user)
    is_approved_attendee = user_registration and user_registration.status == 'approved'
    is_owner = artwork.current_owner == request.user
    print(f"[VIEW DEBUG]   Permissions: approved_attendee={is_approved_attendee}, is_owner={is_owner}")

    if not is_approved_attendee and not is_owner:
        messages.error(request, "You are not an approved attendee for this auction.")
        print(f"[VIEW DEBUG]   User not approved and not owner. Redirecting to artwork detail.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    current_highest_bid = artwork.auction_current_highest_bid
    highest_bidder_username = artwork.auction_current_highest_bidder.username if artwork.auction_current_highest_bidder else None
    min_next_bid = current_highest_bid + Decimal('1.00') if current_highest_bid else artwork.auction_minimum_bid
    if min_next_bid is None: min_next_bid = Decimal('0.01')

    bid_form = None
    if is_approved_attendee and not is_owner:
        bid_form = PlaceBidForm(initial={'bid_amount': min_next_bid.quantize(Decimal('0.01'))})
        
    time_remaining_seconds = max(0, int((effective_end_time - now).total_seconds())) if effective_end_time and now < effective_end_time else 0
    # Calculate soft close only if effective_end_time is set
    is_soft_close_active = False 
    if effective_end_time and artwork.last_bid_time: # THIS IS THE OLD LOGIC
        soft_close_extension_seconds = 30 # <<< CHANGED FROM 3 * 60
        potential_soft_close_end = artwork.last_bid_time + timedelta(seconds=soft_close_extension_seconds)
        if potential_soft_close_end > effective_end_time:
            effective_end_time = potential_soft_close_end # Update effective_end_time for this request
            is_soft_close_active = True
    print(f"[DEBUG] Calculated effective_end_time for '{artwork.title}': {effective_end_time}")
    
    quick_bids = []
    if is_approved_attendee and not is_owner and min_next_bid:
        base = min_next_bid
        increments = [Decimal('0'), Decimal('10'), Decimal('50'), Decimal('100')]
        temp_bids_list = [] 
        for inc in increments:
            potential_bid = (base + inc).quantize(Decimal('0.01'))
            if current_highest_bid and potential_bid <= current_highest_bid:
                if inc == Decimal('0'): 
                    potential_bid = (current_highest_bid + Decimal('10')).quantize(Decimal('0.01'))
                else: continue 
            if potential_bid not in temp_bids_list : temp_bids_list.append(potential_bid)
        quick_bids = sorted(list(set(temp_bids_list)))[:4]

    context = {
        'artwork': artwork, 'bid_form': bid_form,
        'current_highest_bid': current_highest_bid,
        'current_highest_bidder_username': highest_bidder_username,
        'min_next_bid': min_next_bid,
        'is_approved_attendee': is_approved_attendee, 'is_owner': is_owner,
        'time_remaining_seconds': time_remaining_seconds,
        'auction_end_message': None, 
        'is_soft_close_active': is_soft_close_active,
        'effective_end_time_for_display': effective_end_time,
        'quick_bid_amounts': quick_bids,
        'page_title': f"Live Bidding: {artwork.title}"
    }
    print(f"[VIEW DEBUG] Rendering bidding page for '{artwork.title}'. Time Rem: {time_remaining_seconds}s")
    print(f"[VIEW DEBUG] ===== BIDDING PAGE RENDER END =====\n")
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
            soft_close_extension = timedelta(seconds=30) # 30 seconds
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
def auction_bidding_page_view(request, artwork_slug): # MODIFIED FOR FIX
    print(f"[DEBUG] 0. Entered auction_bidding_page_view for slug: {artwork_slug}")
    artwork = get_object_or_404(Artwork, slug=artwork_slug)
    
    artwork.get_effective_auction_status_and_save() # Update status first
    artwork = Artwork.objects.get(pk=artwork.pk) # Re-fetch for freshest data
    current_artwork_status = artwork.auction_status # This is the status from DB after effective check
    print(f"[DEBUG] 1. Initial status for '{artwork.title}': {current_artwork_status}")

    now = timezone.now()
    print(f"[DEBUG] Server 'now': {now}")

    effective_end_time = artwork.auction_scheduled_end_time
    if not effective_end_time and current_artwork_status == 'live': # Check if live AND missing end time
        messages.error(request, f"Configuration Error for '{artwork.title}': Live auction is missing its scheduled end time.")
        print(f"[DEBUG] Config Error: Live auction '{artwork.title}' missing scheduled_end_time.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    # Calculate soft close only if effective_end_time is set
    is_soft_close_active = False 
    if effective_end_time and artwork.last_bid_time:
        soft_close_extension_seconds = 30 
        potential_soft_close_end = artwork.last_bid_time + timedelta(seconds=soft_close_extension_seconds)
        if potential_soft_close_end > effective_end_time:
            effective_end_time = potential_soft_close_end # Update effective_end_time for this request
            is_soft_close_active = True
    print(f"[DEBUG] Calculated effective_end_time for '{artwork.title}': {effective_end_time}")


    # --- Attempt to finalize if time has passed and auction was live ---
    if current_artwork_status == 'live' and effective_end_time and now >= effective_end_time:
        print(f"[DEBUG] 5. ENTERED FINALIZE BLOCK for '{artwork.title}': now ({now}) >= effective_end_time ({effective_end_time}) is TRUE.")
        
        finalization_details = artwork.finalize_auction() 
        # `artwork` instance is modified by finalize_auction (is_for_auction=False, status='not_configured')
        # `finalization_details` is the dictionary returned by finalize_auction.

        print(f"[DEBUG] 6. Status of artwork object after finalize_auction call: '{artwork.auction_status}'") 
        print(f"[DEBUG] 6a. Details returned by finalize_auction(): {finalization_details}")

        outcome_type = finalization_details.get('outcome')

        if outcome_type == 'winner_found':
            transaction_obj = finalization_details.get('transaction')
            winner_user_obj = finalization_details.get('winner') 
            
            if not transaction_obj or not winner_user_obj:
                messages.error(request, f"Auction for '{artwork.title}' ended, but there was an error processing the result. Please contact support.")
                print(f"[DEBUG] Critical Error: 'winner_found' but transaction_obj ({transaction_obj}) or winner_user_obj ({winner_user_obj}) is missing.")
                return redirect('artworks:artwork_detail', slug=artwork.slug)

            winner_username = winner_user_obj.username
            msg_for_redirect = f"Auction for '{artwork.title}' has ended! Winner: {winner_username}."
            
            if request.user.is_authenticated and request.user.id == winner_user_obj.id:
                msg_for_redirect += " Congratulations! Please proceed to payment."
                messages.success(request, msg_for_redirect)
                print(f"[DEBUG] Finalize Block: Redirecting WINNER {request.user.username} to payment page for TxID: {transaction_obj.id}.")
                return redirect('artworks:payment_and_dekont_upload', transaction_id=transaction_obj.id)
            else:
                msg_for_redirect += " Awaiting payment from winner."
                messages.success(request, msg_for_redirect)
                print(f"[DEBUG] Finalize Block: Redirecting NON-WINNER/OBSERVER '{request.user.username if request.user.is_authenticated else 'Anonymous'}' to artwork detail for '{artwork.title}'.")
                return redirect('artworks:artwork_detail', slug=artwork.slug)
        
        elif outcome_type == 'no_bids':
            messages.info(request, f"Auction for '{artwork.title}' ended: {finalization_details.get('message', 'No valid bids met the criteria.')}")
            print(f"[DEBUG] Finalize Block: Outcome 'no_bids' for '{artwork.title}'. Redirecting to artwork detail.")
            return redirect('artworks:artwork_detail', slug=artwork.slug)
        
        elif outcome_type == 'transaction_error':
             messages.error(request, f"Auction for '{artwork.title}' ended with a transaction processing issue: {finalization_details.get('message', 'Please contact support.')}")
             print(f"[DEBUG] Finalize Block: Outcome 'transaction_error' for '{artwork.title}'. Redirecting to artwork detail.")
             return redirect('artworks:artwork_detail', slug=artwork.slug)
        
        elif outcome_type == 'already_concluded':
            messages.info(request, f"The auction for '{artwork.title}' appears to have already concluded or was not live when checked for finalization.")
            print(f"[DEBUG] Finalize Block: Outcome 'already_concluded' for '{artwork.title}'. Redirecting to artwork detail.")
            return redirect('artworks:artwork_detail', slug=artwork.slug)
        
        else: 
             print(f"[DEBUG] Warning: finalize_auction for '{artwork.title}' returned an unexpected outcome: '{outcome_type}'. "
                   f"Message: {finalization_details.get('message')}. Current artwork status from object: {artwork.auction_status}")
    else: 
        print(f"[DEBUG] 5. SKIPPED FINALIZE BLOCK for '{artwork.title}'.")
        if current_artwork_status != 'live': print(f"  - Reason: Status is '{current_artwork_status}', not 'live'.")
        if effective_end_time and now < effective_end_time: print(f"  - Reason: now ({now}) < effective_end_time ({effective_end_time}). Remaining: {effective_end_time - now}")
    
    # --- Post-Finalization Check & Permission Logic ---
    current_artwork_status_for_render = artwork.auction_status 
    print(f"[DEBUG] 7. Status before render/permission checks for '{artwork.title}': {current_artwork_status_for_render}")

    if current_artwork_status_for_render == 'not_configured' and not artwork.is_for_auction: 
        print(f"[DEBUG] Post-finalize state: Status is 'not_configured' and is_for_auction=False for '{artwork.title}'. This means auction concluded.")
        
        if request.user.is_authenticated:
            winning_transaction = Transaction.objects.filter(
                artwork=artwork, buyer=request.user, sale_type='auction_win', status='pending_payment'
            ).order_by('-initiated_at').first()

            if winning_transaction:
                has_congrats_message = any("Congratulations! You won the auction" in m.message for m in messages.get_messages(request))
                if not has_congrats_message:
                    messages.success(request, f"Congratulations! You won the auction for '{artwork.title}'. Please proceed to payment.")
                print(f"[DEBUG] Post-finalize state: Redirecting WINNER {request.user.username} to payment page for TxID: {winning_transaction.id} (found via Transaction query).")
                return redirect('artworks:payment_and_dekont_upload', transaction_id=winning_transaction.id)
            else:
                print(f"[DEBUG] Post-finalize state: User {request.user.username} is not the winner with a PENDING payment for '{artwork.title}'.")
        
        has_any_relevant_message = any(m.level >= messages.INFO for m in messages.get_messages(request))
        if not has_any_relevant_message:
            messages.info(request, f"The auction for '{artwork.title}' has concluded.")
        
        print(f"[DEBUG] Post-finalize state: Redirecting to artwork detail page for '{artwork.title}' (general concluded path).")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    if current_artwork_status_for_render != 'live':
        print(f"[DEBUG] 8. Redirecting from bidding page for '{artwork.title}' as status '{current_artwork_status_for_render}' is not 'live'.")
        has_any_message = any(m.level >= messages.INFO for m in messages.get_messages(request))
        if not has_any_message:
            messages.info(request, f"The auction for '{artwork.title}' is not currently active for bidding (Status: {artwork.get_auction_status_display()}).")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    # --- If we reach here, auction is 'live' for rendering ---
    # --- Define permission variables BEFORE using them ---
    user_registration = None
    is_approved_attendee = False
    is_owner = False 

    if request.user.is_authenticated: 
        user_registration = artwork.get_user_auction_registration(request.user)
        is_approved_attendee = user_registration and user_registration.status == 'approved'
        is_owner = artwork.current_owner == request.user
    
    print(f"[DEBUG] 9. Permissions for '{artwork.title}': approved_attendee={is_approved_attendee}, is_owner={is_owner}, user_authenticated={request.user.is_authenticated}")

    if not is_approved_attendee and not is_owner: 
        print(f"[DEBUG] 10. Redirecting from bidding page for '{artwork.title}' (not approved and not owner)")
        if request.user.is_authenticated:
            messages.error(request, "You are not an approved attendee for this auction.")
        else:
            messages.info(request, f"Please log in to participate. The auction for '{artwork.title}' is currently live.")
        return redirect('artworks:artwork_detail', slug=artwork.slug)

    # --- Prepare for Rendering Live Bidding Page ---
    current_highest_bid_amount = artwork.auction_current_highest_bid
    current_highest_bidder_user_obj = artwork.auction_current_highest_bidder
    
    min_next_bid = None
    if current_highest_bid_amount is not None:
        min_next_bid = current_highest_bid_amount + Decimal('1.00')
    elif artwork.auction_minimum_bid is not None:
        min_next_bid = artwork.auction_minimum_bid
    else: # Fallback if somehow minimum_bid is also None (should not happen for live auction)
        min_next_bid = Decimal('1.00') 
    
    bid_form = None
    auction_end_message = None 
    time_remaining_seconds = 0 

    if is_approved_attendee and not is_owner: # Bid form only for approved, non-owner bidders on a live auction
        form_initial_bid = min_next_bid.quantize(Decimal('0.01'))
        bid_form = PlaceBidForm(initial={'bid_amount': form_initial_bid })
    
    if effective_end_time and now < effective_end_time: 
         current_time_remaining_delta = effective_end_time - now
         time_remaining_seconds = max(0, int(current_time_remaining_delta.total_seconds()))
             
    quick_bid_amounts = [] 
    if min_next_bid is not None and is_approved_attendee and not is_owner: 
        base_for_quick_bids_val = min_next_bid
        temp_bids = [
            base_for_quick_bids_val,
            base_for_quick_bids_val + Decimal('10.00'),
            base_for_quick_bids_val + Decimal('50.00'),
            base_for_quick_bids_val + Decimal('100.00')
        ]
        valid_quick_bids = []
        auction_abs_min_bid = artwork.auction_minimum_bid if artwork.auction_minimum_bid is not None else Decimal('0.01')
        current_high_for_check = artwork.auction_current_highest_bid if artwork.auction_current_highest_bid is not None else Decimal('-1.00')

        for qb_decimal in sorted(list(set(temp_bids))):
            if qb_decimal > current_high_for_check and qb_decimal >= auction_abs_min_bid:
                valid_quick_bids.append(qb_decimal.quantize(Decimal('0.01')))
        quick_bid_amounts = valid_quick_bids[:4]
    
    print(f"[DEBUG] 11. Preparing to render bidding page for '{artwork.title}'. Status: {current_artwork_status_for_render}, Time Rem: {time_remaining_seconds}s, BidForm: {'Yes' if bid_form else 'No'}")
    
    context = {
        'artwork': artwork, 
        'bid_form': bid_form, 
        'current_highest_bid': current_highest_bid_amount, 
        'current_highest_bidder_username': current_highest_bidder_user_obj.username if current_highest_bidder_user_obj else None,
        'min_next_bid': min_next_bid, 
        'is_approved_attendee': is_approved_attendee, 
        'is_owner': is_owner,
        'time_remaining_seconds': time_remaining_seconds, 
        'auction_end_message': auction_end_message,
        'is_soft_close_active': is_soft_close_active, 
        'effective_end_time_for_display': effective_end_time, 
        'quick_bid_amounts': quick_bid_amounts, 
        'page_title': f"Live Bidding: {artwork.title}"
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
            soft_close_extension = timedelta(seconds=30) # 30 seconds
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
    
    