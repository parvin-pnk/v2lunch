from flask import Flask, render_template, request, redirect, url_for, session, flash,jsonify,make_response
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime,timedelta
import os
from bson.objectid import ObjectId
from dotenv import load_dotenv
from math import ceil

import secrets
import string

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
import io

from flask_mail import Mail,Message
# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))

# Add to your configuration section
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER') # e.g., smtp.gmail.com
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT')
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS')
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('EMAIL_USER')

# Initialize Flask-Mail
mail = Mail(app)

# MongoDB connection setup
mongodb_uri = os.getenv('MONGODB_URI', 'mongodb+srv://default:password@cluster0.mongodb.net/food_delivery?retryWrites=true&w=majority')
client = MongoClient(mongodb_uri)
db = client.get_database('food_delivery')


# Helper functions
def calculate_cart_total():
    return sum(item['price'] * item['quantity'] for item in session.get('cart', []))

def is_user_logged_in():
    return 'user_id' in session

def validate_cart_has_main_dish():
    return any(item['type'] == 'main' for item in session.get('cart', []))

def is_today_available():
    current_hour = datetime.now().hour
    return current_hour < 10  # Today available only before 10 AM
def calculate_cart_total():
    if 'cart' not in session:
        return 0
    return sum(item['price'] * item['quantity'] for item in session['cart'])

#Routes for data and time

@app.context_processor
def utility_processor():
    return {
        'calculate_cart_total': calculate_cart_total,
        'is_today_available': is_today_available,
        'datetime': datetime,
        'timedelta': timedelta
    }

@app.route('/remove-from-cart', methods=['POST'])
def remove_from_cart():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        item_type = data.get('item_type')
        
        if not item_id or not item_type:
            return jsonify({'success': False, 'message': 'Invalid request'}), 400
        
        # Remove item from cart
        if 'cart' in session:
            session['cart'] = [item for item in session['cart'] 
                             if not (item['id'] == item_id and item['type'] == item_type)]
            session.modified = True
            
            # Calculate new subtotal
            subtotal = sum(item['price'] * item['quantity'] for item in session.get('cart', []))
            
            return jsonify({
                'success': True,
                'subtotal': subtotal,
                'cart_count': len(session.get('cart', []))
            })
            
    except Exception as e:
        app.logger.error(f"Error removing item from cart: {str(e)}")
        return jsonify({'success': False, 'message': 'Server error'}), 500

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d/%m/%y %I:%M %p'):
    if isinstance(value, str):
        try:
            # Handle different possible input formats
            try:
                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    value = datetime.strptime(value, '%Y-%m-%d %H:%M')
                except ValueError:
                    value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(format)

@app.template_filter('format_time')
def format_time(value, format='%I:%M %p'):
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%H:%M:%S')
        except ValueError:
            try:
                value = datetime.strptime(value, '%H:%M')
            except ValueError:
                return value
    return value.strftime(format)


# Routes

@app.template_filter('format_time')
def format_time(value, format='%H:%M'):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(format)

@app.route('/', methods=['GET', 'POST'])
def home():
    try:
        # Initialize cart if not exists
        if 'cart' not in session:
            session['cart'] = []
            app.logger.debug("Initialized new cart in session")

        # Handle POST request (adding items to cart)
        if request.method == 'POST':
            if not is_user_logged_in():
                flash('Please login to continue', 'warning')
                app.logger.warning("Unauthenticated user attempted to add to cart")
                return redirect(url_for('login'))
            
            # Process selected main dishes
            selected_mains = request.form.getlist('main_dishes')
            app.logger.debug(f"Selected mains: {selected_mains}")

            if not selected_mains:
                flash('Please select at least one item', 'warning')
                return redirect(url_for('home'))

            for item_id in selected_mains:
                try:
                    quantity = int(request.form.get(f'main_quantity_{item_id}', 1))
                    app.logger.debug(f"Processing item {item_id} with quantity {quantity}")

                    # Validate ObjectId format
                    if not ObjectId.is_valid(item_id):
                        app.logger.error(f"Invalid ObjectId format: {item_id}")
                        continue

                    item = db.dishes.find_one({"_id": ObjectId(item_id)})
                    
                    if not item:
                        app.logger.warning(f"Item not found in database: {item_id}")
                        continue

                    # Check if item already in cart
                    existing_item = next(
                        (i for i in session['cart'] if i['id'] == str(item['_id'])), 
                        None
                    )

                    if existing_item:
                        existing_item['quantity'] += quantity
                        app.logger.debug(f"Incremented quantity for item {item_id}")
                    else:
                        cart_item = {
                            "id": str(item['_id']),
                            "name": item['name'],
                            "price": float(item['price']),
                            "quantity": quantity,
                            "type": "main",
                            "image": item.get('image', 'default.jpg')  # Added default image
                        }
                        session['cart'].append(cart_item)
                        app.logger.debug(f"Added new item to cart: {item['name']}")

                except ValueError as e:
                    app.logger.error(f"Invalid quantity for item {item_id}: {e}")
                    continue
                except Exception as e:
                    app.logger.error(f"Error processing item {item_id}: {e}")
                    continue

            session.modified = True
            return redirect(url_for('side_dishes'))

        # GET request - show available main dishes
        try:
            # Get only available main dishes, sorted by name
            main_dishes = list(db.dishes.find({
                "is_available": True
            }).sort("name", 1))

            app.logger.info(f"Found {len(main_dishes)} available main dishes")

            if not main_dishes:
                flash('Currently no dishes available. Please check back later!', 'info')
                app.logger.warning("No available dishes found in database")

            return render_template('home.html', 
                               dishes=main_dishes,
                               cart_count=len(session['cart']))

        except Exception as e:
            app.logger.error(f"Database error: {str(e)}")
            flash('Error loading menu. Please try again later.', 'danger')
            return render_template('home.html', dishes=[], cart_count=0)

    except Exception as e:
        app.logger.critical(f"Unexpected error in home route: {str(e)}")
        flash('An unexpected error occurred. Please try again.', 'danger')
        return redirect(url_for('home'))
    
from flask_mail import Message

@app.route('/about')
def about():
    # You can add dynamic content here if needed
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        message = request.form.get('message')
        your_email = "v2lunch@gmail.com"  # Change this to your actual email
        
        # Basic validation
        if not all([name, email, message]):
            flash('Please fill in all required fields', 'danger')
            return redirect(url_for('contact'))
        
        try:
            # Create and send email
            msg = Message(
                subject=f"New Contact Form Submission from {name}",
                recipients=[your_email],
                body=f"""
                Name: {name}
                Email: {email}
                Phone: {phone or 'Not provided'}
                
                Message:
                {message}
                
                Sent from V2Lunch contact form
                """,
                html=f"""
                <h1>New Contact Form Submission</h1>
                <p><strong>Name:</strong> {name}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Phone:</strong> {phone or 'Not provided'}</p>
                <p><strong>Message:</strong></p>
                <p>{message}</p>
                <p><em>Sent from V2Lunch contact form</em></p>
                """
            )
            mail.send(msg)
            
            flash('Thank you for your message! We will contact you soon.', 'success')
            return redirect(url_for('contact'))
        except Exception as e:
            app.logger.error(f"Error sending contact email: {str(e)}")
            flash('Error submitting your message. Please try again.', 'danger')
    
    return render_template('contact.html')



# My Account Page
@app.route('/my-account', methods=['GET', 'POST'])
def my_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.users.find_one({'_id': ObjectId(session['user_id'])})
    
    if request.method == 'POST':
        # Handle profile updates
        if 'update_profile' in request.form:
            db.users.update_one(
                {'_id': ObjectId(session['user_id'])},
                {'$set': {
                    'full_name': request.form.get('full_name'),
                    'phone': request.form.get('phone'),
                    'address': request.form.get('address')
                }}
            )
            flash('Profile updated successfully!', 'success')
        
        # Handle password change
        elif 'change_password' in request.form:
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            
            if check_password_hash(user['password'], current_password):
                db.users.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {'$set': {'password': generate_password_hash(new_password)}}
                )
                flash('Password changed successfully!', 'success')
            else:
                flash('Current password is incorrect', 'danger')
        
        return redirect(url_for('my_account'))
    
    return render_template('my_account.html', user=user)

# Add these routes after your login route
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = db.users.find_one({"email": email})
        
        if user:
            # Generate temporary password
            temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for i in range(8))
            
            # Update user's password in DB
            db.users.update_one(
                {"_id": user['_id']},
                {"$set": {"password": generate_password_hash(temp_password)}}
            )
            
            # Send email
            msg = Message(
                "Your Password Reset",
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[email]
            )
            msg.body = f"Your temporary password is: {temp_password}\n\nPlease change it after logging in."
            mail.send(msg)
            
            flash('A temporary password has been sent to your email', 'success')
            return redirect(url_for('login'))
        
        flash('Email not found', 'danger')
    return render_template('forgot_password.html')

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    if not is_user_logged_in():
        flash('Please login to continue', 'warning')
        return redirect(url_for('login'))
    
    try:
        item_id = request.form.get('item_id')
        item_type = request.form.get('item_type')
        quantity = max(1, int(request.form.get('quantity', 1)))
        
        collection_map = {
            'main': db.dishes,
            'side': db.side_dishes,
            'other': db.other_items
        }
        
        item = collection_map[item_type].find_one({"_id": ObjectId(item_id)})
        
        if not item:
            flash('Item not found', 'danger')
            return redirect(url_for('home'))
        
        cart_item = {
            "id": str(item['_id']),
            "name": item['name'],
            "price": item['price'],
            "quantity": quantity,
            "type": item_type
        }
        
        # For main dish, clear existing main dish in cart
        if item_type == 'main':
            session['cart'] = [ci for ci in session['cart'] if ci['type'] != 'main']
        
        session['cart'].append(cart_item)
        session.modified = True
        
        redirect_routes = {
            'main': 'side_dishes',
            'side': 'other_items',
            'other': 'location'
        }
        
        return redirect(url_for(redirect_routes[item_type]))
    
    except Exception as e:
        flash('An error occurred while adding item to cart', 'danger')
        return redirect(url_for('home'))
    
@app.route('/skip-side-dishes')
def skip_side_dishes():
    return redirect(url_for('other_items'))

@app.route('/side-dishes', methods=['GET', 'POST'])
def side_dishes():
    if not is_user_logged_in():
        return redirect(url_for('login'))
    if not validate_cart_has_main_dish():
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        selected_sides = request.form.getlist('side_dishes')
        for item_id in selected_sides:
            quantity = int(request.form.get(f'side_quantity_{item_id}', 1))
            item = db.side_dishes.find_one({"_id": ObjectId(item_id)})
            if item:
                existing_item = next((i for i in session['cart'] if i['id'] == str(item['_id'])), None)
                if existing_item:
                    existing_item['quantity'] += quantity
                else:
                    cart_item = {
                        "id": str(item['_id']),
                        "name": item['name'],
                        "price": item['price'],
                        "quantity": quantity,
                        "type": "side"
                    }
                    session['cart'].append(cart_item)
        
        session.modified = True
        return redirect(url_for('other_items'))
    
    dishes = list(db.side_dishes.find())
    return render_template('side_dishes.html', dishes=dishes)

@app.route('/other-items', methods=['GET', 'POST'])
def other_items():
    if not is_user_logged_in():
        return redirect(url_for('login'))
    if not validate_cart_has_main_dish():
        return redirect(url_for('home'))

    if request.method == 'POST':
        # Debug print to see what's being submitted
        print("Form data:", request.form)
        
        # Get all selected other items and their quantities
        selected_items = request.form.getlist('other_items')
        print("Selected items:", selected_items)
        
        for item_id in selected_items:
            quantity = int(request.form.get(f'other_quantity_{item_id}', 1))
            item = db.other_items.find_one({"_id": ObjectId(item_id)})
            
            if item:
                print("Adding to cart:", item['name'], "Qty:", quantity)
                cart_item = {
                    "id": str(item['_id']),
                    "name": item['name'],
                    "price": item['price'],
                    "quantity": quantity,
                    "type": "other"  # Make sure type is set to 'other'
                }
                session['cart'].append(cart_item)
                session.modified = True
        
        print("Current cart:", session['cart'])
        return redirect(url_for('select_date'))
    
    items = list(db.other_items.find())
    return render_template('other_items.html', items=items)

@app.route('/update-quantity', methods=['POST'])
def update_quantity():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    
    item_id = request.form.get('item_id')
    item_type = request.form.get('item_type')
    action = request.form.get('action')
    
    # Find the item in the cart
    for item in session['cart']:
        if item['id'] == item_id and item['type'] == item_type:
            if action == 'increase':
                item['quantity'] += 1
            elif action == 'decrease' and item['quantity'] > 1:
                item['quantity'] -= 1
            session.modified = True
            return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': 'Item not found'}), 404

@app.route('/skip-other-items')
def skip_other_items():
    return redirect(url_for('select_date'))




@app.route('/select-date', methods=['GET', 'POST'])
def select_date():
    if not is_user_logged_in():
        return redirect(url_for('login'))
    if not validate_cart_has_main_dish():
        return redirect(url_for('home'))
    
    
    current_time = datetime.now()
    current_hour = current_time.hour
    
    if request.method == 'POST':
        selected_date = request.form.get('delivery_date')
        if not selected_date:
            flash('Please select a delivery date', 'danger')
            return redirect(url_for('select_date'))
        
        session['delivery_date'] = selected_date
        return redirect(url_for('location'))
    
    # Calculate available dates
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    
    # Format dates for display
    date_options = []
    
    # Only show today if before 10 AM
    if current_hour < 10:
        date_options.append({
            'value': today.strftime('%Y-%m-%d'),
            'display': f"Today ({today.strftime('%d/%m/%y')})"
        })
    
    date_options.append({
        'value': tomorrow.strftime('%Y-%m-%d'),
        'display': f"Tomorrow ({tomorrow.strftime('%d/%m/%y')})"
    })
    
    # Add next 3 days
    for i in range(2, 5):
        next_date = today + timedelta(days=i)
        date_options.append({
            'value': next_date.strftime('%Y-%m-%d'),
            'display': next_date.strftime('%A, %d/%m/%y')
        })
    
    return render_template('select_date.html', date_options=date_options)

@app.route('/location', methods=['GET', 'POST'])
def location():
    if not is_user_logged_in():
        flash('Please login first', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        location = request.form.get('location')
        if not location:
            flash('Please select a delivery location', 'danger')
            return redirect(url_for('location'))
        
        session['delivery_location'] = location
        return redirect(url_for('time_slot'))

    # Get active locations from database
    locations = [loc['name'] for loc in db.locations.find({'is_active': True}).sort('name', 1)]
    
    if not locations:
        flash('No delivery locations available. Please check back later.', 'warning')
        return redirect(url_for('home'))

    return render_template('location.html', locations=locations)

@app.route('/time-slot', methods=['GET', 'POST'])
def time_slot():
    if not is_user_logged_in():
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    # Check if delivery_date exists in session
    if 'delivery_date' not in session:
        flash('Please select a delivery date first', 'warning')
        return redirect(url_for('select_date'))
    
    if request.method == 'POST':
        time_slot = request.form.get('time_slot')
        if not time_slot:
            flash('Please select a time slot', 'danger')
            return redirect(url_for('time_slot'))
        
        session['time_slot'] = time_slot
        return redirect(url_for('summary'))
    
    time_slots = [
        "11:00 AM - 11:30 AM",
        "11:30 AM - 12:00 PM",
        "12:00 PM - 12:30 PM",
        "12:30 PM - 1:00 PM"
    ]
    
    # Format the date safely
    try:
        delivery_date = datetime.strptime(session['delivery_date'], '%Y-%m-%d')
        formatted_date = delivery_date.strftime('%A, %d %B')
    except:
        formatted_date = "your selected date"
    
    return render_template('time_slot.html', 
                        time_slots=time_slots,
                        formatted_date=formatted_date)

@app.route('/summary')
def summary():
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('home'))
    
    if 'delivery_location' not in session or 'time_slot' not in session:
        flash('Please select delivery location and time slot', 'warning')
        return redirect(url_for('location'))

    # Get pricing settings
    settings = db.settings.find_one({'name': 'billing'}) or {
        'delivery_fee': 2.00,
        'tax_rate': 5.0,
        'special_charges': {
            'packaging': 0.50,
            'service': 0.00
        }
    }

    # Calculate totals - INCLUDES ALL ITEM TYPES
    subtotal = sum(item['price'] * item['quantity'] for item in session['cart'])
    delivery_fee = float(settings.get('delivery_fee', 2.00))
    packaging = float(settings.get('special_charges', {}).get('packaging', 0.50))
    service = float(settings.get('special_charges', {}).get('service', 0.00))
    tax = subtotal * (float(settings.get('tax_rate', 5.0)) / 100)
    grand_total = subtotal + delivery_fee + packaging + service + tax

    return render_template('summary.html', 
                         cart=session['cart'],  # Pass the complete cart
                         location=session['delivery_location'],
                         time_slot=session['time_slot'],
                         subtotal=subtotal,
                         delivery_fee=delivery_fee,
                         packaging=packaging,
                         service=service,
                         tax=tax,
                         tax_rate=float(settings.get('tax_rate', 5.0)),
                         grand_total=grand_total,
                         settings=settings)


@app.route('/update-order-status/<status>')
def update_order_status(status):
    if 'current_order' not in session:
        return jsonify({'success': False})
    
    try:
        db.orders.update_one(
            {'_id': ObjectId(session['current_order']['order_id'])},
            {'$set': {'status': status}}
        )
        session['current_order']['status'] = status
        session.modified = True
        
        if status == 'delivered':
            # Remove order from session after delivery
            del session['current_order']
        
        return jsonify({'success': True})
    except:
        return jsonify({'success': False})

@app.route('/confirm-order', methods=['POST'])
def confirm_order():
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    try:
        if 'cart' not in session or not session['cart']:
            flash('Your cart is empty', 'warning')
            return redirect(url_for('home'))

        # Get pricing settings
        settings = db.settings.find_one({'name': 'billing'}) or {
            'delivery_fee': 2.00,
            'tax_rate': 5.0,
            'special_charges': {
                'packaging': 0.50,
                'service': 0.00
            }
        }

        # Calculate totals including all item types
        subtotal = sum(item['price'] * item['quantity'] for item in session['cart'])
        delivery_fee = float(settings.get('delivery_fee', 2.00))
        packaging = float(settings.get('special_charges', {}).get('packaging', 0.50))
        service = float(settings.get('special_charges', {}).get('service', 0.00))
        tax = subtotal * (float(settings.get('tax_rate', 5.0)) / 100)
        grand_total = subtotal + delivery_fee + packaging + service + tax

        # Create order with all item types
        order_data = {
            "user_id": session['user_id'],
            "items": session['cart'],
            "status": "preparing",
            "created_at": datetime.now(),
            "delivery_location": session['delivery_location'],
            "delivery_date": session['delivery_date'],
            "time_slot": session['time_slot'],
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "packaging": packaging,
            "service": service,
            "tax": tax,
            "tax_rate": float(settings.get('tax_rate', 5.0)),
            "total": grand_total
        }
        
        # Insert order
        result = db.orders.insert_one(order_data)
        order_id = str(result.inserted_id)
        
        # Create order confirmation notification
        notification = {
            'user_id': session['user_id'],
            'title': 'Order Confirmed',
            'message': f'Your order #{order_id[:6]} has been placed successfully!',
            'order_id': order_id,
            'is_active': True,
            'created_at': datetime.now(),
            'is_read': False
        }
        db.notifications.insert_one(notification)
        
        # Set current order in session
        session['current_order'] = {
            'order_id': order_id,
            'status': 'preparing',
            'created_at': datetime.now().isoformat()
        }
        
        # Clear cart and delivery info (but keep current_order)
        session.pop('cart', None)
        session.pop('delivery_location', None)
        session.pop('time_slot', None)
        session.pop('delivery_date', None)
        
        flash('Order placed successfully!', 'success')
        return redirect(url_for('tracking', order_id=order_id))
    
    except Exception as e:
        app.logger.error(f"Order confirmation error: {str(e)}")
        flash('Failed to place order. Please try again.', 'danger')
        return redirect(url_for('summary'))
    
@app.route('/tracking')
def tracking():
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    order_id = request.args.get('order_id')
    
    # If no order_id in URL but have current_order in session
    if not order_id and 'current_order' in session:
        order_id = session['current_order']['order_id']
    
    if not order_id:
        flash('No order specified', 'danger')
        return redirect(url_for('home'))
    
    try:
        order = db.orders.find_one({
            "_id": ObjectId(order_id),
            "user_id": session['user_id']
        })
        
        if not order:
            flash('Order not found', 'danger')
            if 'current_order' in session:
                session.pop('current_order')
            return redirect(url_for('home'))
        
        # Update session with current order if not present
        if 'current_order' not in session:
            session['current_order'] = {
                'order_id': order_id,
                'status': order.get('status', 'preparing'),
                'created_at': order['created_at'].isoformat()
            }
        
        # Prepare order data for template
        order_data = {
            '_id': str(order['_id']),
            'items': order.get('items', []),
            'status': order.get('status', 'preparing'),
            'time_slot': order.get('time_slot', 'Not specified'),
            'created_at': order.get('created_at', datetime.now()),
            'total': float(order.get('total', 0)),
            'delivery_location': order.get('delivery_location', 'Not specified'),
            'delivery_date': order.get('delivery_date', '')
        }
        
        return render_template('tracking.html', 
                           order=order_data,
                           current_status=order['status'])
    
    except Exception as e:
        app.logger.error(f"Tracking error: {str(e)}")
        flash('Error loading order details', 'danger')
        return redirect(url_for('home'))

@app.route('/check-order-status')
def check_order_status():
    if 'current_order' not in session or 'user_id' not in session:
        return {'status': None}
    
    try:
        order = db.orders.find_one(
            {"_id": ObjectId(session['current_order']['order_id']),
            "user_id": session['user_id']
        }, 
            {"status": 1}
        )
        
        if order and order['status'] != session['current_order']['status']:
            session['current_order']['status'] = order['status']
            session.modified = True
            
        return {'status': order['status'] if order else None}
    
    except:
        return {'status': None}
    
from math import ceil

@app.route('/my-orders')
def my_orders():
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    try:
        # Get all orders for current user
        orders_cursor = db.orders.find({"user_id": session['user_id']}).sort("created_at", -1)
        processed_orders = []
        
        for order in orders_cursor:
            # Convert MongoDB order to a serializable dict
            order_dict = {
                '_id': str(order['_id']),
                'user_id': order['user_id'],
                'status': order.get('status', 'pending'),
                'created_at': order.get('created_at', datetime.now()).strftime('%Y-%m-%d %H:%M'),
                'delivery_date': order.get('delivery_date', datetime.now().strftime('%Y-%m-%d')),
                'time_slot': order.get('time_slot', 'Not specified'),
                'delivery_location': order.get('delivery_location', 'Not specified'),
                'subtotal': float(order.get('subtotal', 0)),
                'delivery_fee': float(order.get('delivery_fee', 0)),
                'total': float(order.get('total', 0))
            }
            
            # Safely handle items list
            items = order.get('items')
            if callable(items):  # If items is accidentally a function
                items = []
            elif not isinstance(items, list):  # If items exists but isn't a list
                items = []
            
            order_dict['items'] = items
            order_dict['item_count'] = len(items)
            
            processed_orders.append(order_dict)
        
        return render_template('my_orders.html', 
                            orders=processed_orders,
                            datetime=datetime,
                            now=datetime.now)
    
    except Exception as e:
        app.logger.error(f"Error fetching orders: {str(e)}", exc_info=True)
        flash('Error loading your orders. Please try again.', 'danger')
        return redirect(url_for('home'))
    
@app.route('/order-details/<order_id>')
def order_details(order_id):
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))
    
    try:
        # Get the complete order document
        order = db.orders.find_one({
            "_id": ObjectId(order_id),
            "user_id": session['user_id']
        })
        
        if not order:
            flash('Order not found', 'danger')
            return redirect(url_for('my_orders'))
        
        # Process order items - handle both old and new format
        order_items = []
        if 'items' in order:
            # New format - items array contains all types
            order_items = order['items']
        elif 'main_dishes' in order:
            # Old format - separate arrays for different types
            if 'main_dishes' in order:
                order_items.extend(order['main_dishes'])
            if 'side_dishes' in order:
                order_items.extend(order['side_dishes'])
            if 'other_items' in order:
                order_items.extend(order['other_items'])
        
        # Prepare order data
        order_data = {
            '_id': str(order['_id']),
            'order_items': order_items,  # Contains all item types
            'status': order.get('status', 'pending'),
            'created_at': order.get('created_at', datetime.now()),
            'delivery_date': order.get('delivery_date', ''),
            'time_slot': order.get('time_slot', 'Not specified'),
            'delivery_location': order.get('delivery_location', 'Not specified'),
            'subtotal': float(order.get('subtotal', 0)),
            'delivery_fee': float(order.get('delivery_fee', 0)),
            'packaging': float(order.get('packaging', 0)),
            'service': float(order.get('service', 0)),
            'tax': float(order.get('tax', 0)),
            'tax_rate': float(order.get('tax_rate', 0)),
            'total': float(order.get('total', 0))
        }
        
        return render_template('order_details.html', order=order_data)
    
    except Exception as e:
        app.logger.error(f"Error loading order details: {str(e)}")
        flash('Error loading order details', 'danger')
        return redirect(url_for('my_orders'))
    
@app.route('/cancel-order/<order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session:
        flash('Please login to cancel orders', 'warning')
        return redirect(url_for('login'))
    
    try:
        # Get the order
        order = db.orders.find_one({
            "_id": ObjectId(order_id),
            "user_id": session['user_id']
        })
        
        if not order:
            flash('Order not found', 'danger')
            return redirect(url_for('my_orders'))
        
        # Check if cancellation is allowed
        delivery_date = datetime.strptime(order['delivery_date'], '%Y-%m-%d').date()
        today = datetime.now().date()
        current_hour = datetime.now().hour
        
        # Can only cancel if:
        # 1. Order is for today and it's before 10 AM, OR
        # 2. Order is for a future date
        can_cancel = (delivery_date == today and current_hour < 10) or (delivery_date > today)
        
        if not can_cancel:
            flash('Cancellation is only allowed before 10 AM on the delivery date', 'danger')
            return redirect(url_for('my_orders'))
        
        # Update order status
        db.orders.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {'status': 'cancelled'}}
        )
        
        flash('Order cancelled successfully', 'success')
        return redirect(url_for('my_orders'))
    
    except Exception as e:
        print(f"Error cancelling order: {str(e)}")
        flash('Failed to cancel order', 'danger')
        return redirect(url_for('my_orders'))
# Auth routes (if needed)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = db.users.find_one({"email": email})
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user.get('full_name', 'User')
            session['is_admin'] = user.get('is_admin', False)
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

import random
import string
from datetime import datetime, timedelta

# Add these new routes
@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    if request.method == 'POST':
        user_otp = request.form.get('otp')
        session_email = session.get('pending_email')
        
        if not session_email:
            flash('Session expired. Please register again.', 'danger')
            return redirect(url_for('register'))
        
        stored_otp = db.otp_tokens.find_one({
            'email': session_email,
            'used': False
        })
        
        if stored_otp and stored_otp['otp'] == user_otp and stored_otp['expires_at'] > datetime.now():
            # Mark OTP as used
            db.otp_tokens.update_one(
                {'_id': stored_otp['_id']},
                {'$set': {'used': True}}
            )
            
            # Create the user account
            db.users.insert_one(session['pending_user_data'])
            del session['pending_email']
            del session['pending_user_data']
            
            flash('Email verified! Registration complete. Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid or expired OTP', 'danger')
    
    return render_template('verify_email.html')

# Modified register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Get form data
        full_name = request.form.get('full_name')
        email = request.form.get('email').lower()
        phone = request.form.get('phone')
        alt_phone = request.form.get('alt_phone')
        address = request.form.get('address')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # Validation checks
        if not all([full_name, email, phone, address, password, confirm_password]):
            flash('Please fill all required fields', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))

        if db.users.find_one({'email': email}):
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))

        if db.users.find_one({'phone': phone}):
            flash('Phone number already registered', 'danger')
            return redirect(url_for('register'))

        try:
            # Generate OTP (6-digit code)
            otp = ''.join(random.choices(string.digits, k=6))
            
            # Store user data temporarily in session
            session['pending_user_data'] = {
                'full_name': full_name,
                'email': email,
                'phone': phone,
                'alt_phone': alt_phone,
                'address': address,
                'password': generate_password_hash(password),
                'is_admin': False,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            session['pending_email'] = email
            
            # Store OTP in database (expires in 15 minutes)
            db.otp_tokens.insert_one({
                'email': email,
                'otp': otp,
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(minutes=15),
                'used': False
            })
            
            # Send OTP via email
            msg = Message(
                "Your Email Verification Code",
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[email]
            )
            msg.body = f"Your verification code is: {otp}\n\nThis code will expire in 15 minutes."
            mail.send(msg)
            
            flash('Verification code sent to your email!', 'success')
            return redirect(url_for('verify_email'))
            
        except Exception as e:
            app.logger.error(f"Registration error: {str(e)}")
            flash('Registration failed. Please try again.', 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')
@app.route('/resend-otp')
def resend_otp():
    if 'pending_email' not in session:
        flash('Session expired. Please register again.', 'danger')
        return redirect(url_for('register'))
    
    email = session['pending_email']
    
    # Delete any existing unused OTPs
    db.otp_tokens.delete_many({
        'email': email,
        'used': False
    })
    
    # Generate new OTP
    otp = ''.join(random.choices(string.digits, k=6))
    
    # Store new OTP
    db.otp_tokens.insert_one({
        'email': email,
        'otp': otp,
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(minutes=15),
        'used': False
    })
    
    # Resend email
    msg = Message(
        "Your New Verification Code",
        sender=app.config['MAIL_DEFAULT_SENDER'],
        recipients=[email]
    )
    msg.body = f"Your new verification code is: {otp}\n\nThis code will expire in 15 minutes."
    mail.send(msg)
    
    flash('New verification code sent!', 'success')
    return redirect(url_for('verify_email'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))



#Admin 
# Admin routes
@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))
    
    # Get counts for dashboard
    orders_count = db.orders.count_documents({})
    users_count = db.users.count_documents({})
    
    # Get today's date in YYYY-MM-DD format
    today_date = datetime.now().strftime('%Y-%m-%d')
    today_orders = db.orders.count_documents({
        'delivery_date': today_date
    })
    
    # Get recent orders (last 5)
    recent_orders = []
    for order in db.orders.find().sort('created_at', -1).limit(5):
        user = db.users.find_one({'_id': ObjectId(order['user_id'])}, {'full_name': 1})
        recent_orders.append({
            '_id': str(order['_id']),
            'user': user or {'full_name': 'Unknown'},
            'created_at': order.get('created_at', datetime.now()),
            'total': float(order.get('total', 0)),
            'status': order.get('status', 'pending')
        })
    
    return render_template('admin/dashboard.html',
                         orders_count=orders_count,
                         users_count=users_count,
                         today_orders=today_orders,
                         today_date=today_date,
                         recent_orders=recent_orders)

@app.route('/admin/food-items')
def admin_food_items():
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))
    
    main_dishes = list(db.dishes.find())
    side_dishes = list(db.side_dishes.find())
    other_items = list(db.other_items.find())
    
    return render_template('admin/food_items.html',
                         main_dishes=main_dishes,
                         side_dishes=side_dishes,
                         other_items=other_items)

@app.route('/admin/food-items/edit/<item_type>/<item_id>', methods=['GET', 'POST'])
def admin_edit_food_item(item_type, item_id):
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))
    
    collections = {
        'main': db.dishes,
        'side': db.side_dishes,
        'other': db.other_items
    }
    
    item = collections[item_type].find_one({'_id': ObjectId(item_id)})
    
    if request.method == 'POST':
        update_data = {
            'name': request.form.get('name'),
            'price': float(request.form.get('price')),
            'description': request.form.get('description'),
            'is_available': request.form.get('is_available') == 'on'
        }
        
        collections[item_type].update_one(
            {'_id': ObjectId(item_id)},
            {'$set': update_data}
        )
        
        flash('Item updated successfully', 'success')
        return redirect(url_for('admin_food_items'))
    
    return render_template('admin/edit_food_item.html',
                         item=item,
                         item_type=item_type)

# Add new food item
@app.route('/admin/food-items/add/<item_type>', methods=['GET', 'POST'])
def admin_add_food_item(item_type):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    collections = {
        'main': db.dishes,
        'side': db.side_dishes,
        'other': db.other_items
    }

    if request.method == 'POST':
        try:
            new_item = {
                'name': request.form.get('name'),
                'price': float(request.form.get('price')),
                'description': request.form.get('description'),
                'category': request.form.get('category'),
                'is_available': request.form.get('is_available') == 'on',
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            
            collections[item_type].insert_one(new_item)
            flash('Item added successfully!', 'success')
            return redirect(url_for('admin_food_items'))
        except Exception as e:
            flash(f'Error adding item: {str(e)}', 'danger')

    categories = {
        'main': ['Vegetarian', 'Non-Vegetarian', 'Vegan'],
        'side': ['Salad', 'Bread', 'Soup', 'Snack'],
        'other': ['Beverage', 'Dessert', 'Extra']
    }

    return render_template('admin/add_food_item.html',
                         item_type=item_type,
                         categories=categories[item_type])

@app.route('/admin/bill-settings', methods=['GET', 'POST'])
def admin_bill_settings():
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            # Update bill settings (always available)
            settings_data = {
                'delivery_fee': float(request.form.get('delivery_fee', 2.0)),
                'tax_rate': float(request.form.get('tax_rate', 5.0)),
                'special_charges': {
                    'packaging': float(request.form.get('packaging_charge', 0.5)),
                    'service': float(request.form.get('service_charge', 0.0))
                },
                'updated_at': datetime.now()
            }
            
            db.settings.update_one(
                {'name': 'billing'},
                {'$set': settings_data},
                upsert=True
            )

            # Only process offer if it's from the modal form
            if 'offer_name' in request.form:
                offer_data = {
                    'name': request.form['offer_name'],
                    'code': request.form['offer_code'],
                    'discount': float(request.form['discount']),
                    'valid_until': datetime.strptime(request.form['valid_until'], '%Y-%m-%d'),
                    'is_active': request.form.get('is_active') == 'on',
                    'created_at': datetime.now()
                }
                db.offers.insert_one(offer_data)
                flash('New offer created successfully!', 'success')

            flash('Settings updated successfully!', 'success')
            return redirect(url_for('admin_bill_settings'))

        except ValueError as e:
            app.logger.error(f"Invalid input format: {str(e)}")
            flash('Invalid input format. Please check your values.', 'danger')
        except Exception as e:
            app.logger.error(f"Error updating settings: {str(e)}")
            flash('An error occurred. Please try again.', 'danger')

    # Get current settings with defaults
    settings = db.settings.find_one({'name': 'billing'}) or {
        'delivery_fee': 2.0,
        'tax_rate': 5.0,
        'special_charges': {
            'packaging': 0.5,
            'service': 0.0
        }
    }
    
    current_offers = list(db.offers.find({'valid_until': {'$gte': datetime.now()}}))
    
    return render_template('admin/bill_settings.html',
                         settings=settings,
                         offers=current_offers)
# Delete offer
@app.route('/admin/offer/delete/<offer_id>')
def delete_offer(offer_id):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))
    
    db.offers.delete_one({'_id': ObjectId(offer_id)})
    flash('Offer deleted', 'success')
    return redirect(url_for('admin_bill_settings'))

@app.route('/admin/food-items/delete/<item_type>/<item_id>')
def delete_food_item(item_type, item_id):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    collections = {
        'main': db.dishes,
        'side': db.side_dishes,
        'other': db.other_items
    }

    collections[item_type].delete_one({'_id': ObjectId(item_id)})
    flash('Item deleted successfully', 'success')
    return redirect(url_for('admin_food_items'))
@app.route('/admin/announcements', methods=['GET', 'POST'])
def admin_announcements():
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        announcement = {
            'title': request.form.get('title'),
            'message': request.form.get('message'),
            'is_active': request.form.get('is_active') == 'on',
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'style': request.form.get('style', 'info')  # info, warning, danger, success
        }
        
        db.announcements.insert_one(announcement)
        flash('Announcement created successfully!', 'success')
        return redirect(url_for('admin_announcements'))
    
    announcements = list(db.announcements.find().sort('created_at', -1))
    return render_template('admin/announcements.html', announcements=announcements)

@app.route('/admin/announcement/delete/<announcement_id>')
def delete_announcement(announcement_id):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))
    
    db.announcements.delete_one({'_id': ObjectId(announcement_id)})
    flash('Announcement deleted', 'success')
    return redirect(url_for('admin_announcements'))
@app.route('/dismiss_announcement', methods=['POST'])
def dismiss_announcement():
    if 'user_id' not in session:
        return jsonify({'success': False}), 401
    
    announcement_id = request.form.get('announcement_id')
    if not announcement_id:
        return jsonify({'success': False}), 400
    
    # Add to user's dismissed announcements
    db.users.update_one(
        {'_id': ObjectId(session['user_id'])},
        {'$addToSet': {'dismissed_announcements': ObjectId(announcement_id)}}
    )
    
    return jsonify({'success': True})

@app.context_processor
def inject_announcements():
    if 'user_id' not in session:
        return {}
    
    # Get user's dismissed announcements
    user = db.users.find_one({'_id': ObjectId(session['user_id'])}, 
                           {'dismissed_announcements': 1})
    dismissed = user.get('dismissed_announcements', [])
    
    # Get active announcements not dismissed by user
    announcements = list(db.announcements.find({
        'is_active': True,
        '_id': {'$nin': dismissed}
    }).sort('created_at', -1).limit(1))  # Only show most recent
    
    return {'active_announcements': announcements}


@app.route('/admin/orders')
def admin_orders():
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    # Get filter parameters
    date_filter = request.args.get('date')
    status_filter = request.args.get('status', 'all')
    location_filter = request.args.get('location', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Build query filters
    query = {}
    if date_filter:
        query['delivery_date'] = date_filter
    if status_filter != 'all':
        query['status'] = status_filter
    if location_filter != 'all':
        query['delivery_location'] = location_filter

    # Get total count of orders
    total_orders = db.orders.count_documents(query)

    # Get orders with pagination
    orders = list(db.orders.find(query)
                 .sort('created_at', -1)
                 .skip((page - 1) * per_page)
                 .limit(per_page))

    # Get user details for each order
    processed_orders = []
    for order in orders:
        user = db.users.find_one({'_id': ObjectId(order['user_id'])}) or {}
        processed_orders.append({
            '_id': str(order['_id']),
            'user': user,
            'created_at': order.get('created_at', datetime.now()),
            'delivery_date': order.get('delivery_date', ''),
            'delivery_location': order.get('delivery_location', 'Not specified'),
            'time_slot': order.get('time_slot', 'Not specified'),
            'items': order.get('items', []),
            'item_count': len(order.get('items', [])),
            'total': float(order.get('total', 0)),
            'status': order.get('status', 'pending')
        })

    # Get unique dates for filter dropdown
    unique_dates = db.orders.distinct('delivery_date')
    
    # Get all active locations
    locations = list(db.locations.find({'is_active': True}).sort('name', 1))

    return render_template('admin/orders.html',
                         orders=processed_orders,
                         unique_dates=unique_dates,
                         locations=locations,
                         date_filter=date_filter,
                         status_filter=status_filter,
                         location_filter=location_filter,
                         pagination={
                             'page': page,
                             'per_page': per_page,
                             'total': total_orders,
                             'pages': ceil(total_orders / per_page)
                         })

@app.route('/admin/order/<order_id>')
def admin_order_details(order_id):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('admin_orders'))

    try:
        order = db.orders.find_one({'_id': ObjectId(order_id)})
        if not order:
            flash('Order not found', 'danger')
            return redirect(url_for('admin_orders'))

        # Safely get items - handle both missing field and method cases
        order_items = []
        if 'items' in order:
            if isinstance(order['items'], list):
                order_items = order['items']
            elif callable(order['items']):
                app.logger.warning(f"Items is callable for order {order_id}")
            else:
                app.logger.warning(f"Unexpected items type for order {order_id}")
        
        # Get user details with defaults
        user = db.users.find_one(
            {'_id': ObjectId(order['user_id'])}, 
            {'full_name': 1, 'email': 1, 'phone': 1, 'address': 1}
        ) or {
            'full_name': 'Unknown User',
            'email': 'N/A',
            'phone': 'N/A',
            'address': 'N/A'
        }

        # Prepare order data with safe defaults
        order_data = {
            '_id': str(order['_id']),
            'user': user,
            'order_items': order_items,  # Use a different name than 'items'
            'status': order.get('status', 'pending'),
            'created_at': order.get('created_at', datetime.now()),
            'delivery_date': order.get('delivery_date', 'Not specified'),
            'time_slot': order.get('time_slot', 'Not specified'),
            'delivery_location': order.get('delivery_location', 'Not specified'),
            'subtotal': float(order.get('subtotal', 0)),
            'delivery_fee': float(order.get('delivery_fee', 0)),
            'packaging': float(order.get('packaging', 0)),
            'service': float(order.get('service', 0)),
            'tax': float(order.get('tax', 0)),
            'tax_rate': float(order.get('tax_rate', 0)),
            'total': float(order.get('total', 0)),
            'notes': order.get('notes', 'No notes available')
        }

        # Safely process status history
        status_history = order.get('status_history', [])
        if callable(status_history):
            status_history = []
            app.logger.warning(f"Status history is callable for order {order_id}")

        return render_template(
            'admin/order_details.html',
            order=order_data,
            status_history=status_history
        )

    except Exception as e:
        app.logger.error(f"Error loading order {order_id}: {str(e)}", exc_info=True)
        flash('Error loading order details', 'danger')
        return redirect(url_for('admin_orders'))

@app.route('/admin/order/<order_id>/update-status', methods=['POST'])
def admin_update_order_status(order_id):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    try:
        new_status = request.form.get('status')
        notes = request.form.get('notes', '')

        if not new_status:
            flash('Status is required', 'danger')
            return redirect(url_for('admin_order_details', order_id=order_id))

        # First get the order to have the user_id for notification
        order = db.orders.find_one({'_id': ObjectId(order_id)})
        if not order:
            flash('Order not found', 'danger')
            return redirect(url_for('admin_orders'))

        # Update order status
        update_data = {
            '$set': {'status': new_status},
            '$push': {
                'status_history': {
                    'status': new_status,
                    'changed_at': datetime.now(),
                    'changed_by': session['user_id'],
                    'notes': notes
                }
            }
        }

        db.orders.update_one({'_id': ObjectId(order_id)}, update_data)

        # Create notification for user
        notification = {
            'user_id': order['user_id'],  # Now using the order we fetched earlier
            'title': 'Order Status Updated',
            'message': f'Your order #{order_id[:6]} is now {new_status}',
            'order_id': order_id,
            'is_active': True,
            'created_at': datetime.now(),
            'is_read': False
        }
        db.notifications.insert_one(notification)

        flash('Order status updated successfully', 'success')
        return redirect(url_for('admin_order_details', order_id=order_id))

    except Exception as e:
        app.logger.error(f"Error updating order status: {str(e)}", exc_info=True)
        flash('Error updating order status', 'danger')
        return redirect(url_for('admin_order_details', order_id=order_id))

@app.route('/admin/locations', methods=['GET', 'POST'])
def admin_locations():
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        action = request.form.get('action')
        location_name = request.form.get('name', '').strip()
        
        if action == 'add' and location_name:
            # Add new location
            if db.locations.find_one({'name': location_name}):
                flash('Location already exists', 'warning')
            else:
                db.locations.insert_one({
                    'name': location_name,
                    'is_active': True,
                    'created_at': datetime.now()
                })
                flash('Location added successfully', 'success')
        
        elif action == 'toggle':
            # Toggle active status
            location_id = request.form.get('location_id')
            db.locations.update_one(
                {'_id': ObjectId(location_id)},
                {'$set': {'is_active': request.form.get('is_active') == 'true'}}
            )
            return jsonify({'success': True})
        
        elif action == 'delete':
            # Delete location (soft delete)
            location_id = request.form.get('location_id')
            db.locations.update_one(
                {'_id': ObjectId(location_id)},
                {'$set': {'is_active': False}}
            )
            flash('Location deactivated', 'success')
        
        return redirect(url_for('admin_locations'))

    # GET request - show all locations
    locations = list(db.locations.find().sort('name', 1))
    return render_template('admin/locations.html', locations=locations)

#PDF

@app.route('/admin/orders/<order_id>/print')
def admin_print_order(order_id):
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    try:
        order = db.orders.find_one({'_id': ObjectId(order_id)})
        if not order:
            flash('Order not found', 'danger')
            return redirect(url_for('admin_orders'))

        user = db.users.find_one({'_id': ObjectId(order['user_id'])})
        
        # Create HTML template for printing
        return render_template('admin/order_print.html',
                            order=order,
                            user=user,
                            datetime=datetime)

    except Exception as e:
        app.logger.error(f"Order print error: {str(e)}")
        flash('Failed to generate print view', 'danger')
        return redirect(url_for('admin_order_details', order_id=order_id))
    
@app.route('/admin/orders/pdf-report')
def admin_order_pdf_report():
    if not session.get('is_admin'):
        flash('Admin access required', 'danger')
        return redirect(url_for('login'))

    try:
        # Get filter parameters
        report_date = request.args.get('date')
        status_filter = request.args.get('status', 'all')
        location_filter = request.args.get('location', 'all')
        detailed = request.args.get('detailed', 'false').lower() == 'true'

        # Build query filters
        query = {}
        if report_date:
            query['delivery_date'] = report_date
        if status_filter != 'all':
            query['status'] = status_filter
        if location_filter != 'all':
            query['delivery_location'] = location_filter

        # Query orders
        orders = list(db.orders.find(query).sort('time_slot', 1))
        
        if not orders:
            flash('No orders found for the selected filters', 'info')
            return redirect(url_for('admin_orders'))

        # Create PDF buffer
        buffer = io.BytesIO()
        
        # Create PDF document
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                              rightMargin=40, leftMargin=40,
                              topMargin=40, bottomMargin=40)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Add title
        title_text = "Detailed Order Report" if detailed else "Order Summary Report"
        if report_date:
            title_text += f" - {report_date}"
        if location_filter != 'all':
            title_text += f" ({location_filter})"
        
        elements.append(Paragraph(title_text, styles['Heading1']))
        elements.append(Spacer(1, 12))
        
        # Add summary information
        summary_data = [
            ["Report Date:", datetime.now().strftime('%Y-%m-%d %H:%M')],
            ["Total Orders:", str(len(orders))],
            ["Total Revenue:", f"${sum(order.get('total', 0) for order in orders):.2f}"],
            ["Status Filter:", status_filter.replace('_', ' ').title() if status_filter != 'all' else 'All Statuses'],
            ["Location Filter:", location_filter if location_filter != 'all' else 'All Locations']
        ]
        
        summary_table = Table(summary_data, colWidths=[120, 180])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 24))
        
        if detailed:
            # Detailed report with individual orders
            for order in orders:
                user = db.users.find_one({'_id': ObjectId(order['user_id'])}) or {}
                
                # Order header
                elements.append(Paragraph(
                    f"Order #{str(order['_id'])[-6:].upper()} - {user.get('full_name', 'Unknown')}",
                    styles['Heading2']
                ))
                
                # Order details
                details_data = [
                    ["Delivery Date:", order.get('delivery_date', 'N/A')],
                    ["Time Slot:", order.get('time_slot', 'N/A')],
                    ["Location:", order.get('delivery_location', 'N/A')],
                    ["Status:", order.get('status', 'pending').replace('_', ' ').title()],
                ]
                
                details_table = Table(details_data, colWidths=[100, 200])
                elements.append(details_table)
                elements.append(Spacer(1, 10))
                
                # Order items
                if order.get('items'):
                    items_data = [["Item", "Qty", "Price", "Subtotal"]]
                    for item in order.get('items', []):
                        items_data.append([
                            item.get('name', 'Unknown'),
                            str(item.get('quantity', 1)),
                            f"${item.get('price', 0):.2f}",
                            f"${item.get('price', 0) * item.get('quantity', 1):.2f}"
                        ])
                    
                    # Add totals row
                    items_data.append(["", "", "Subtotal:", f"${order.get('subtotal', 0):.2f}"])
                    items_data.append(["", "", "Delivery Fee:", f"${order.get('delivery_fee', 0):.2f}"])
                    items_data.append(["", "", "Tax:", f"${order.get('tax', 0):.2f}"])
                    items_data.append(["", "", "Total:", f"${order.get('total', 0):.2f}"])
                    
                    items_table = Table(items_data, colWidths=[180, 40, 60, 60])
                    items_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                        ('LINEABOVE', (-4, 0), (-1, -1), 1, colors.black),
                    ]))
                    elements.append(items_table)
                
                elements.append(Spacer(1, 20))
        else:
            # Summary table
            summary_data = [["Order ID", "Customer", "Location", "Time Slot", "Items", "Total"]]
            for order in orders:
                user = db.users.find_one({'_id': ObjectId(order['user_id'])}) or {}
                summary_data.append([
                    str(order['_id'])[-6:].upper(),
                    user.get('full_name', 'Unknown'),
                    order.get('delivery_location', 'N/A'),
                    order.get('time_slot', 'N/A'),
                    str(len(order.get('items', []))),
                    f"${order.get('total', 0):.2f}"
                ])
            
            summary_table = Table(summary_data, colWidths=[60, 120, 80, 80, 40, 50])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF6B6B')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(summary_table)
        
        # Add footer
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(
            f"Generated by {session.get('username', 'Admin')} on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            styles['Italic']
        ))
        
        # Build PDF
        doc.build(elements)
        
        # Create response
        buffer.seek(0)
        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        
        filename = f"{'detailed' if detailed else 'summary'}_orders_{datetime.now().strftime('%Y%m%d')}"
        if report_date:
            filename += f"_{report_date}"
        if location_filter != 'all':
            filename += f"_{location_filter.replace(' ', '_')}"
        filename += ".pdf"
        
        response.headers['Content-Disposition'] = f'inline; filename={filename}'
        return response

    except Exception as e:
        app.logger.error(f"PDF generation error: {str(e)}", exc_info=True)
        flash('Failed to generate PDF report', 'danger')
        return redirect(url_for('admin_orders'))
    
if __name__ == '__main__':
    app.run(debug=True)