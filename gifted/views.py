from datetime import datetime

from flask import (
    Blueprint, flash, render_template, request, session,
    url_for, current_app)
from flask_mail import Message
from werkzeug import security
from werkzeug.utils import redirect

from gifted import login_required, validate, db, mail
from gifted.helpers import generate_code
from gifted.models import User, Invite, Event

bp = Blueprint('views', __name__)


@bp.route('/')
@login_required
def index():
    user = get_logged_in_user()
    events = user.events
    return render_template('index.html', events=events)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        validate(username=username, password=password, redirect_to='views.login')
        user = User.query.filter_by(username=username).first()

        if user is None:
            flash('Username does not exist!', 'error')
            return redirect(url_for('views.login'))

        # password is valid, proceed to set session cookie and redirect to index
        # otherwise, flash a friendly message
        if security.check_password_hash(pwhash=user.password, password=password):
            session['user_id'] = user.id
            session['username'] = request.form.get('username')
            session['is_admin'] = user.is_admin
            flash('Logged in successfully', 'success')
            return redirect(url_for('views.index'))
        else:
            flash('Invalid password!', 'error')
            return redirect(url_for('views.login'))

    # it's a GET, render the template
    return render_template('login.html')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_confirm = request.form.get('passwordConfirm')
        code = request.form.get('code')
        first_name = request.form.get('firstName')
        last_name = request.form.get('lastName')

        if password != password_confirm:
            flash('Passwords must match!', 'error')
            return redirect(url_for('views.register'))

        invitation = Invite.query.filter_by(email=username, code=code).first()
        event = Event.query.filter_by(id=invitation.id).first()
        if invitation is None:
            flash('This code and email combination is invalid!', 'error')
            return redirect(url_for('views.register'))

        if datetime.now() > invitation.expires_on:
            flash('This invitation has expired!', 'error')
            return redirect(url_for('views.register'))

        if event is None or datetime.now() > event.ends_on:
            flash('This event has either expired or it has been deleted!', 'error')
            return redirect(url_for('views.register'))

        user = User(username=username, password=security.generate_password_hash(password),
                    first_name=first_name, last_name=last_name)

        event.participants.append(user)
        invitation.is_used = 1
        db.session.add(user)
        db.session.commit()

        flash('Account created successfully!', 'success')
        return redirect(url_for('views.login'))

    # it's a GET, render the template
    return render_template('register.html', email=request.args.get('email'), code=request.args.get('code'))


@bp.route('/admin')
def admin():
    invites = Invite.query.filter_by(is_valid=1).order_by(Invite.id.desc()).all()
    events = Event.query.order_by(Event.id.desc()).all()
    return render_template('admin.html', events=events, invites=invites)


@bp.route('/admin/events', methods=['GET', 'POST'])
def create_event():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        starts_on = datetime.strptime(request.form.get('startsOn'), '%Y-%m-%d').date()
        ends_on = datetime.strptime(request.form.get('endsOn'), '%Y-%m-%d').date()

        event = Event(title=title, description=description, starts_on=starts_on, ends_on=ends_on)
        user = get_logged_in_user()
        event.participants.append(user)
        db.session.add(event)
        db.session.commit()

        flash('Event created successfully!', 'success')
        return redirect(url_for('views.admin'))


@bp.route('/admin/events/<event_id>')
def admin_get_event(event_id):
    event = Event.query.get(event_id)
    return render_template('admin_event.html', event=event)


@bp.route('/events/<event_id>')
def get_event(event_id):
    event = Event.query.get(event_id)
    participants = event.participants
    return render_template('event.html', event=event, participants=participants)


# todo: change urls to take path params w/ ids
@bp.route('/admin/events/delete', methods=['POST'])
def delete_event():
    event_id = request.form.get('id')
    event = Event.query.get(event_id)
    db.session.delete(event)
    db.session.commit()
    flash(f'Deleted event {event}!', 'success')
    return redirect(url_for('views.admin'))


@bp.route('/admin/users/delete', methods=['POST'])
def delete_user():
    user_id = request.form.get('id')
    user = User.query.get(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'Deleted user {user}!', 'success')
    return redirect(url_for('views.admin'))


@bp.route('/admin/invites', methods=['POST'])
def invite():
    email = request.form.get('email')
    event_id = request.form.get('eventId')
    code = generate_code()
    invitation = Invite(email=email, event_id=event_id, code=code)
    db.session.add(invitation)
    db.session.commit()
    flash(f'Invited {email}!', 'success')

    message = Message('You have been invited to participate in a Gifted exchange!',
                      sender=current_app.config.get("MAIL_USERNAME"),
                      recipients=[current_app.config.get("MAIL_USERNAME")])

    message.html = render_template('email.html', email=invitation.email, code=invitation.code)
    mail.send(message)

    return redirect(url_for('views.admin'))


@bp.route('/admin/invites/<invite_id>/revoke', methods=['POST'])
def revoke(invite_id):
    invitation = Invite.query.filter_by(id=invite_id).first()
    invitation.is_valid = 0
    db.session.commit()
    flash(f'Revoked {invitation.email}\'s invitation', 'success')
    return redirect(url_for('views.admin'))


@bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_admin', None)
    return redirect(url_for('views.login'))


@bp.app_template_filter('pretty_boolean')
def pretty_boolean(i):
    return True if i is 1 else False


@bp.app_template_filter('is_expired')
def is_expired(expires_on):
    now = datetime.now()
    return True if now > expires_on else False


def get_logged_in_user():
    return User.query.filter_by(id=session['user_id']).first()
