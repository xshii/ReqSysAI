from datetime import date, datetime, timedelta, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.constants import MAX_COMMENT_LENGTH
from app.extensions import db
from app.incentive import incentive_bp
from app.models.incentive import Incentive, IncentiveFund, IncentiveReport
from app.models.rant import Rant
from app.models.requirement import Requirement
from app.models.todo import Todo
from app.models.user import User
from app.utils.upload import save_photo


@incentive_bp.route('/')
@login_required
def index():
    """List incentives with status filter."""
    is_reviewer = current_user.has_role('PL', 'XM', 'LM', 'HR') or current_user.is_admin
    status_filter = request.args.get('status', '')
    # Only default to 'submitted' when no URL params at all (first visit)
    if not request.args and is_reviewer:
        status_filter = 'submitted'

    # Ordinary users: only see own submitted items; reviewers see all
    scope = request.args.get('scope', 'all' if is_reviewer else 'mine')
    if not is_reviewer:
        scope = 'mine'

    # Time filter: specific month takes priority over period range
    month_filter = request.args.get('month', '').strip()  # e.g. "2026-03"
    period = request.args.get('period', '1m')

    if month_filter:
        try:
            m_start = date.fromisoformat(month_filter + '-01')
            if m_start.month == 12:
                m_end = m_start.replace(year=m_start.year + 1, month=1)
            else:
                m_end = m_start.replace(month=m_start.month + 1)
            q = Incentive.query.filter(
                Incentive.created_at >= m_start,
                Incentive.created_at < m_end,
            )
        except ValueError:
            month_filter = ''
            q = Incentive.query
    if not month_filter:
        period_days = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}.get(period, 30)
        since = date.today() - timedelta(days=period_days)
        q = Incentive.query.filter(Incentive.created_at >= since)

    if not is_reviewer:
        # Ordinary users: see own items + all approved
        q = q.filter(db.or_(
            Incentive.submitted_by == current_user.id,
            Incentive.status == 'approved',
        ))
    elif scope == 'mine':
        q = q.filter_by(submitted_by=current_user.id)
    if status_filter and status_filter != 'funds':
        q = q.filter_by(status=status_filter)
    search_q = request.args.get('q', '').strip()
    if search_q:
        q = q.filter(db.or_(
            Incentive.title.contains(search_q),
            Incentive.description.contains(search_q),
        ))
    items = q.order_by(Incentive.created_at.desc()).all() if status_filter not in ('funds', 'stats') else []

    users = User.query.filter_by(is_active=True).order_by(User.name).all()

    # Stats data for inline tab — use same time filter
    inc_stats = {}
    stats_period = request.args.get('stats_period', '1y')
    saved_report = None
    if is_reviewer and status_filter == 'stats':
        sp_days = {'3m': 90, '6m': 180, '1y': 365, 'all': 9999}.get(stats_period, 365)
        stats_since = date.today() - timedelta(days=sp_days)
        inc_stats = _build_incentive_stats(since=stats_since)
        saved_report = IncentiveReport.query.filter_by(period=stats_period)\
            .order_by(IncentiveReport.created_at.desc()).first()

    # Fund data for inline tab (reviewers only)
    funds = []
    source_stats = {}
    if is_reviewer and status_filter == 'funds':
        from app.constants import INCENTIVE_SOURCE_LABELS
        funds = IncentiveFund.query.order_by(IncentiveFund.expires_at.asc().nullslast()).all()
        # All approved usage by source
        rows = db.session.query(
            Incentive.source, db.func.coalesce(db.func.sum(Incentive.amount), 0)
        ).filter(Incentive.status == 'approved').group_by(Incentive.source).all()
        used_map = {src: float(amt) for src, amt in rows}
        # Build stats from all sources that have funds or usage
        for f in funds:
            s = source_stats.setdefault(f.source, {'label': f.source_label, 'total': 0, 'used': 0})
            s['total'] += f.total_amount or 0
        for src, used in used_map.items():
            s = source_stats.setdefault(src, {'label': INCENTIVE_SOURCE_LABELS.get(src, src), 'total': 0, 'used': 0})
            s['used'] = used
        # Ensure all configured sources appear (even without funds or usage)
        for src, label in INCENTIVE_SOURCE_LABELS.items():
            source_stats.setdefault(src, {'label': label, 'total': 0, 'used': 0})
        # Detect conflict: same source has both budgeted and unbudgeted funds
        source_types = {}  # source → set of 'budget'/'pool'
        for f in funds:
            t = 'budget' if f.has_budget else 'pool'
            source_types.setdefault(f.source, set()).add(t)
        fund_conflict_keys = [src for src, types in source_types.items() if len(types) > 1]
        fund_conflicts = [source_stats[src]['label'] for src in fund_conflict_keys]

    return render_template('incentive/index.html',
        items=items, users=users, is_reviewer=is_reviewer,
        status_filter=status_filter, scope=scope, period=period,
        month_filter=month_filter, search_q=search_q,
        can_export=is_reviewer or current_user.is_admin,
        today=date.today(),
        funds=funds, source_stats=source_stats,
        fund_conflicts=fund_conflicts if funds else [],
        fund_conflict_keys=fund_conflict_keys if funds else [],
        source_labels=_get_source_labels(),
        inc_stats=inc_stats, stats_period=stats_period, saved_report=saved_report,
        all_funds=IncentiveFund.query.order_by(IncentiveFund.name).all() if is_reviewer else [])


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


@incentive_bp.route('/<int:inc_id>/edit', methods=['POST'])
@login_required
def edit(inc_id):
    """Edit a pending/rejected incentive. Submitter or admin only."""
    inc = db.get_or_404(Incentive, inc_id)
    if current_user.id != inc.submitted_by and not current_user.is_admin:
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))
    if inc.status not in ('submitted', 'pending'):
        flash('已通过的激励不可编辑', 'warning')
        return redirect(url_for('incentive.index'))

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    if not title or not description:
        flash('请填写标题和描述', 'danger')
        return redirect(url_for('incentive.index'))

    inc.title = title
    inc.description = description
    inc.category = request.form.get('category', inc.category)

    nominee_ids = request.form.getlist('nominee_ids', type=int)
    if nominee_ids:
        inc.nominees = User.query.filter(User.id.in_(nominee_ids)).all()
    ext_names = request.form.getlist('external_nominees')
    ext_str = ','.join(n.strip() for n in ext_names if n.strip()) or None
    if ext_str:
        inc.external_nominees = ext_str

    photo_path = save_photo(request.files.get('photo'))
    if photo_path:
        inc.photo = photo_path

    # Re-submit after edit (pending → submitted)
    if inc.status == 'pending':
        inc.status = 'submitted'

    db.session.commit()
    flash('激励已更新', 'success')
    return redirect(url_for('incentive.index'))


@incentive_bp.route('/<int:inc_id>/review', methods=['POST'])
@login_required
def review(inc_id):
    if not (current_user.has_role('PL', 'XM', 'HR', 'LM') or current_user.is_admin):
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    inc = db.get_or_404(Incentive, inc_id)
    action = request.form.get('action')
    description = request.form.get('description', '').strip()
    amount = request.form.get('amount', type=float)

    source = request.form.get('source', 'instant')
    action_labels = {'approve': '通过', 'reject': '拒绝', 'pending': '退回修改'}
    fund_id = request.form.get('fund_id', type=int)
    if action == 'approve':
        inc.status = 'approved'
        inc.amount = amount
        inc.source = source
        inc.fund_id = fund_id
        inc.is_public = 'is_public' in request.form
    elif action == 'reject':
        inc.status = 'rejected'
    elif action == 'pending':
        inc.status = 'pending'
    if description:
        inc.description = description
    comment = request.form.get('review_comment', '').strip()[:MAX_COMMENT_LENGTH]
    inc.review_comment = comment or inc.review_comment
    inc.reviewed_by = current_user.id
    award_month = request.form.get('award_month', '').strip()
    if award_month:
        try:
            inc.reviewed_at = datetime.strptime(award_month + '-15', '%Y-%m-%d')
        except ValueError:
            inc.reviewed_at = datetime.now()
    else:
        inc.reviewed_at = datetime.now()
    from app.services.audit import log_audit
    log_audit(action, 'incentive', inc.id, inc.title, f'{action_labels.get(action, action)} 金额={amount}')
    db.session.commit()
    flash(f'已{action_labels.get(action, action)}', 'success')
    return redirect(url_for('incentive.index'))


@incentive_bp.route('/<int:inc_id>/toggle-public', methods=['POST'])
@login_required
def toggle_public(inc_id):
    """Toggle is_public for approved incentive."""
    if not (current_user.has_role('PL', 'XM', 'HR', 'LM') or current_user.is_admin):
        return jsonify(ok=False, msg='无权限')
    inc = db.get_or_404(Incentive, inc_id)
    inc.is_public = not inc.is_public
    db.session.commit()
    return jsonify(ok=True, is_public=inc.is_public)


@incentive_bp.route('/export-csv')
@login_required
def export_csv():
    """Export approved incentives as CSV. Reviewer/admin only."""
    if not (current_user.has_role('PL', 'XM', 'HR', 'LM') or current_user.is_admin):
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import csv
    import io

    from flask import Response

    period = request.args.get('period', '1m')
    period_days = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}.get(period, 30)
    since = date.today() - timedelta(days=period_days)

    items = Incentive.query.filter(
        Incentive.status == 'approved',
        Incentive.created_at >= since,
    ).order_by(Incentive.reviewed_at.desc()).all()

    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['ID', '获奖名称', '类别', '导向', '提交人', '成员', '工号', '小组', '金额', '资金池', '激励来源', '获奖年月', '事迹描述'])
    # Demo row (ID=0)
    writer.writerow([0, '示例奖项', '(自动)', '专业(选填)', '张三(选填)',
                     '获奖人姓名', 'a00123456(选填)', '(自动)', '500(选填)',
                     '资金池名(选填)', '及时激励(选填)', '2026-03(选填)',
                     '事迹描述(选填) 此行为格式示例，导入时自动跳过'])
    for inc in items:
        fund_name = inc.fund.name if inc.fund else ''
        common = [inc.id, inc.title, inc.award_type, inc.category_label, inc.submitter.name]
        tail = [inc.amount or '', fund_name, inc.source_label, inc.reviewed_at.strftime('%Y-%m') if inc.reviewed_at else '', inc.description or '']
        for u in inc.nominees:
            writer.writerow(common + [u.name, u.employee_id, u.group or ''] + tail)
        if inc.external_nominees:
            for name in inc.external_nominees.split(','):
                name = name.strip()
                if name:
                    writer.writerow(common + [name, '', ''] + tail)

    from urllib.parse import quote
    from flask import current_app
    from app.constants import DEFAULT_SITE_NAME
    site = current_app.config.get('SITE_NAME', DEFAULT_SITE_NAME)
    fname = f"{site}_激励记录_{date.today().strftime('%Y%m%d')}.csv"
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(fname)}"})


@incentive_bp.route('/import-csv', methods=['POST'])
@login_required
def import_csv():
    """Import incentives from CSV. Reviewer/admin only."""
    if not (current_user.has_role('PL', 'XM', 'HR', 'LM') or current_user.is_admin):
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import csv
    import io
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
        if (row.get('ID') or '').strip() == '0':
            continue  # Skip demo row
        key = row.get('ID', '').strip() or row.get('获奖名称', '').strip()
        if not key:
            continue
        if key not in groups:
            groups[key] = {'title': row.get('获奖名称', '').strip(), 'rows': []}
        groups[key]['rows'].append(row)

    cat_reverse = {v: k for k, v in Incentive.CATEGORY_LABELS.items()}
    created = 0
    skipped = 0
    for key, g in groups.items():
        title = g['title']
        if not title:
            continue
        # Skip if ID matches existing; or by title + nominees + month
        try:
            existing_id = int(key)
            if existing_id > 0 and db.session.get(Incentive, existing_id):
                skipped += 1
                continue
        except (ValueError, TypeError):
            pass
        first = g['rows'][0]
        category = cat_reverse.get(first.get('导向', '').strip(), 'professional')
        amount = None
        try:
            amount = float(first.get('金额', '').strip())
        except (ValueError, AttributeError):
            pass
        description = first.get('事迹描述', '').strip()
        comment = first.get('评语', '').strip()[:150]
        month_str = first.get('获奖年月', '').strip()

        reviewed_at = datetime.now()
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

        # Dedup by nominee names + award month
        nominee_names = sorted(u.name for u in nominee_users) + sorted(ext_names)
        if nominee_names and month_str:
            existing = Incentive.query.filter(
                Incentive.title == title,
                Incentive.reviewed_at >= reviewed_at.replace(day=1),
                Incentive.reviewed_at < (reviewed_at.replace(day=28) + timedelta(days=4)).replace(day=1),
            ).all()
            for ex in existing:
                ex_names = sorted(ex.all_nominee_names)
                if ex_names == nominee_names:
                    break
            else:
                existing = []
            if existing:
                skipped += 1
                continue

        # Resolve submitter
        submitter_name = (first.get('提交人') or '').strip()
        submitter_id = current_user.id
        if submitter_name:
            su = User.query.filter_by(name=submitter_name, is_active=True).first()
            if su:
                submitter_id = su.id

        # Resolve fund
        fund_id = None
        fund_name = (first.get('资金池') or '').strip()
        if fund_name:
            fund = IncentiveFund.query.filter_by(name=fund_name).first()
            if fund:
                fund_id = fund.id

        inc = Incentive(
            title=title, description=description or title, category=category,
            submitted_by=submitter_id, status='approved',
            amount=amount, fund_id=fund_id, review_comment=comment,
            reviewed_by=current_user.id, reviewed_at=reviewed_at,
            nominees=nominee_users,
            external_nominees=','.join(ext_names) if ext_names else None,
        )
        db.session.add(inc)
        created += 1

    db.session.commit()
    msg = f'导入完成：{created} 条激励'
    if skipped:
        msg += f'，跳过 {skipped} 条重复'
    flash(msg, 'success')
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
            Requirement.updated_at >= since,
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


@incentive_bp.route('/ai-recommend-candidates', methods=['POST'])
@login_required
def ai_recommend_candidates():
    """AI recommends incentive candidates based on recent work data."""
    if not (current_user.is_admin or current_user.has_role('PL', 'LM', 'XM', 'HR')):
        return jsonify(ok=False, msg='无权限'), 403


    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    since = date.today() - timedelta(days=30)
    users = User.query.filter_by(is_active=True).all()

    lines = [f'近30天团队工作数据（截至 {date.today()}）：\n']
    for u in users:
        done_count = Todo.query.filter(
            Todo.user_id == u.id,
            Todo.created_date >= since,
            Todo.status == 'done').count()
        active_count = Todo.query.filter_by(user_id=u.id, status='todo').count()
        help_count = Todo.query.filter(
            Todo.user_id == u.id, Todo.source == 'help',
            Todo.created_date >= since).count()
        focus_min = db.session.query(db.func.sum(Todo.actual_minutes)).filter(
            Todo.user_id == u.id, Todo.created_date >= since).scalar() or 0
        lines.append(
            f'- {u.name}（{u.group or ""}）：'
            f'完成 {done_count} 个任务，进行中 {active_count} 个，'
            f'协助他人 {help_count} 次，番茄钟 {focus_min} 分钟')

    prompt = get_prompt('incentive_recommend') + '\n\n' + '\n'.join(lines)
    result, raw = call_ollama(prompt)

    if isinstance(result, list):
        return jsonify(ok=True, candidates=result)
    return jsonify(ok=False, raw=raw or '生成失败')


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

    reviewed_at = datetime.now()
    if month_str:
        try:
            reviewed_at = datetime.strptime(month_str + '-15', '%Y-%m-%d')
        except ValueError:
            pass

    nominees = User.query.filter(User.id.in_(nominee_ids)).all()
    fund_id = request.form.get('fund_id', type=int)
    status = request.form.get('status', 'approved')
    if status not in ('approved', 'submitted'):
        status = 'approved'
    is_public = 'is_public' in request.form
    inc = Incentive(
        title=title, description=description or title, category=category,
        photo=photo_path,
        submitted_by=current_user.id, nominees=nominees,
        status=status, amount=amount, fund_id=fund_id,
        is_public=is_public,
        source=request.form.get('source', 'instant'),
        review_comment=review_comment,
        reviewed_by=current_user.id if status == 'approved' else None,
        reviewed_at=reviewed_at if status == 'approved' else None,
    )
    db.session.add(inc)
    db.session.commit()
    flash('激励已录入', 'success')
    return redirect(url_for('incentive.index'))


# ---- Fund Pool (资金池) ----

def _is_fund_viewer():
    return current_user.is_admin or current_user.has_role('PL', 'XM', 'LM', 'HR')


def _build_incentive_stats(since=None):
    """Build stats data for the stats tab."""

    q = Incentive.query.filter_by(status='approved')
    if since:
        q = q.filter(Incentive.reviewed_at >= datetime(since.year, since.month, since.day))
    approved = q.all()
    total_amount = sum(i.amount or 0 for i in approved)
    total_count = len(approved)

    # Per-group distribution
    group_data = {}  # group → {count, amount, people}
    for inc in approved:
        for u in inc.nominees:
            g = u.group or '未分组'
            d = group_data.setdefault(g, {'count': 0, 'amount': 0, 'people': set()})
            d['count'] += 1
            d['amount'] += (inc.amount or 0) / max(len(inc.nominees), 1)
            d['people'].add(u.name)
    # Convert sets to counts
    for v in group_data.values():
        v['people_count'] = len(v['people'])
        del v['people']

    # Per-category distribution
    cat_data = {}
    for inc in approved:
        c = inc.category_label
        d = cat_data.setdefault(c, {'count': 0, 'amount': 0})
        d['count'] += 1
        d['amount'] += inc.amount or 0

    # Per-source distribution
    src_data = {}
    for inc in approved:
        s = inc.source_label
        d = src_data.setdefault(s, {'count': 0, 'amount': 0})
        d['count'] += 1
        d['amount'] += inc.amount or 0

    # Monthly trend (last 6 months)
    today = date.today()
    monthly = {}
    for i in range(6):
        m = today.month - i
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        key = f'{y}-{m:02d}'
        monthly[key] = {'count': 0, 'amount': 0}
    for inc in approved:
        if inc.reviewed_at:
            key = inc.reviewed_at.strftime('%Y-%m')
            if key in monthly:
                monthly[key]['count'] += 1
                monthly[key]['amount'] += inc.amount or 0

    # Top nominees
    nominee_data = {}
    for inc in approved:
        for name in inc.all_nominee_names:
            d = nominee_data.setdefault(name, {'count': 0, 'amount': 0})
            d['count'] += 1
            d['amount'] += (inc.amount or 0) / max(len(inc.all_nominee_names), 1)
    top_nominees = sorted(nominee_data.items(), key=lambda x: -x[1]['amount'])[:15]

    # Status summary (all incentives)
    all_incs = Incentive.query.all()
    status_counts = {}
    for inc in all_incs:
        status_counts[inc.status_label] = status_counts.get(inc.status_label, 0) + 1

    # ---- People stability analysis ----
    all_active_users = User.query.filter_by(is_active=True).all()
    awarded_names = set(nominee_data.keys())

    # Per-group coverage: awarded vs total
    group_coverage = {}
    for u in all_active_users:
        g = u.group or '未分组'
        gc = group_coverage.setdefault(g, {'total': 0, 'awarded': 0, 'not_awarded': []})
        gc['total'] += 1
        if u.name in awarded_names:
            gc['awarded'] += 1
        else:
            gc['not_awarded'].append(u.name)

    # Per-person per-month heatmap (last 6 months)
    person_monthly = {}  # name → {month: count}
    for inc in approved:
        if not inc.reviewed_at:
            continue
        key = inc.reviewed_at.strftime('%Y-%m')
        if key not in monthly:
            continue
        for name in inc.all_nominee_names:
            pm = person_monthly.setdefault(name, {})
            pm[key] = pm.get(key, 0) + 1

    # People who never got awarded (stability risk)
    never_awarded = [u.name for u in all_active_users if u.name not in awarded_names]

    return {
        'total_amount': total_amount,
        'total_count': total_count,
        'group_data': sorted(group_data.items(), key=lambda x: -x[1]['amount']),
        'cat_data': sorted(cat_data.items(), key=lambda x: -x[1]['amount']),
        'src_data': sorted(src_data.items(), key=lambda x: -x[1]['amount']),
        'monthly': sorted(monthly.items()),
        'top_nominees': top_nominees,
        'status_counts': status_counts,
        'all_count': len(all_incs),
        # People stability
        'group_coverage': sorted(group_coverage.items()),
        'person_monthly': person_monthly,
        'month_keys': sorted(monthly.keys()),
        'never_awarded': never_awarded,
        'total_people': len(all_active_users),
        'awarded_people': len(awarded_names),
    }

def _get_source_labels():
    from app.constants import INCENTIVE_SOURCE_LABELS
    return INCENTIVE_SOURCE_LABELS


@incentive_bp.route('/stats/ai-analysis', methods=['POST'])
@login_required
def stats_ai_analysis():
    """AI analysis of incentive stats for people stability."""
    if not (_is_fund_viewer()):
        return jsonify(ok=False, msg='无权限')
    from app.services.ai import call_ollama

    data = request.get_json(silent=True) or {}
    period = data.get('period', '1y')
    period_days = {'3m': 90, '6m': 180, '1y': 365, 'all': 9999}.get(period, 365)
    period_label = {'3m': '近3个月', '6m': '近6个月', '1y': '近1年', 'all': '全部时间'}.get(period, '近1年')
    since = date.today() - timedelta(days=period_days)

    stats = _build_incentive_stats(since=since)
    lines = [
        f'激励统计数据（{period_label}，截至{date.today().isoformat()}）：',
        f'总金额：¥{stats["total_amount"]:.0f}，共{stats["total_count"]}次',
        f'在职人数：{stats["total_people"]}，获奖人数：{stats["awarded_people"]}，覆盖率：{stats["awarded_people"]*100//max(stats["total_people"],1)}%',
        '',
        '小组覆盖情况：',
    ]
    for g, gc in stats['group_coverage']:
        pct = gc['awarded'] * 100 // max(gc['total'], 1)
        lines.append(f'  {g}：{gc["total"]}人，{gc["awarded"]}人获奖({pct}%)，未获奖：{", ".join(gc["not_awarded"]) or "无"}')

    lines.append('')
    lines.append('获奖排行（金额）：')
    for name, nd in stats['top_nominees'][:10]:
        lines.append(f'  {name}：{nd["count"]}次，¥{nd["amount"]:.0f}')

    lines.append('')
    lines.append('月度趋势：')
    for mk, mv in stats['monthly']:
        lines.append(f'  {mk}：{mv["count"]}次，¥{mv["amount"]:.0f}')

    if stats['never_awarded']:
        lines.append('')
        lines.append(f'从未获奖（{len(stats["never_awarded"])}人）：{", ".join(stats["never_awarded"])}')

    # Add category and source breakdown
    lines.append('')
    lines.append('类别分布：')
    for cat, cd in stats['cat_data']:
        lines.append(f'  {cat}：{cd["count"]}次，¥{cd["amount"]:.0f}')
    lines.append('')
    lines.append('来源分布：')
    for src, sd in stats['src_data']:
        lines.append(f'  {src}：{sd["count"]}次，¥{sd["amount"]:.0f}')

    prompt = (
        '你是团队人力稳定性分析师。基于以下激励数据进行分析。\n\n'
        '请严格返回以下JSON格式（不要返回其他内容）：\n'
        '{\n'
        '  "summary": "一句话总结当前激励体系健康度",\n'
        '  "health_score": 75,  // 0-100分，综合健康评分\n'
        '  "findings": [\n'
        '    {"title": "发现标题", "level": "info|warning|danger", "detail": "具体分析"},\n'
        '  ],\n'
        '  "risk_people": [\n'
        '    {"name": "姓名", "reason": "风险原因", "level": "high|medium|low"}\n'
        '  ],\n'
        '  "suggestions": ["建议1", "建议2"]\n'
        '}\n\n'
        '分析角度：\n'
        '1. 激励公平性：各小组人均激励是否均衡\n'
        '2. 覆盖率：未获奖人员是否被忽视\n'
        '3. 频次：有无"激励疲劳"或"激励荒漠"\n'
        '4. 稳定性风险：谁可能因缺乏认可而流失\n'
        '5. 改进建议：具体可操作\n\n'
        '红线：严禁编造数据中不存在的人名或数字。\n\n'
        '数据：\n' + '\n'.join(lines)
    )
    import json as _json

    def _save_report(response_data):
        """Save AI analysis result to DB."""
        report = IncentiveReport(
            period=period,
            data=_json.dumps(response_data, ensure_ascii=False),
            created_by=current_user.id,
        )
        db.session.add(report)
        db.session.commit()

    result, raw = call_ollama(prompt)
    if isinstance(result, dict) and 'findings' in result:
        resp = {'ok': True, 'structured': True, **result}
        _save_report(resp)
        return jsonify(**resp)
    if raw:
        resp = {'ok': True, 'structured': False, 'text': raw}
        _save_report(resp)
        return jsonify(**resp)

    # Fallback: local rule-based analysis when AI unavailable
    findings = []
    risk_people = []
    suggestions = []
    coverage_pct = stats['awarded_people'] * 100 // max(stats['total_people'], 1)

    if coverage_pct < 50:
        findings.append({'title': '激励覆盖率偏低', 'level': 'danger',
            'detail': f'仅{coverage_pct}%的在职人员获得过激励，{len(stats["never_awarded"])}人从未获奖'})
    elif coverage_pct < 75:
        findings.append({'title': '激励覆盖率中等', 'level': 'warning',
            'detail': f'{coverage_pct}%覆盖率，建议关注未获奖人员'})
    else:
        findings.append({'title': '激励覆盖率良好', 'level': 'info',
            'detail': f'{coverage_pct}%覆盖率'})

    # Group imbalance
    if stats['group_data']:
        amounts = [gd['amount'] for _, gd in stats['group_data']]
        if len(amounts) >= 2 and max(amounts) > 0:
            ratio = min(amounts) / max(amounts) if min(amounts) > 0 else 0
            if ratio < 0.3:
                findings.append({'title': '小组间激励差距较大', 'level': 'warning',
                    'detail': f'最高组 ¥{max(amounts):.0f} vs 最低组 ¥{min(amounts):.0f}'})

    # Top nominee concentration
    if stats['top_nominees'] and stats['total_amount'] > 0:
        top3_amt = sum(nd['amount'] for _, nd in stats['top_nominees'][:3])
        top3_pct = top3_amt * 100 / stats['total_amount']
        if top3_pct > 50:
            findings.append({'title': '激励集中度过高', 'level': 'warning',
                'detail': f'前3名占总金额{top3_pct:.0f}%，存在"激励疲劳"风险'})

    # Never awarded → risk
    for name in stats['never_awarded']:
        risk_people.append({'name': name, 'reason': '从未获奖', 'level': 'medium'})

    if coverage_pct < 60:
        suggestions.append('扩大激励覆盖面，关注长期未获奖人员')
    suggestions.append('定期review各组激励分布，确保公平性')
    if stats['never_awarded']:
        suggestions.append(f'重点关注{len(stats["never_awarded"])}位从未获奖成员的工作表现和贡献')

    score = min(100, max(0, coverage_pct + (20 if len(findings) <= 2 else 0) - len(risk_people) * 2))
    resp = {'ok': True, 'structured': True,
        'summary': f'激励覆盖率{coverage_pct}%，{len(stats["never_awarded"])}人从未获奖',
        'health_score': score, 'findings': findings,
        'risk_people': risk_people[:10], 'suggestions': suggestions}
    _save_report(resp)
    return jsonify(**resp)


@incentive_bp.route('/stats/report/<int:report_id>/delete', methods=['POST'])
@login_required
def stats_report_delete(report_id):
    if not _is_fund_viewer():
        return jsonify(ok=False, msg='无权限')
    report = db.get_or_404(IncentiveReport, report_id)
    db.session.delete(report)
    db.session.commit()
    return jsonify(ok=True)


@incentive_bp.route('/funds')
@login_required
def fund_list():
    """Redirect to index funds tab."""
    return redirect(url_for('incentive.index', status='funds', scope='all'))


@incentive_bp.route('/funds/add', methods=['POST'])
@login_required
def fund_add():
    if not _is_fund_viewer():
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    name = request.form.get('name', '').strip()
    source = request.form.get('source', 'instant')
    amount = request.form.get('amount', type=float)
    expires = request.form.get('expires_at', '').strip()
    note = request.form.get('note', '').strip()

    if not name:
        flash('请填写名称', 'danger')
        return redirect(url_for('incentive.fund_list'))

    fund = IncentiveFund(
        name=name, source=source, total_amount=amount,
        note=note or None, created_by=current_user.id,
    )
    if expires:
        try:
            fund.expires_at = date.fromisoformat(expires)
        except ValueError:
            pass
    db.session.add(fund)
    db.session.commit()
    flash('资金条目已添加', 'success')
    return redirect(url_for('incentive.fund_list'))


@incentive_bp.route('/funds/<int:fund_id>/edit', methods=['POST'])
@login_required
def fund_edit(fund_id):
    if not _is_fund_viewer():
        return jsonify(ok=False, msg='无权限')
    fund = db.get_or_404(IncentiveFund, fund_id)
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if name:
        fund.name = name
    amt = data.get('amount')
    if amt == '' or amt is None:
        fund.total_amount = None
    else:
        try:
            fund.total_amount = float(amt)
        except (ValueError, TypeError):
            pass
    source = data.get('source', '').strip()
    if source:
        fund.source = source
    expires = data.get('expires_at', '').strip()
    if expires:
        try:
            fund.expires_at = date.fromisoformat(expires)
        except ValueError:
            pass
    elif expires == '':
        fund.expires_at = None
    note = data.get('note')
    if note is not None:
        fund.note = note.strip() or None
    db.session.commit()
    return jsonify(ok=True)


@incentive_bp.route('/funds/<int:fund_id>/delete', methods=['POST'])
@login_required
def fund_delete(fund_id):
    if not _is_fund_viewer():
        if request.is_json:
            return jsonify(ok=False, msg='无权限')
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))
    fund = db.get_or_404(IncentiveFund, fund_id)
    db.session.delete(fund)
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True)
    flash('已删除', 'success')
    return redirect(url_for('incentive.fund_list'))


@incentive_bp.route('/funds/export-csv')
@login_required
def fund_export_csv():
    """Export fund pool as CSV."""
    if not _is_fund_viewer():
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import csv
    import io

    from flask import Response

    funds = IncentiveFund.query.order_by(IncentiveFund.source, IncentiveFund.expires_at).all()

    # Current month usage per source
    today = date.today()
    month_start = today.replace(day=1)
    month_rows = db.session.query(
        Incentive.source, db.func.coalesce(db.func.sum(Incentive.amount), 0)
    ).filter(
        Incentive.status == 'approved',
        Incentive.reviewed_at >= datetime(month_start.year, month_start.month, month_start.day),
    ).group_by(Incentive.source).all()
    month_used_map = {src: float(amt) for src, amt in month_rows}

    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['ID', '名称', '金额', '激励来源', '截止日期', '备注', '已使用', '本月使用', '使用率'])
    # Demo row (ID=0)
    writer.writerow([0, '示例资金池', '50000(选填,空=公共池)', '及时激励(选填)', '2026-12-31(选填)',
                     '备注(选填) 此行为格式示例，导入时自动跳过', '', '', ''])
    for f in funds:
        used = f.used_amount
        month_used = month_used_map.get(f.source, 0)
        pct = f'{round(used / f.total_amount * 100)}%' if f.has_budget else '公共池'
        writer.writerow([
            f.id,
            f.name,
            f.total_amount if f.has_budget else '',
            f.source_label,
            f.expires_at.isoformat() if f.expires_at else '',
            f.note or '',
            used, month_used, pct,
        ])
    from urllib.parse import quote
    from flask import current_app as _ca
    from app.constants import DEFAULT_SITE_NAME
    site = _ca.config.get('SITE_NAME', DEFAULT_SITE_NAME)
    fname = f"{site}_资金池_{date.today().strftime('%Y%m%d')}.csv"
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(fname)}"})


@incentive_bp.route('/funds/add-source', methods=['POST'])
@login_required
def fund_add_source():
    """Add a custom incentive source type."""
    if not _is_fund_viewer():
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    from app.constants import INCENTIVE_SOURCE_LABELS
    from app.utils.pinyin import to_pinyin
    label = request.form.get('label', '').strip()
    if not label:
        flash('请填写来源名称', 'danger')
        return redirect(url_for('incentive.fund_list'))
    # Auto-generate key from pinyin
    key = to_pinyin(label).replace(' ', '_').lower()[:20]
    if not key:
        key = 'custom_' + str(len(INCENTIVE_SOURCE_LABELS))
    if key in INCENTIVE_SOURCE_LABELS:
        flash(f'来源「{label}」已存在', 'warning')
        return redirect(url_for('incentive.fund_list'))

    # Persist to constants by writing to a simple JSON file
    import json
    import os
    custom_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'custom_sources.json')
    existing = {}
    if os.path.exists(custom_path):
        with open(custom_path, 'r', encoding='utf-8') as fp:
            existing = json.load(fp)
    existing[key] = label
    with open(custom_path, 'w', encoding='utf-8') as fp:
        json.dump(existing, fp, ensure_ascii=False, indent=2)

    flash(f'激励来源「{label}」已添加', 'success')
    return redirect(url_for('incentive.fund_list'))


@incentive_bp.route('/funds/delete-source', methods=['POST'])
@login_required
def fund_delete_source():
    """Delete a custom incentive source."""
    if not _is_fund_viewer():
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import json
    import os

    from app.constants import _INCENTIVE_SOURCE_DEFAULTS
    data = request.get_json(silent=True) or {}
    key = data.get('key') or request.form.get('key', '')
    key = key.strip()
    if not key or key in _INCENTIVE_SOURCE_DEFAULTS:
        if request.is_json:
            return jsonify(ok=False, msg='内置来源不可删除')
        flash('内置来源不可删除', 'warning')
        return redirect(url_for('incentive.fund_list'))

    custom_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'custom_sources.json')
    if os.path.exists(custom_path):
        with open(custom_path, 'r', encoding='utf-8') as fp:
            existing = json.load(fp)
        if key in existing:
            del existing[key]
            with open(custom_path, 'w', encoding='utf-8') as fp:
                json.dump(existing, fp, ensure_ascii=False, indent=2)
    if request.is_json:
        return jsonify(ok=True)
    flash('来源已删除', 'success')
    return redirect(url_for('incentive.fund_list'))


@incentive_bp.route('/funds/import-csv', methods=['POST'])
@login_required
def fund_import_csv():
    """Import fund items from CSV."""
    if not _is_fund_viewer():
        flash('无权限', 'danger')
        return redirect(url_for('incentive.index'))

    import csv
    import io

    from app.constants import INCENTIVE_SOURCE_LABELS
    source_rev = {v: k for k, v in INCENTIVE_SOURCE_LABELS.items()}

    file = request.files.get('csv_file')
    if not file or not file.filename.lower().endswith('.csv'):
        flash('请选择 CSV 文件', 'danger')
        return redirect(url_for('incentive.fund_list'))

    raw = file.read()
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        flash('编码无法识别', 'danger')
        return redirect(url_for('incentive.fund_list'))

    reader = csv.DictReader(io.StringIO(text))
    if not {'名称'}.issubset(set(reader.fieldnames or [])):
        flash('CSV 缺少必填列：名称', 'danger')
        return redirect(url_for('incentive.fund_list'))

    created = 0
    skipped = 0
    for row in reader:
        if (row.get('ID') or '').strip() == '0':
            continue  # Skip demo row
        name = (row.get('名称') or '').strip()
        if not name:
            continue
        amt_str = (row.get('金额') or '').strip()
        amt = None
        if amt_str:
            try:
                amt = float(amt_str)
            except ValueError:
                pass
        src_label = (row.get('激励来源') or '').strip()
        source = source_rev.get(src_label, 'instant')
        expires = (row.get('截止日期') or '').strip()
        note = (row.get('备注') or '').strip()

        # Skip if already exists (same name + source)
        existing = IncentiveFund.query.filter_by(name=name, source=source).first()
        if existing:
            # Update existing
            existing.total_amount = amt
            existing.note = note or existing.note
            if expires:
                try:
                    existing.expires_at = date.fromisoformat(expires)
                except ValueError:
                    pass
            skipped += 1
            continue
        fund = IncentiveFund(
            name=name, source=source, total_amount=amt,
            note=note or None, created_by=current_user.id,
        )
        if expires:
            try:
                fund.expires_at = date.fromisoformat(expires)
            except ValueError:
                pass
        db.session.add(fund)
        created += 1

    db.session.commit()
    msg = f'导入完成：{created} 条资金'
    if skipped:
        msg += f'，跳过 {skipped} 条重复'
    flash(msg, 'success')
    return redirect(url_for('incentive.fund_list'))
