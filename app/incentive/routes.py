from datetime import datetime, date, timedelta

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user

from app.incentive import incentive_bp
from app.extensions import db
from app.constants import MAX_COMMENT_LENGTH
from app.models.incentive import Incentive
from app.models.todo import Todo
from app.models.requirement import Requirement
from app.models.rant import Rant
from app.models.user import User
from app.utils.upload import save_photo


@incentive_bp.route('/')
@login_required
def index():
    """List incentives with status filter."""
    is_reviewer = current_user.has_role('PL', 'XM') or current_user.is_admin
    status_filter = request.args.get('status', '')
    scope = request.args.get('scope', 'all' if is_reviewer else 'mine')

    q = Incentive.query
    if scope == 'mine':
        q = q.filter_by(submitted_by=current_user.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    items = q.order_by(Incentive.created_at.desc()).all()

    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('incentive/index.html',
        items=items, users=users, is_reviewer=is_reviewer,
        status_filter=status_filter, scope=scope)


@incentive_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    team_name = request.form.get('team_name', '').strip() or None
    nominee_ids = request.form.getlist('nominee_ids', type=int)

    if not title or not description or not nominee_ids:
        flash('请填写完整信息', 'danger')
        return redirect(url_for('incentive.index'))

    photo_path = save_photo(request.files.get('photo'))

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
    comment = request.form.get('review_comment', '').strip()[:MAX_COMMENT_LENGTH]
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


@incentive_bp.route('/<int:inc_id>/like', methods=['POST'])
@login_required
def like(inc_id):
    inc = db.session.get(Incentive, inc_id)
    if inc:
        inc.likes = (inc.likes or 0) + 1
        db.session.commit()
        if request.is_json:
            return jsonify(ok=True, likes=inc.likes)
    return redirect(url_for('incentive.index'))


@incentive_bp.route('/<int:inc_id>/photo', methods=['POST'])
@login_required
def update_photo(inc_id):
    """Replace incentive photo. Allowed: submitter, reviewer, admin."""
    inc = db.get_or_404(Incentive, inc_id)
    if current_user.id not in (inc.submitted_by, inc.reviewed_by) and not current_user.is_admin:
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))
    new_photo = save_photo(request.files.get('photo'))
    if new_photo:
        # Delete old photo
        if inc.photo:
            import os
            old_path = os.path.join(current_app.root_path, 'static', inc.photo)
            if os.path.exists(old_path):
                os.remove(old_path)
        inc.photo = new_photo
        db.session.commit()
        flash('照片已更新', 'success')
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
    from app.services.prompts import get_prompt
    _, raw = call_ollama(get_prompt('incentive_polish_comment') + f'\n{text}')
    return jsonify(ok=True, text=raw.strip()[:150] if raw else text)


@incentive_bp.route('/ai-describe', methods=['POST'])
@login_required
def ai_describe():
    """AI generate or polish description based on nominees' recent work."""
    from app.services.ai import call_ollama

    data = request.get_json() or {}
    nominee_ids = data.get('nominee_ids', [])
    existing_desc = (data.get('description') or '').strip()
    category = data.get('category', '')

    # If just polishing existing text
    if existing_desc and not nominee_ids:
        from app.services.prompts import get_prompt
        _, raw = call_ollama(get_prompt('incentive_polish_desc') + f'\n{existing_desc}')
        if raw:
            return jsonify(ok=True, text=raw.strip()[:500])
        return jsonify(ok=False, msg='AI 服务不可用')

    if not nominee_ids:
        return jsonify(ok=False, msg='请先选择推荐人物')

    # Gather nominees' recent work (last 30 days)
    nominees = User.query.filter(User.id.in_(nominee_ids)).all()
    if not nominees:
        return jsonify(ok=False, msg='未找到选中人员')

    since = date.today() - timedelta(days=30)
    parts = []
    for u in nominees:
        lines = [f'【{u.name}】']
        # Recent done todos
        todos = Todo.query.filter(
            Todo.user_id == u.id, Todo.status == 'done',
            Todo.done_date >= since,
        ).order_by(Todo.done_date.desc()).limit(10).all()
        if todos:
            lines.append('近期完成的任务：' + '、'.join(t.title for t in todos))

        # Active/done requirements
        reqs = Requirement.query.filter(
            Requirement.assignee_id == u.id,
            Requirement.updated_at >= str(since),
        ).limit(5).all()
        if reqs:
            lines.append('参与的需求：' + '、'.join(
                f'{r.title}({r.status_label})' for r in reqs
            ))
        parts.append('\n'.join(lines))

    category_map = {
        'professional': '专业能力', 'proactive': '积极主动',
        'beyond': '超越期望', 'clean': '代码Clean',
    }
    cat_label = category_map.get(category, '优秀表现')

    from app.services.prompts import get_prompt
    context = '\n\n'.join(parts)
    tpl = get_prompt('incentive_generate')
    prompt = tpl.replace('{{context}}', context).replace('{{category}}', cat_label)
    if existing_desc:
        prompt += f'\n\n参考已有描述进行润色：{existing_desc}'

    _, raw = call_ollama(prompt)
    if raw:
        return jsonify(ok=True, text=raw.strip()[:500])
    return jsonify(ok=False, msg='AI 服务不可用')


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

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'professional')
    team_name = request.form.get('team_name', '').strip() or None
    nominee_ids = request.form.getlist('nominee_ids', type=int)
    amount = request.form.get('amount', type=float)
    review_comment = request.form.get('review_comment', '').strip()[:MAX_COMMENT_LENGTH]
    month_str = request.form.get('month', '')  # YYYY-MM

    if not title or not nominee_ids:
        flash('请填写完整信息', 'danger')
        return redirect(url_for('incentive.index'))

    photo_path = save_photo(request.files.get('photo'))

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
