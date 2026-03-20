from datetime import datetime

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user

from app.incentive import incentive_bp
from app.extensions import db
from app.models.incentive import Incentive
from app.models.rant import Rant
from app.models.user import User


@incentive_bp.route('/')
@login_required
def index():
    """List: normal users see own submissions; PL/XM see all for review."""
    is_reviewer = current_user.has_role('PL', 'XM') or current_user.is_admin
    if is_reviewer:
        tab = request.args.get('tab', 'review')
        if tab == 'mine':
            items = Incentive.query.filter_by(submitted_by=current_user.id)\
                .order_by(Incentive.created_at.desc()).all()
        else:
            items = Incentive.query.filter_by(status='pending')\
                .order_by(Incentive.created_at.desc()).all()
    else:
        tab = 'mine'
        items = Incentive.query.filter_by(submitted_by=current_user.id)\
            .order_by(Incentive.created_at.desc()).all()

    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('incentive/index.html',
        items=items, users=users, is_reviewer=is_reviewer, tab=tab)


@incentive_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    import os, uuid

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    team_name = request.form.get('team_name', '').strip() or None
    nominee_ids = request.form.getlist('nominee_ids', type=int)

    if not title or not description or not nominee_ids:
        flash('请填写完整信息', 'danger')
        return redirect(url_for('incentive.index'))

    # Handle photo upload
    photo_path = None
    photo = request.files.get('photo')
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            fname = f'{uuid.uuid4().hex[:12]}{ext}'
            save_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'incentive')
            os.makedirs(save_dir, exist_ok=True)
            photo.save(os.path.join(save_dir, fname))
            photo_path = f'uploads/incentive/{fname}'

    nominees = User.query.filter(User.id.in_(nominee_ids)).all()
    category = request.form.get('category', 'professional')
    inc = Incentive(
        title=title, description=description, category=category,
        photo=photo_path, team_name=team_name,
        submitted_by=current_user.id, nominees=nominees,
    )
    db.session.add(inc)
    db.session.commit()
    flash('激励推荐已提交', 'success')
    return redirect(url_for('incentive.index'))


@incentive_bp.route('/<int:inc_id>/review', methods=['POST'])
@login_required
def review(inc_id):
    if not (current_user.has_role('PL', 'XM') or current_user.is_admin):
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    inc = db.get_or_404(Incentive, inc_id)
    action = request.form.get('action')
    comment = request.form.get('review_comment', '').strip()[:150]
    amount = request.form.get('amount', type=float)

    if action == 'approve':
        inc.status = 'approved'
        inc.amount = amount
    elif action == 'reject':
        inc.status = 'rejected'
    inc.review_comment = comment
    inc.reviewed_by = current_user.id
    inc.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash(f'已{"通过" if action == "approve" else "拒绝"}', 'success')
    return redirect(url_for('incentive.index'))


@incentive_bp.route('/ai-polish', methods=['POST'])
@login_required
def ai_polish():
    """AI polish review comment."""
    from app.services.ai import call_ollama
    data = request.get_json()
    text = (data.get('text') or '').strip() if data else ''
    if not text:
        return jsonify(ok=False, msg='请输入评语')
    _, raw = call_ollama(
        f'请润色以下激励评语，保持原意，语言精炼正式，不超过150字：\n{text}'
    )
    return jsonify(ok=True, text=raw.strip()[:150] if raw else text)


@incentive_bp.route('/rant', methods=['GET', 'POST'])
@login_required
def rant_wall():
    if request.method == 'POST':
        content = request.form.get('content', '').strip()[:500]
        if content:
            db.session.add(Rant(content=content))
            db.session.commit()
            flash('已匿名发布', 'success')
        return redirect(url_for('incentive.rant_wall'))

    rants = Rant.query.order_by(Rant.created_at.desc()).limit(50).all()
    return render_template('incentive/rant.html', rants=rants)


@incentive_bp.route('/admin-submit', methods=['POST'])
@login_required
def admin_submit():
    """Admin can submit approved incentive directly with custom month."""
    if not current_user.is_admin:
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import os, uuid

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'professional')
    team_name = request.form.get('team_name', '').strip() or None
    nominee_ids = request.form.getlist('nominee_ids', type=int)
    amount = request.form.get('amount', type=float)
    review_comment = request.form.get('review_comment', '').strip()[:150]
    month_str = request.form.get('month', '')  # YYYY-MM

    if not title or not nominee_ids:
        flash('请填写完整信息', 'danger')
        return redirect(url_for('incentive.index'))

    photo_path = None
    photo = request.files.get('photo')
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            fname = f'{uuid.uuid4().hex[:12]}{ext}'
            save_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'incentive')
            os.makedirs(save_dir, exist_ok=True)
            photo.save(os.path.join(save_dir, fname))
            photo_path = f'uploads/incentive/{fname}'

    reviewed_at = datetime.utcnow()
    if month_str:
        try:
            reviewed_at = datetime.strptime(month_str + '-15', '%Y-%m-%d')
        except ValueError:
            pass

    nominees = User.query.filter(User.id.in_(nominee_ids)).all()
    inc = Incentive(
        title=title, description=description or title, category=category,
        photo=photo_path, team_name=team_name,
        submitted_by=current_user.id, nominees=nominees,
        status='approved', amount=amount,
        review_comment=review_comment,
        reviewed_by=current_user.id, reviewed_at=reviewed_at,
    )
    db.session.add(inc)
    db.session.commit()
    flash('激励已录入', 'success')
    return redirect(url_for('incentive.index'))
