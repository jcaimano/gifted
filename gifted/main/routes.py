from datetime import datetime

from flask import Blueprint, render_template, request, flash, url_for, session, current_app
from flask_mail import Message
from werkzeug import security
from werkzeug.utils import redirect

from gifted import login_required, validate, db, mail
from gifted.models import User, Invite, Event, Item, Transaction, generate_code

main = Blueprint('main', __name__,
                 template_folder='templates',
                 static_folder='static')


@main.route('/')
@login_required
def index():
    user = User.query.filter_by(id=session['user_id']).first()
    events = user.events
    return render_template('index.html', events=events)


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        validate(username=username, password=password, redirect_to='main.login')
        user = User.query.filter_by(username=username).first()

        if user is None:
            flash('Username does not exist!', 'warning')
            return redirect(url_for('main.login'))

        # password is valid, proceed to set session cookie and redirect to index
        # otherwise, flash a friendly message
        if security.check_password_hash(pwhash=user.password, password=password):
            session['user_id'] = user.id
            session['username'] = request.form.get('username')
            session['is_admin'] = user.is_admin
            flash('Logged in successfully', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('Invalid password!', 'warning')
            return redirect(url_for('main.login'))

    # it's a GET, render the template
    return render_template('login.html')


@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_confirm = request.form.get('passwordConfirm')
        code = request.form.get('code')
        first_name = request.form.get('firstName')
        last_name = request.form.get('lastName')

        if password != password_confirm:
            flash('Passwords must match!', 'warning')
            return redirect(url_for('main.register'))

        invitation = Invite.query.filter_by(email=username, code=code).first()
        event = Event.query.filter_by(id=invitation.event_id).first()
        if invitation is None:
            flash('This code and email combination is invalid!', 'warning')
            return redirect(url_for('main.register'))

        if datetime.now() > invitation.expires_on:
            flash('This invitation has expired!', 'warning')
            return redirect(url_for('main.register'))

        if event is None or datetime.now() > event.ends_on:
            flash('This event has either expired or it has been deleted!', 'warning')
            return redirect(url_for('main.register'))

        user = User(username=username, password=security.generate_password_hash(password),
                    first_name=first_name, last_name=last_name)

        event.users.append(user)
        invitation.is_used = 1
        db.session.add(user)
        db.session.commit()

        flash('Account created successfully!', 'success')
        return redirect(url_for('main.login'))

    # it's a GET, render the template
    return render_template('register.html', email=request.args.get('email'), code=request.args.get('code'))


@main.route('/events/<event_id>')
@login_required
def event(event_id):
    event = Event.query.get(event_id)
    user = User.query.get(session['user_id'])
    liability = Transaction.get_user_liability(event.id, user.id)
    progress = get_event_progress(event_id)
    return render_template('event.html', event=event, progress=progress, logged_in_user=user,
                           liability=liability)


@main.route('/events/<event_id>/wishlists/<user_id>', methods=['GET', 'POST'])
@login_required
def wishlist(event_id, user_id):
    if request.method == 'POST':
        description = request.form.get('description')
        location = request.form.get('location')
        price = request.form.get('price')
        quantity = request.form.get('quantity')
        priority = request.form.get('priority')

        item = Item(description=description, location=location, price=price, quantity=quantity, priority=priority,
                    event_id=event_id, user_id=user_id)
        db.session.add(item)
        db.session.commit()

        return redirect(url_for('main.wishlist', event_id=event_id, user_id=user_id))

    event = Event.query.get(event_id)
    user = User.query.get(user_id)
    items = Item.query.filter_by(event_id=event_id, user_id=user_id).all()
    transactions = Transaction.query.filter_by(event_id=event_id).all()
    my_transactions = Transaction.query.filter_by(event_id=event_id, gifter_id=session['user_id']).all()
    progress = get_wishlist_progress(event_id, user_id)
    return render_template('wishlist.html', event=event, user=user, wishlist=items, progress=progress,
                           transactions=transactions, my_transactions=my_transactions)


@main.route('/events/<event_id>/purchases/<user_id>')
@login_required
def purchases(event_id, user_id):
    event = Event.query.get(event_id)
    transactions = Transaction.query.filter_by(event_id=event_id, gifter_id=user_id).all()
    liability = Transaction.get_user_liability(event_id, user_id)
    return render_template('purchases.html', event=event, purchases=transactions, liability=liability)


@main.route('/events/<event_id>/purchases/<user_id>/delete', methods=['POST'])
@login_required
def remove_purchase(event_id, user_id):
    purchase_id = request.form.get('purchase_id')
    purchase = Transaction.query.get(purchase_id)
    db.session.delete(purchase)
    db.session.commit()
    flash('You deleted a purchase!', 'warning')
    return redirect(url_for('main.purchases', event_id=event_id, user_id=user_id))


@main.route('/events/<event_id>/wishlists/<user_id>/items/<item_id>/delete', methods=['POST'])
@login_required
def remove_item(event_id, user_id, item_id):
    item_id = request.form.get('item_id')
    item = Item.query.get(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('You deleted an item!', 'warning')
    return redirect(url_for('main.wishlist', event_id=event_id, user_id=user_id))


@main.route('/events/<event_id>/wishlists/<user_id>/transactions', methods=['POST'])
@login_required
def claim_item(event_id, user_id):
    item_id = request.form.get('item_id')
    gifter_id = request.form.get('gifter_id')
    giftee_id = request.form.get('giftee_id')

    item = Item.query.get(item_id)
    transaction = Transaction(event_id=event_id, item_id=item_id, gifter_id=gifter_id, giftee_id=giftee_id)
    db.session.add(transaction)
    item.is_purchased = 1
    db.session.commit()

    flash('You claimed an item!', 'success')
    return redirect(url_for('main.wishlist', event_id=event_id, user_id=user_id))


@main.route('/events/<event_id>/wishlists/<user_id>/transactions/<transaction_id>/delete', methods=['POST'])
@login_required
def unclaim_item(event_id, user_id, transaction_id):
    if transaction_id != request.form.get('transaction_id'):
        flash('Transaction identifiers do not match.', 'warning')
        return redirect(url_for('main.wishlist', event_id=event_id, user_id=user_id))
    transaction = Transaction.query.get(transaction_id)
    item = transaction.item
    item.is_purchased = 0
    db.session.add(item)
    db.session.commit()
    db.session.delete(transaction)
    db.session.commit()
    flash('You unclaimed an item!', 'warning')
    return redirect(url_for('main.wishlist', event_id=event_id, user_id=user_id))


@main.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_admin', None)
    return redirect(url_for('main.login'))


@main.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        email = request.form.get('email')
        code = generate_code()
        message = Message('Gifted password reset',
                          sender=current_app.config.get("MAIL_USERNAME"),
                          recipients=[email])

        message.html = render_template('forgot_password_email.html', email=email, code=code)
        mail.send(message)
        flash('A password reset email was sent to {}!'.format(email), 'success')
        return redirect(url_for('main.login'))

    return render_template('forgot.html')


@main.app_template_filter('pretty_boolean')
def pretty_boolean(i):
    return True if i == 1 else False


@main.app_template_filter('is_expired')
def is_expired(expires_on):
    now = datetime.now()
    return True if now > expires_on else False


@main.app_template_filter('is_active')
def is_active(starts_on, ends_on):
    now = datetime.now()
    return True if starts_on < now < ends_on else False


def get_event_progress(event_id):
    progress = {}
    user_total_result = Item.get_wishlist_totals(event_id)
    for row in user_total_result:
        user_id = row[0]
        total = row[1]
        purchased = Transaction.get_user_total(event_id, user_id)
        percent = purchased / total * 100 if total != 0 else 0
        progress[user_id] = {'purchased': str(purchased), 'total': str(total), 'percent': "{:.2f}".format(percent)}

    return progress


def get_wishlist_progress(event_id, user_id):
    total = Item.get_wishlist_total(event_id, user_id)
    purchased = Transaction.get_user_total(event_id, user_id)
    percent = purchased / total * 100 if total != 0 else 0
    progress = {'purchased': str(purchased), 'total': str(total), 'percent': "{:.2f}".format(percent)}
    return progress
