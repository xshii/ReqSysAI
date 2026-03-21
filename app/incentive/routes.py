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

    period = request.args.get('period', '1m')
    period_days = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}.get(period, 30)
    since = date.today() - timedelta(days=period_days)

    q = Incentive.query.filter(Incentive.created_at >= str(since))
    if scope == 'mine':
        q = q.filter_by(submitted_by=current_user.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    items = q.order_by(Incentive.created_at.desc()).all()

    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('incentive/index.html',
        items=items, users=users, is_reviewer=is_reviewer,
        status_filter=status_filter, scope=scope, period=period,
        can_export=is_reviewer or current_user.is_admin)


@incentive_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    nominee_ids = request.form.getlist('nominee_ids', type=int)

    if not title or not description:
        flash('请填写标题和描述', 'danger')
        return redirect(url_for('incentive.index'))

    photo_path = save_photo(request.files.get('photo'))

    nominees = User.query.filter(User.id.in_(nominee_ids)).all() if nominee_ids else []
    ext_names = request.form.getlist('external_nominees')
    ext_str = ','.join(n.strip() for n in ext_names if n.strip()) or None
    if not nominees and not ext_str:
        flash('请选择至少一位推荐人员', 'danger')
        return redirect(url_for('incentive.index'))
    category = request.form.get('category', 'professional')
    inc = Incentive(
        title=title, description=description, category=category,
        photo=photo_path, external_nominees=ext_str,
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

    source = request.form.get('source', 'instant')
    if action == 'approve':
        inc.status = 'approved'
        inc.amount = amount
        inc.source = source
    elif action == 'reject':
        inc.status = 'rejected'
    inc.review_comment = comment
    inc.reviewed_by = current_user.id
    inc.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash(f'已{"通过" if action == "approve" else "拒绝"}', 'success')
    return redirect(url_for('incentive.index'))


@incentive_bp.route('/export-csv')
@login_required
def export_csv():
    """Export approved incentives as CSV. Reviewer/admin only."""
    if not (current_user.has_role('PL', 'XM', 'HR', 'LM') or current_user.is_admin):
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import csv, io
    from flask import Response

    period = request.args.get('period', '1m')
    period_days = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}.get(period, 30)
    since = date.today() - timedelta(days=period_days)

    items = Incentive.query.filter(
        Incentive.status == 'approved',
        Incentive.created_at >= str(since),
    ).order_by(Incentive.reviewed_at.desc()).all()

    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['ID', '获奖名称', '类别', '导向', '成员', '工号', '小组', '金额', '激励来源', '获奖年月', '评语'])
    for inc in items:
        common = [inc.id, inc.title, inc.award_type, inc.category_label]
        tail = [inc.amount or '', inc.source_label, inc.reviewed_at.strftime('%Y-%m') if inc.reviewed_at else '', inc.review_comment or '']
        for u in inc.nominees:
            writer.writerow(common + [u.name, u.employee_id, u.group or ''] + tail)
        if inc.external_nominees:
            for name in inc.external_nominees.split(','):
                name = name.strip()
                if name:
                    writer.writerow(common + [name, '', ''] + tail)

    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=incentives.csv'})


@incentive_bp.route('/import-csv', methods=['POST'])
@login_required
def import_csv():
    """Import incentives from CSV. Reviewer/admin only."""
    if not (current_user.has_role('PL', 'XM', 'HR', 'LM') or current_user.is_admin):
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import csv, io
    file = request.files.get('csv_file')
    if not file or not file.filename.lower().endswith('.csv'):
        flash('请选择 CSV 文件', 'danger')
        return redirect(url_for('incentive.index'))

    raw = file.read()
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        flash('编码无法识别', 'danger')
        return redirect(url_for('incentive.index'))

    reader = csv.DictReader(io.StringIO(text))
    required = {'获奖名称', '成员'}
    if not required.issubset(set(reader.fieldnames or [])):
        flash('CSV 缺少必填列：获奖名称, 成员', 'danger')
        return redirect(url_for('incentive.index'))

    # Group rows by ID or title (same ID = same incentive, multiple nominees)
    groups = {}
    for row in reader:
        key = row.get('ID', '').strip() or row.get('获奖名称', '').strip()
        if not key:
            continue
        if key not in groups:
            groups[key] = {'title': row.get('获奖名称', '').strip(), 'rows': []}
        groups[key]['rows'].append(row)

    cat_reverse = {v: k for k, v in Incentive.CATEGORY_LABELS.items()}
    created = 0
    for key, g in groups.items():
        title = g['title']
        if not title:
            continue
        first = g['rows'][0]
        category = cat_reverse.get(first.get('导向', '').strip(), 'professional')
        amount = None
        try:
            amount = float(first.get('金额', '').strip())
        except (ValueError, AttributeError):
            pass
        comment = first.get('评语', '').strip()[:150]
        month_str = first.get('获奖年月', '').strip()

        reviewed_at = datetime.utcnow()
        if month_str:
            try:
                reviewed_at = datetime.strptime(month_str + '-15', '%Y-%m-%d')
            except ValueError:
                pass

        # Collect nominees
        nominee_users = []
        ext_names = []
        for row in g['rows']:
            name = row.get('成员', '').strip()
            eid = row.get('工号', '').strip()
            if eid:
                u = User.query.filter_by(employee_id=eid.lower()).first()
                if u:
                    nominee_users.append(u)
                    continue
            if name:
                u = User.query.filter_by(name=name).first()
                if u:
                    nominee_users.append(u)
                else:
                    ext_names.append(name)

        inc = Incentive(
            title=title, description=title, category=category,
            submitted_by=current_user.id, status='approved',
            amount=amount, review_comment=comment,
            reviewed_by=current_user.id, reviewed_at=reviewed_at,
            nominees=nominee_users,
            external_nominees=','.join(ext_names) if ext_names else None,
        )
        db.session.add(inc)
        created += 1

    db.session.commit()
    flash(f'导入完成：{created} 条激励', 'success')
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
        photo=photo_path,
        submitted_by=current_user.id, nominees=nominees,
        status='approved', amount=amount,
        source=request.form.get('source', 'instant'),
        review_comment=review_comment,
        reviewed_by=current_user.id, reviewed_at=reviewed_at,
    )
    db.session.add(inc)
    db.session.commit()
    flash('激励已录入', 'success')
    return redirect(url_for('incentive.index'))
