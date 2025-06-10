# artworks/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from .models import Artwork, Comment, Transaction, GallerySetting, UserProfile, AuctionRegistration # AuctionRegistration Added
from .forms import (CommentForm, GuestCommentForm, ArtworkDirectSaleForm, 
                    DekontUploadForm, UserProfileForm,
                    ArtworkAuctionSettingsForm)
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q

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

