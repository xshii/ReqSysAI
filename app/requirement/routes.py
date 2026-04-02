from collections import namedtuple
from datetime import date

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

TodoProgress = namedtuple('TodoProgress', 'total done')

from app.extensions import db
from app.models.project import Project
from app.models.requirement import Activity, Comment, Requirement
from app.models.todo import Todo, TodoItem, todo_requirements
from app.models.user import User
from app.requirement import requirement_bp
from app.requirement.forms import CommentForm, RequirementForm

PER_PAGE = 20


def _resolve_assignee(name_str):
    """Resolve assignee from text. Returns (user_id, assignee_name)."""
    if not name_str:
        return None, None
    user = User.query.filter_by(name=name_str.strip(), is_active=True).first()
    if user:
        return user.id, None
    return None, name_str.strip()


def _log_activity(req, action, detail=None):
    db.session.add(Activity(
        requirement_id=req.id, user_id=current_user.id,
        action=action, detail=detail,
    ))


@requirement_bp.route('/')
@login_required
def requirement_list():
    query = Requirement.query.options(
        joinedload(Requirement.project),
        joinedload(Requirement.assignee),
    )

    # Filters
    status = request.args.get('status')
    priority = request.args.get('priority')
    category = request.args.get('category', '').strip()
    project_id = request.args.get('project_id', type=int)
    include_sub = request.args.get('include_sub', '1') == '1'
    # 非 PL/PM/FO 默认只看自己是责任人的需求
    _is_lead = current_user.is_admin or current_user.has_role('PL', 'PM', 'FO', 'LM', 'XM')
    if 'assignee_id' in request.args:
        assignee_id = request.args.get('assignee_id', type=int)
    else:
        assignee_id = None if _is_lead else current_user.id
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')

    if status:
        query = query.filter_by(status=status)
    if priority:
        query = query.filter_by(priority=priority)
    if category:
        if category.startswith('l2:'):
            # L2-only filter: match suffix after '-'
            l2_val = category[3:]
            query = query.filter(Requirement.category.like('%-' + l2_val))
        else:
            # Match category_l1 (prefix before '-') or exact category
            query = query.filter(
                db.or_(Requirement.category == category,
                       Requirement.category.like(category + '-%'))
            )
    if project_id:
        if include_sub:
            child_ids = [c.id for c in Project.query.filter_by(parent_id=project_id).all()]
            query = query.filter(Requirement.project_id.in_([project_id] + child_ids))
        else:
            query = query.filter_by(project_id=project_id)
    if assignee_id is not None and assignee_id == 0:
        query = query.filter(Requirement.assignee_id.is_(None), Requirement.assignee_name.is_(None))
    elif assignee_id:
        query = query.filter_by(assignee_id=assignee_id)
    if search:
        query = query.filter(
            db.or_(Requirement.title.contains(search), Requirement.description.contains(search), Requirement.category.contains(search))
        )
    # 隐藏项目：直接URL指定project_id时拦截，否则从查询中排除
    if project_id and project_id in g.hidden_pids:
        abort(403)
    if g.hidden_pids:
        query = query.filter(Requirement.project_id.notin_(g.hidden_pids))

    # Sort
    today_ = date.today()
    if sort == 'urgency' or sort == 'newest':
        # Group: 0=overdue, 1=active(not done/closed), 2=done/closed
        sort_group = db.case(
            (db.and_(Requirement.due_date < today_, Requirement.status.notin_(['done', 'closed'])), 0),
            (Requirement.status.in_(['done', 'closed']), 2),
            else_=1,
        )
        # remaining_pct / remaining_days → higher = more urgent → sort desc
        remaining_days = db.func.max(db.func.julianday(Requirement.due_date) - db.func.julianday(today_.isoformat()), 1)
        remaining_pct = 100 - db.func.coalesce(Requirement.completion, 0)
        urgency = remaining_pct / remaining_days
        # Done/closed: sort by days finished ahead of due_date (due - updated), desc
        ahead_days = db.func.julianday(Requirement.due_date) - db.func.julianday(Requirement.updated_at)
        query = query.order_by(sort_group, urgency.desc(), ahead_days.desc(), Requirement.due_date.asc().nullslast())
    else:
        if sort == 'assignee':
            # Sort by assignee pinyin (join User table)
            query = query.outerjoin(User, Requirement.assignee_id == User.id)\
                         .order_by(db.func.coalesce(User.pinyin, User.name, Requirement.assignee_name, 'zzz').asc())
        else:
            order = {
                'oldest': Requirement.created_at.asc(),
                'priority': db.case({'high': 0, 'medium': 1, 'low': 2}, value=Requirement.priority),
                'due_date': Requirement.due_date.asc().nullslast(),
            }.get(sort, Requirement.created_at.desc())
            query = query.order_by(order)

    page = request.args.get('page', 1, type=int)
    pagination = query.paginate(page=page, per_page=PER_PAGE, error_out=False)

    # Todo progress per requirement
    req_ids = [r.id for r in pagination.items]
    todo_counts = {}
    if req_ids:
        rows = db.session.query(
            todo_requirements.c.requirement_id,
            db.func.count(Todo.id),
            db.func.sum(db.case((Todo.status == 'done', 1), else_=0)),
        ).join(Todo, Todo.id == todo_requirements.c.todo_id)\
         .filter(todo_requirements.c.requirement_id.in_(req_ids))\
         .group_by(todo_requirements.c.requirement_id).all()
        for rid, total, done in rows:
            todo_counts[rid] = TodoProgress(total=total, done=int(done or 0))

    # Per-requirement weighted completion (uses model property)
    for r in pagination.items:
        r._weighted_pct = r.weighted_completion

    # Weighted AI ratio for current filter
    ai_weighted_sum = sum(r.ai_ratio * r.estimate_days for r in pagination.items if r.ai_ratio and r.estimate_days)
    ai_days_sum = sum(r.estimate_days for r in pagination.items if r.ai_ratio is not None and r.estimate_days)
    ai_ratio_weighted = round(ai_weighted_sum / ai_days_sum) if ai_days_sum else None

    # Weighted completion progress for current filter
    _active_reqs = [r for r in pagination.items if r.status != 'closed']
    def _pct(r):
        return 100 if r.status == 'done' else (r.completion or 0)
    comp_weighted_sum = sum(_pct(r) * (r.estimate_days or 1) for r in _active_reqs)
    comp_days_sum = sum((r.estimate_days or 1) for r in _active_reqs)
    completion_weighted = round(comp_weighted_sum / comp_days_sum) if comp_days_sum else None

    # Load saved diagnostic results for this project
    saved_diag = []
    if project_id:
        import json

        from app.models.site_setting import SiteSetting
        raw = SiteSetting.get(f'diag_issues_{project_id}', '')
        if raw:
            try:
                saved_diag = json.loads(raw)
            except Exception:
                pass

    # Assignee filter: project members if project selected, else all users
    if project_id:
        from app.models.project_member import ProjectMember
        if include_sub:
            child_ids = [c.id for c in Project.query.filter_by(parent_id=project_id).all()]
            member_uids = list({m.user_id for m in ProjectMember.query.filter(
                ProjectMember.project_id.in_([project_id] + child_ids)).all() if m.user_id})
        else:
            member_uids = [m.user_id for m in ProjectMember.query.filter_by(project_id=project_id).all() if m.user_id]
        filter_users = User.query.filter(User.id.in_(member_uids)).order_by(User.name).all() if member_uids else []
    else:
        filter_users = User.query.filter_by(is_active=True).order_by(User.name).all()

    # Build category options for filter dropdown (L1 groups with L2 items)
    # Scope to current project if selected, so dropdown shows relevant categories
    cat_rows = db.session.query(Requirement.category).filter(
        Requirement.category.isnot(None), Requirement.category != '',
    )
    if project_id:
        _cat_pids = [project_id]
        if include_sub:
            _cat_pids += [c.id for c in Project.query.filter_by(parent_id=project_id).all()]
        cat_rows = cat_rows.filter(Requirement.project_id.in_(_cat_pids))
    if g.hidden_pids:
        cat_rows = cat_rows.filter(Requirement.project_id.notin_(g.hidden_pids))
    all_cats = sorted({c for (c,) in cat_rows.distinct() if c and c.strip()})
    # Build {l1: [l2_full_category, ...]} and unique L2 list
    from collections import OrderedDict
    category_tree = OrderedDict()
    category_l2s = sorted({c.split('-', 1)[1] for c in all_cats if '-' in c})
    for c in all_cats:
        if '-' in c:
            l1 = c.split('-', 1)[0]
        else:
            l1 = c
        category_tree.setdefault(l1, [])
        if c != l1:
            category_tree[l1].append(c)

    return render_template('requirement/list.html',
        pagination=pagination, requirements=pagination.items,
        projects=[p for p in Project.query.all() if p.id not in g.hidden_pids],
        users=filter_users,
        statuses=Requirement.STATUS_LABELS, priorities=Requirement.PRIORITY_LABELS,
        category_tree=category_tree, category_l2s=category_l2s, all_cats=all_cats, cur_category=category,
        cur_status=status, cur_priority=priority, cur_project=project_id,
        cur_assignee=assignee_id, cur_search=search, cur_sort=sort,
        include_sub=include_sub,
        todo_counts=todo_counts, ai_ratio_weighted=ai_ratio_weighted,
        completion_weighted=completion_weighted, saved_diag=saved_diag,
        today=today_,
    )


@requirement_bp.route('/new', methods=['GET', 'POST'])
@login_required
def requirement_create():
    form = _build_requirement_form()
    if request.method == 'GET':
        from datetime import date
        form.due_date.data = form.due_date.data or date.today()
        pid = request.args.get('project_id', type=int)
        if pid and any(pid == c[0] for c in form.project_id.choices):
            form.project_id.data = pid
    if form.validate_on_submit():
        a_id, a_name = _resolve_assignee(request.form.get('assignee_name', ''))
        req = Requirement(
            number=Requirement.generate_number(),
            title=form.title.data,
            description=form.description.data,
            project_id=form.project_id.data,
            priority=form.priority.data,
            assignee_id=a_id,
            assignee_name=a_name,
            start_date=form.start_date.data,
            due_date=form.due_date.data,
            estimate_days=form.estimate_days.data,
            code_lines=form.code_lines.data,
            test_cases=form.test_cases.data,
            ai_ratio=form.ai_ratio.data,
            source=form.source.data or 'coding',
            category=form.category.data or None,
            created_by=current_user.id,
        )
        db.session.add(req)
        db.session.flush()
        _log_activity(req, 'created', f'创建了需求「{req.title}」')

        # Create sub-requirements
        sub_titles = request.form.getlist('sub_title')
        sub_types = request.form.getlist('sub_type')
        sub_assignees = request.form.getlist('sub_assignee')
        sub_days = request.form.getlist('sub_days')
        sub_est_lines = request.form.getlist('sub_est_lines')
        sub_est_cases = request.form.getlist('sub_est_cases')
        sub_ai_ratios = request.form.getlist('sub_ai_ratio')
        for i, st in enumerate(sub_titles):
            st = st.strip()
            if st:
                sub_type = sub_types[i] if i < len(sub_types) else 'analysis'
                assignee = None
                assignee_name_ext = None
                if i < len(sub_assignees) and sub_assignees[i].strip():
                    val = sub_assignees[i].strip()
                    try:
                        assignee = int(val)
                    except ValueError:
                        # Try match by name
                        a_id, a_name = _resolve_assignee(val)
                        assignee = a_id
                        assignee_name_ext = a_name
                try:
                    days = float(sub_days[i]) if i < len(sub_days) and sub_days[i] else None
                except (ValueError, IndexError):
                    days = None
                try:
                    est_lines = int(sub_est_lines[i]) if i < len(sub_est_lines) and sub_est_lines[i] else None
                except (ValueError, IndexError):
                    est_lines = None
                try:
                    est_cases = int(sub_est_cases[i]) if i < len(sub_est_cases) and sub_est_cases[i] else None
                except (ValueError, IndexError):
                    est_cases = None
                sub_ai = None
                try:
                    sub_ai = int(sub_ai_ratios[i]) if i < len(sub_ai_ratios) and sub_ai_ratios[i] else None
                except (ValueError, IndexError):
                    pass
                sub = Requirement(
                    number=Requirement.generate_child_number(req.number),
                    title=st,
                    project_id=req.project_id,
                    priority=req.priority,
                    start_date=req.start_date,
                    due_date=req.due_date,
                    assignee_id=assignee,
                    assignee_name=assignee_name_ext,
                    estimate_days=days,
                    code_lines=est_lines if sub_type == 'coding' else None,
                    test_cases=est_cases if sub_type == 'testing' else None,
                    ai_ratio=sub_ai if sub_ai is not None else req.ai_ratio,
                    parent_id=req.id,
                    source=sub_type,
                    created_by=current_user.id,
                )
                db.session.add(sub)

        # Auto-sum sub-requirement days
        sub_total = sum(s.estimate_days or 0 for s in db.session.new if isinstance(s, Requirement) and s.parent_id == req.id)
        if sub_total > 0:
            req.estimate_days = sub_total

        db.session.commit()
        flash(f'需求 {req.number} 创建成功', 'success')
        return redirect(url_for('requirement.requirement_detail', req_id=req.id))
    if request.method == 'POST':
        flash('请检查必填项（标题、截止日期）', 'danger')
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    existing_categories = sorted(set(
        r.category for r in db.session.query(Requirement.category).filter(Requirement.category.isnot(None)).distinct()
    ))
    return render_template('requirement/form.html', form=form, title='创建需求', users=users, existing_categories=existing_categories)


@requirement_bp.route('/<int:req_id>')
@login_required
def requirement_detail(req_id):
    from datetime import date as d_date
    req = db.get_or_404(Requirement, req_id)
    if req.project_id and req.project_id in g.hidden_pids:
        abort(403)
    comment_form = CommentForm()
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('requirement/detail.html', req=req,
                           comment_form=comment_form, today=d_date.today(), users=users)


@requirement_bp.route('/<int:req_id>/edit', methods=['GET', 'POST'])
@login_required
def requirement_edit(req_id):
    req = db.get_or_404(Requirement, req_id)
    form = _build_requirement_form(obj=req)
    if form.validate_on_submit():
        req.title = form.title.data
        req.description = form.description.data
        req.project_id = form.project_id.data
        req.priority = form.priority.data
        a_id, a_name = _resolve_assignee(request.form.get('assignee_name', ''))
        req.assignee_id = a_id
        req.assignee_name = a_name
        req.start_date = form.start_date.data
        req.due_date = form.due_date.data
        req.estimate_days = form.estimate_days.data
        req.code_lines = form.code_lines.data
        req.test_cases = form.test_cases.data
        req.ai_ratio = form.ai_ratio.data
        req.source = form.source.data or 'coding'
        req.category = form.category.data or None
        # Handle new sub-requirements (same as create)
        sub_titles = request.form.getlist('sub_title')
        sub_types = request.form.getlist('sub_type')
        sub_days = request.form.getlist('sub_days')
        sub_assignees = request.form.getlist('sub_assignee')
        sub_est_lines = request.form.getlist('sub_est_lines')
        sub_est_cases = request.form.getlist('sub_est_cases')
        sub_ai_ratios = request.form.getlist('sub_ai_ratio')
        for i, st in enumerate(sub_titles):
            st = st.strip()
            if not st:
                continue
            sub_type = sub_types[i] if i < len(sub_types) else 'coding'
            try:
                days = float(sub_days[i]) if i < len(sub_days) and sub_days[i] else None
            except (ValueError, IndexError):
                days = None
            assignee_name_sub = sub_assignees[i].strip() if i < len(sub_assignees) else ''
            a_id_sub, a_name_sub = _resolve_assignee(assignee_name_sub) if assignee_name_sub else (None, None)
            try:
                est_lines = int(sub_est_lines[i]) if i < len(sub_est_lines) and sub_est_lines[i] else None
            except (ValueError, IndexError):
                est_lines = None
            try:
                est_cases = int(sub_est_cases[i]) if i < len(sub_est_cases) and sub_est_cases[i] else None
            except (ValueError, IndexError):
                est_cases = None
            sub_ai = None
            try:
                sub_ai = int(sub_ai_ratios[i]) if i < len(sub_ai_ratios) and sub_ai_ratios[i] else None
            except (ValueError, IndexError):
                pass
            sub = Requirement(
                number=Requirement.generate_child_number(req.number),
                title=st, project_id=req.project_id, priority=req.priority,
                start_date=req.start_date, due_date=req.due_date,
                assignee_id=a_id_sub, assignee_name=a_name_sub,
                estimate_days=days,
                code_lines=est_lines if sub_type == 'coding' else None,
                test_cases=est_cases if sub_type == 'testing' else None,
                ai_ratio=sub_ai if sub_ai is not None else req.ai_ratio,
                parent_id=req.id, source=sub_type, created_by=current_user.id,
            )
            db.session.add(sub)
        _log_activity(req, 'edited', '编辑了需求')
        db.session.commit()
        flash('需求更新成功', 'success')
        return redirect(url_for('requirement.requirement_detail', req_id=req.id))
    if request.method == 'POST':
        flash('请检查必填项（标题、截止日期）', 'danger')
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    existing_categories = sorted(set(
        r.category for r in db.session.query(Requirement.category).filter(Requirement.category.isnot(None)).distinct()
    ))
    return render_template('requirement/form.html', form=form, title=f'编辑需求 - {req.number}', users=users, req=req, existing_categories=existing_categories)


@requirement_bp.route('/<int:req_id>/status', methods=['POST'])
@login_required
def requirement_status(req_id):
    req = db.get_or_404(Requirement, req_id)
    new_status = request.form.get('status')
    if new_status not in req.allowed_next_statuses:
        flash('不允许的状态流转', 'danger')
    else:
        old_status = req.status
        old_label = req.status_label
        req.status = new_status
        if new_status != 'done':
            req.completion = 0
        else:
            req.completion = 100
        _log_activity(req, 'status_changed', f'{old_label} → {req.status_label}')
        db.session.commit()
        from app.services.events import fire, requirement_status_changed
        fire(requirement_status_changed, requirement=req, old_status=old_status, new_status=new_status)
        flash(f'状态已更新为「{req.status_label}」', 'success')
    # If changed from parent requirement page, redirect back to parent
    back_id = request.form.get('back_to', type=int) or req.parent_id or req.id
    return redirect(url_for('requirement.requirement_detail', req_id=back_id))


@requirement_bp.route('/<int:req_id>/delete', methods=['POST'])
@login_required
def requirement_delete(req_id):
    req = db.get_or_404(Requirement, req_id)
    parent_id = req.parent_id
    number = req.number
    # Delete children first
    for child in req.children:
        for c in child.comments:
            db.session.delete(c)
        for a in child.activities:
            db.session.delete(a)
        child.requirements = []  # clear todo associations
        db.session.delete(child)
    # Delete self
    for c in req.comments:
        db.session.delete(c)
    for a in req.activities:
        db.session.delete(a)
    req.requirements = []
    from app.services.audit import log_audit
    children_count = len(req.children)
    log_audit('delete', 'requirement', req.id, number,
              f'删除需求 {number} {req.title}' + (f'（含{children_count}个子需求）' if children_count else ''))
    db.session.delete(req)
    db.session.commit()
    flash(f'需求 {number} 已删除', 'success')
    if parent_id:
        return redirect(url_for('requirement.requirement_detail', req_id=parent_id))
    return redirect(url_for('requirement.requirement_list'))


@requirement_bp.route('/<int:req_id>/status-api', methods=['POST'])
@login_required
def requirement_status_api(req_id):
    """JSON API for kanban drag status change."""
    req = db.get_or_404(Requirement, req_id)
    data = request.get_json() or {}
    new_status = data.get('status', '')
    force = data.get('force', False)  # kanban drag allows free transition
    if not force and new_status not in req.allowed_next_statuses:
        return jsonify(ok=False, msg=f'不允许从「{req.status_label}」流转到该状态')
    if new_status not in Requirement.STATUS_LABELS:
        return jsonify(ok=False, msg='无效的状态')
    old_status = req.status
    old_label = req.status_label
    req.status = new_status
    # Reset completion on manual status transition (except done)
    if new_status != 'done':
        req.completion = 0
    else:
        req.completion = 100
    _log_activity(req, 'status_changed', f'{old_label} → {req.status_label}')
    db.session.commit()
    from app.services.events import fire, requirement_status_changed
    fire(requirement_status_changed, requirement=req, old_status=old_status, new_status=new_status)
    return jsonify(ok=True, status=new_status, label=req.status_label, color=req.status_color)


@requirement_bp.route('/<int:req_id>/completion-api', methods=['POST'])
@login_required
def requirement_completion_api(req_id):
    """JSON API for kanban drag completion change."""
    req = db.get_or_404(Requirement, req_id)
    data = request.get_json() or {}
    pct = data.get('completion', 0)
    if pct < 0 or pct > 100 or pct % 10 != 0:
        return jsonify(ok=False, msg='完成率须为0-100的10的倍数')
    req.completion = pct
    db.session.commit()
    return jsonify(ok=True, completion=pct)


@requirement_bp.route('/<int:req_id>/field-api', methods=['POST'])
@login_required
def requirement_field_api(req_id):
    """JSON API for inline field editing on detail page."""
    req = db.get_or_404(Requirement, req_id)
    data = request.get_json() or {}
    field = data.get('field', '')
    value = data.get('value')

    ALLOWED = {
        'title': str, 'description': str, 'category': str,
        'priority': str, 'source': str,
        'estimate_days': float, 'code_lines': int, 'test_cases': int,
        'ai_ratio': int, 'start_date': str, 'due_date': str,
        'assignee_name': str,
    }
    if field not in ALLOWED:
        return jsonify(ok=False, msg=f'不支持编辑字段: {field}')

    # Type conversion
    if field in ('start_date', 'due_date'):
        from datetime import date as d_date
        try:
            value = d_date.fromisoformat(value) if value else None
        except ValueError:
            return jsonify(ok=False, msg='日期格式错误')
    elif field == 'assignee_name':
        old_display = req.assignee_display
        a_id, a_name = _resolve_assignee(value or '')
        req.assignee_id = a_id
        req.assignee_name = a_name
        # Compute new display directly (relationship cache is stale)
        if a_id:
            new_user = db.session.get(User, a_id)
            new_display = new_user.name if new_user else a_name or '未分配'
        else:
            new_display = a_name or '未分配'
        if old_display != new_display:
            _log_activity(req, 'edited', f'负责人: {old_display} → {new_display}')
        db.session.commit()
        return jsonify(ok=True, display=new_display)
    elif ALLOWED[field] in (int, float):
        try:
            value = ALLOWED[field](value) if value not in (None, '') else None
        except (ValueError, TypeError):
            return jsonify(ok=False, msg='数值格式错误')
    else:
        value = str(value).strip() if value else None

    # Validate required fields
    if field == 'title' and not value:
        return jsonify(ok=False, msg='标题不能为空')

    old_val = getattr(req, field)
    if old_val == value:
        # No change, skip
        resp = {'ok': True, 'value': value}
        if field == 'priority':
            resp['label'] = req.priority_label
            resp['color'] = req.priority_color
        elif field == 'source':
            resp['label'] = req.source_label
        elif field == 'category':
            resp['label'] = req.category_label
        return jsonify(**resp)
    setattr(req, field, value)

    # Build response with labels
    resp = {'ok': True, 'value': value}
    FIELD_NAMES = {
        'title': '标题', 'description': '描述', 'category': '分类',
        'priority': '优先级', 'source': '类型',
        'estimate_days': '预估工期', 'code_lines': '代码量',
        'test_cases': '测试用例', 'ai_ratio': 'AI辅助',
        'start_date': '开始日期', 'due_date': '截止日期',
    }
    old_label_map = {
        'priority': Requirement.PRIORITY_LABELS.get(old_val, old_val or '-'),
        'source': Requirement.SOURCE_LABELS.get(old_val, old_val or '-'),
        'category': old_val or '未分类',
    }
    if field == 'priority':
        resp['label'] = req.priority_label
        resp['color'] = req.priority_color
        detail = f'优先级: {old_label_map["priority"]} → {req.priority_label}'
    elif field == 'source':
        resp['label'] = req.source_label
        detail = f'类型: {old_label_map["source"]} → {req.source_label}'
    elif field == 'category':
        resp['label'] = req.category_label
        detail = f'分类: {old_label_map["category"]} → {req.category_label or "未分类"}'
    else:
        fn = FIELD_NAMES.get(field, field)
        old_str = str(old_val) if old_val is not None else '-'
        new_str = str(value) if value is not None else '-'
        detail = f'{fn}: {old_str} → {new_str}'

    _log_activity(req, 'edited', detail)
    db.session.commit()
    return jsonify(**resp)


def _load_project_reqs(project_id):
    """Load all requirements for a project including sub-projects."""
    from app.models.project import Project
    all_reqs = Requirement.query.filter_by(project_id=project_id)\
        .options(joinedload(Requirement.children), joinedload(Requirement.assignee),
                 joinedload(Requirement.comments)).all()
    project = db.session.get(Project, project_id)
    if project and project.children:
        for cp in project.children:
            all_reqs.extend(Requirement.query.filter_by(project_id=cp.id)
                .options(joinedload(Requirement.children), joinedload(Requirement.assignee),
                         joinedload(Requirement.comments)).all())
    return all_reqs


def _build_req_data_text(all_reqs, today_):
    """Build text summary of requirements for AI prompt, including comments."""
    lines = []
    for r in all_reqs:
        pct = 100 if r.status == 'done' else (r.completion or 0)
        parent_info = f' (父需求ID={r.parent_id})' if r.parent_id else ''
        children_info = f' [子需求{len(r.children)}个]' if r.children else ''
        overdue = f' 超期{(today_ - r.due_date).days}天' if r.due_date and r.due_date < today_ and r.status not in ('done', 'closed') else ''
        dep_info = ''
        if r.dependencies:
            dep_info = ' 依赖:[' + ','.join(d.number for d in r.dependencies) + ']'
        if r.dependents:
            dep_info += ' 被依赖:[' + ','.join(d.number for d in r.dependents) + ']'
        line = (
            f'{r.number} | {r.title} | 状态:{r.status_label} | 完成率:{pct}% | '
            f'类型:{r.source_label} | 负责人:{r.assignee_display} | '
            f'预估:{r.estimate_days or "?"}天 | '
            f'启动:{r.start_date or "无"} | 截止:{r.due_date or "无"}'
            f'{parent_info}{children_info}{dep_info}{overdue}'
        )
        # Append recent comments (last 3)
        if hasattr(r, 'comments') and r.comments:
            recent = r.comments[:3]
            for c in recent:
                line += f'\n  评论[{c.user.name} {c.created_at.strftime("%m-%d")}]: {c.content[:80]}'
        lines.append(line)
    return '\n'.join(lines)


def _code_based_diagnose(all_reqs, today_):
    """Fallback: pure code-based requirement diagnosis."""
    import hashlib
    from collections import Counter, defaultdict

    active = [r for r in all_reqs if r.status not in ('done', 'closed')]
    issues = []

    def _id(tag, key):
        return hashlib.md5(f'{tag}:{key}'.encode()).hexdigest()[:8]

    for r in active:
        if r.due_date and r.due_date < today_:
            days = (today_ - r.due_date).days
            issues.append({'id': _id('overdue', r.id), 'level': 'danger', 'tag': '超期',
                'text': f'<strong>{r.number} {r.title}</strong> 超期 {days} 天，负责人：{r.assignee_display}'})
    for r in active:
        if not r.due_date:
            continue
        left = (r.due_date - today_).days
        pct = r.completion or 0
        if 0 < left <= 7 and pct < 60:
            issues.append({'id': _id('risk', r.id), 'level': 'danger', 'tag': '进度风险',
                'text': f'<strong>{r.number} {r.title}</strong> 剩余 {left} 天，完成率仅 {pct}%'})
    person_parents = defaultdict(set)
    for r in active:
        name = r.assignee_display
        if not name or name == '-':
            continue
        if r.parent_id:
            parent = next((p for p in all_reqs if p.id == r.parent_id), None)
            person_parents[name].add(parent.title if parent else f'ID={r.parent_id}')
        else:
            person_parents[name].add(r.title)
    for name, parents in person_parents.items():
        if len(parents) > 1:
            issues.append({'id': _id('spread', name), 'level': 'warning', 'tag': '人力分散',
                'text': f'<strong>{name}</strong> 同时参与 {len(parents)} 个父需求：{"、".join(list(parents)[:3])}'})
    person_days = defaultdict(float)
    for r in active:
        name = r.assignee_display
        if name and name != '-':
            person_days[name] += r.estimate_days or 1
    if len(person_days) >= 2:
        avg = sum(person_days.values()) / len(person_days)
        for name, days in person_days.items():
            if days > avg * 2:
                issues.append({'id': _id('load', name), 'level': 'warning', 'tag': '负荷过高',
                    'text': f'<strong>{name}</strong> 承担 {days:.0f} 人天（均值 {avg:.0f}），超出 {days/avg:.1f} 倍'})
    for r in active:
        if not r.parent_id and (r.estimate_days or 0) > 10 and not r.children:
            issues.append({'id': _id('large', r.id), 'level': 'warning', 'tag': '粒度过大',
                'text': f'<strong>{r.number} {r.title}</strong> 预估 {r.estimate_days} 天，建议拆分子需求'})
    for r in all_reqs:
        if r.parent_id and r.due_date:
            parent = next((p for p in all_reqs if p.id == r.parent_id), None)
            if parent and parent.due_date and r.due_date > parent.due_date:
                issues.append({'id': _id('dateconflict', r.id), 'level': 'warning', 'tag': '日期冲突',
                    'text': f'子需求 <strong>{r.number}</strong> 截止({r.due_date.strftime("%m-%d")})晚于父需求 {parent.number}({parent.due_date.strftime("%m-%d")})'})
    no_assignee = [r for r in active if not r.assignee_id and not r.assignee_name]
    if no_assignee:
        nums = '、'.join(r.number for r in no_assignee[:5])
        issues.append({'id': _id('noassign', 'all'), 'level': 'warning', 'tag': '无负责人',
            'text': f'{len(no_assignee)} 个需求未指定负责人：{nums}{"..." if len(no_assignee) > 5 else ""}'})
    no_dates = [r for r in active if not r.start_date or not r.due_date]
    if no_dates:
        nums = '、'.join(r.number for r in no_dates[:5])
        issues.append({'id': _id('nodate', 'all'), 'level': 'info', 'tag': '缺少日期',
            'text': f'{len(no_dates)} 个需求缺启动/截止日期：{nums}{"..." if len(no_dates) > 5 else ""}'})
    source_counts = Counter(r.source for r in active)
    coding_count = source_counts.get('coding', 0)
    testing_count = source_counts.get('testing', 0)
    if coding_count > 3 and testing_count < coding_count * 0.3:
        issues.append({'id': _id('testcov', 'all'), 'level': 'info', 'tag': '测试不足',
            'text': f'编码类 {coding_count} 个，测试类仅 {testing_count} 个（{testing_count/coding_count*100:.0f}%），建议补充'})
    for r in active:
        if r.start_date and (r.completion or 0) == 0 and (today_ - r.start_date).days > 14:
            issues.append({'id': _id('stale', r.id), 'level': 'info', 'tag': '长期停滞',
                'text': f'<strong>{r.number} {r.title}</strong> 已启动 {(today_ - r.start_date).days} 天但完成率 0%'})
    # Dependency issues: blocked by unfinished dependency
    for r in active:
        if r.dependencies:
            blocked = [d for d in r.dependencies if d.status not in ('done', 'closed')]
            if blocked:
                nums = '、'.join(d.number for d in blocked)
                issues.append({'id': _id('depblock', r.id), 'level': 'warning', 'tag': '依赖阻塞',
                    'text': f'<strong>{r.number} {r.title}</strong> 依赖未完成：{nums}'})
    # Dependency date conflict: dependency due_date later than dependent
    for r in all_reqs:
        if r.dependencies and r.start_date:
            late_deps = [d for d in r.dependencies if d.due_date and d.due_date > r.start_date]
            for d in late_deps:
                issues.append({'id': _id('depdate', f'{r.id}_{d.id}'), 'level': 'warning', 'tag': '依赖日期冲突',
                    'text': f'<strong>{r.number}</strong> 启动({r.start_date.strftime("%m-%d")})早于依赖 {d.number} 截止({d.due_date.strftime("%m-%d")})'})

    level_order = {'danger': 0, 'warning': 1, 'info': 2}
    issues.sort(key=lambda i: level_order.get(i['level'], 9))
    return issues


@requirement_bp.route('/diagnose')
@login_required
def diagnose_api():
    """Code diagnosis first, then enhance with AI. Fallback to code results if AI fails."""
    import hashlib
    import json

    from app.models.site_setting import SiteSetting

    project_id = request.args.get('project_id', type=int)
    if not project_id:
        return jsonify(ok=False, issues=[])

    all_reqs = _load_project_reqs(project_id)
    today_ = date.today()

    # Step 1: Code-based diagnosis (always works)
    issues = _code_based_diagnose(all_reqs, today_)
    ai_source = False

    # Step 2: Try AI enhancement
    try:
        from flask import current_app
        if current_app.config.get('AI_ENABLED', True):
            from app.services.ai import call_ollama
            from app.services.prompts import get_prompt
            prompt = get_prompt('req_diagnose')
            if prompt:
                data_text = _build_req_data_text(all_reqs, today_)
                code_summary = '\n'.join(f'[{i["tag"]}] {i["text"]}' for i in issues[:10])
                user_msg = f'今天日期：{today_}\n\n已知问题（代码预分析）：\n{code_summary}\n\n完整需求数据：\n{data_text}'
                ai_result, _ = call_ollama(user_msg, system_prompt=prompt)
                if ai_result and isinstance(ai_result, list) and ai_result:
                    for idx, issue in enumerate(ai_result):
                        issue['id'] = hashlib.md5(f'ai:{issue.get("tag","")}:{idx}'.encode()).hexdigest()[:8]
                    issues = ai_result
                    ai_source = True
    except Exception:
        pass  # Fallback to code issues

    # Load resolved state
    resolved_raw = SiteSetting.get(f'diag_resolved_{project_id}', '[]')
    try:
        resolved = set(json.loads(resolved_raw))
    except Exception:
        resolved = set()
    for i in issues:
        i['resolved'] = i.get('id', '') in resolved

    # Auto-save
    SiteSetting.set(f'diag_issues_{project_id}', json.dumps(issues, ensure_ascii=False))

    return jsonify(ok=True, issues=issues, total=len(issues),
                   resolved_count=sum(1 for i in issues if i['resolved']),
                   ai=ai_source)


@requirement_bp.route('/diagnose/resolve', methods=['POST'])
@login_required
def diagnose_resolve():
    """Mark a diagnostic issue as resolved or unresolved."""
    import json

    from app.models.site_setting import SiteSetting
    data = request.get_json() or {}
    project_id = data.get('project_id')
    issue_id = data.get('issue_id', '')
    resolve = data.get('resolve', True)
    if not project_id or not issue_id:
        return jsonify(ok=False)
    key = f'diag_resolved_{project_id}'
    try:
        resolved = set(json.loads(SiteSetting.get(key, '[]')))
    except Exception:
        resolved = set()
    if resolve:
        resolved.add(issue_id)
    else:
        resolved.discard(issue_id)
    SiteSetting.set(key, json.dumps(list(resolved)))
    return jsonify(ok=True)


@requirement_bp.route('/board')
@login_required
def requirement_board():
    """Kanban board view for requirements — must specify project_id."""
    project_id = request.args.get('project_id', type=int)
    _is_lead = current_user.is_admin or current_user.has_role('PL', 'PM', 'FO', 'LM', 'XM')
    if 'assignee_id' in request.args:
        assignee_id = request.args.get('assignee_id', type=int)
    else:
        assignee_id = None if _is_lead else current_user.id
    swimlane = request.args.get('swimlane', '')

    # 必须指定项目，不允许无项目筛选的全局看板
    if not project_id:
        abort(404)

    # 隐藏项目权限控制
    if project_id in g.hidden_pids:
        abort(403)

    show_sub = request.args.get('show_sub', '1') == '1'

    query = Requirement.query.filter_by(project_id=project_id).options(
        joinedload(Requirement.project), joinedload(Requirement.assignee),
        joinedload(Requirement.children),
    )
    if not show_sub:
        query = query.filter(Requirement.parent_id.is_(None))
    if assignee_id:
        query = query.filter_by(assignee_id=assignee_id)

    reqs = query.order_by(Requirement.updated_at.desc()).all()

    # Group by status for columns
    columns = [s for s in Requirement._STATUS_META.keys() if s != 'closed']
    board = {s: [] for s in columns}
    for r in reqs:
        if r.status in board:
            board[r.status].append(r)

    # Sort each column by completion ascending
    for col_reqs in board.values():
        col_reqs.sort(key=lambda r: r.completion or 0)

    # Assignee filter: project members
    from app.models.project_member import ProjectMember as PM_
    member_uids = [m.user_id for m in PM_.query.filter_by(project_id=project_id).all() if m.user_id]
    board_users = User.query.filter(User.id.in_(member_uids)).order_by(User.name).all() if member_uids else []

    return render_template('requirement/board.html',
        board=board, columns=columns, show_sub=show_sub,
        status_meta=Requirement._STATUS_META,
        users=board_users,
        cur_project=project_id, cur_assignee=assignee_id, swimlane=swimlane,
        today=date.today(),
    )


@requirement_bp.route('/<int:req_id>/quick-todo', methods=['POST'])
@login_required
def quick_todo_for_req(req_id):
    """Create a todo linked to this requirement."""
    req = db.get_or_404(Requirement, req_id)
    title = req.number + ' ' + req.title
    todo = Todo(
        user_id=current_user.id,
        title=title,
        due_date=date.today(),
        requirements=[req],
    )
    todo.items.append(TodoItem(title=title, sort_order=0))
    db.session.add(todo)
    db.session.commit()
    flash(f'已为 {req.number} 创建 Todo', 'success')
    return redirect(request.referrer or url_for('requirement.requirement_list'))


# --- Comments ---

@requirement_bp.route('/<int:req_id>/comments', methods=['POST'])
@login_required
def add_comment(req_id):
    req = db.get_or_404(Requirement, req_id)
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(requirement_id=req.id, user_id=current_user.id, content=form.content.data)
        db.session.add(comment)
        _log_activity(req, 'commented', form.content.data[:100])
        db.session.commit()
    return redirect(url_for('requirement.requirement_detail', req_id=req.id))


@requirement_bp.route('/<int:req_id>/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(req_id, comment_id):
    from app.models.audit import AuditLog
    comment = db.get_or_404(Comment, comment_id)
    if comment.requirement_id != req_id:
        flash('评论不属于该需求', 'danger')
        return redirect(url_for('requirement.requirement_detail', req_id=req_id))
    req = db.get_or_404(Requirement, req_id)
    # Audit log before deletion
    db.session.add(AuditLog(
        user_id=current_user.id, action='delete', entity_type='comment',
        entity_id=comment.id, entity_title=f'{req.number} 评论',
        detail=f'作者: {comment.user.name}, 内容: {comment.content[:200]}',
        ip_address=request.remote_addr,
    ))
    db.session.delete(comment)
    db.session.commit()
    flash('评论已删除', 'success')
    return redirect(url_for('requirement.requirement_detail', req_id=req_id))


# --- Dependencies ---

@requirement_bp.route('/search-api')
@login_required
def requirement_search_api():
    """Autocomplete API: search requirements by title/number within project scope."""
    q = request.args.get('q', '').strip()
    project_id = request.args.get('project_id', type=int)
    exclude_id = request.args.get('exclude_id', type=int)
    if not q or len(q) < 1:
        return jsonify(results=[])
    query = Requirement.query
    if project_id:
        # Include project and its sub-projects
        sub_ids = [p.id for p in Project.query.filter_by(parent_id=project_id).all()]
        query = query.filter(Requirement.project_id.in_([project_id] + sub_ids))
    query = query.filter(
        db.or_(
            Requirement.title.ilike(f'%{q}%'),
            Requirement.number.ilike(f'%{q}%'),
        )
    )
    if exclude_id:
        query = query.filter(Requirement.id != exclude_id)
    reqs = query.order_by(Requirement.number).limit(15).all()
    return jsonify(results=[
        {'id': r.id, 'number': r.number, 'title': r.title,
         'project': r.project.name if r.project else '', 'status': r.status_label}
        for r in reqs
    ])


@requirement_bp.route('/<int:req_id>/dependencies', methods=['POST'])
@login_required
def add_dependency(req_id):
    """Add a dependency: req_id depends on dep_id."""
    req = db.get_or_404(Requirement, req_id)
    dep_id = request.json.get('dep_id') if request.is_json else request.form.get('dep_id', type=int)
    if not dep_id:
        return jsonify(ok=False, msg='缺少依赖需求ID')
    dep = Requirement.query.get(dep_id)
    if not dep:
        return jsonify(ok=False, msg='依赖需求不存在')
    if dep.id == req.id:
        return jsonify(ok=False, msg='不能依赖自身')
    if dep in req.dependencies:
        return jsonify(ok=False, msg='已存在该依赖')
    # Prevent circular: dep should not depend on req (direct or indirect)
    visited = set()
    stack = [dep]
    while stack:
        node = stack.pop()
        if node.id == req.id:
            return jsonify(ok=False, msg='添加后会产生循环依赖')
        if node.id not in visited:
            visited.add(node.id)
            stack.extend(node.dependencies)
    req.dependencies.append(dep)
    _log_activity(req, 'edited', f'添加依赖 {dep.number}')
    db.session.commit()
    return jsonify(ok=True, dep={'id': dep.id, 'number': dep.number, 'title': dep.title, 'status': dep.status_label, 'color': dep.status_color})


@requirement_bp.route('/<int:req_id>/dependencies/<int:dep_id>', methods=['DELETE', 'POST'])
@login_required
def remove_dependency(req_id, dep_id):
    """Remove a dependency."""
    req = db.get_or_404(Requirement, req_id)
    dep = Requirement.query.get(dep_id)
    if dep and dep in req.dependencies:
        req.dependencies.remove(dep)
        _log_activity(req, 'edited', f'移除依赖 {dep.number}')
        db.session.commit()
    if request.is_json or request.method == 'DELETE':
        return jsonify(ok=True)
    return redirect(url_for('requirement.requirement_detail', req_id=req_id))


# ---- AI: Smart Assign ----

@requirement_bp.route('/<int:req_id>/ai-assign', methods=['POST'])
@login_required
def ai_smart_assign(req_id):
    """AI recommends best assignee for a requirement."""

    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    req = db.get_or_404(Requirement, req_id)
    users = User.query.filter_by(is_active=True).all()

    # Build context: each user's workload and recent experience
    lines = [f'需求信息：\n- 标题：{req.title}\n- 描述：{req.description or "无"}\n- 优先级：{req.priority}\n']

    lines.append('团队成员当前状况：')
    for u in users:
        active_count = Todo.query.filter_by(user_id=u.id, status='todo').count()
        # Recent completed req titles (last 30 days)
        recent_reqs = db.session.query(Requirement.title).join(
            todo_requirements, Requirement.id == todo_requirements.c.requirement_id
        ).join(Todo, Todo.id == todo_requirements.c.todo_id).filter(
            Todo.user_id == u.id, Todo.status == 'done'
        ).distinct().limit(5).all()
        exp = '、'.join(r[0][:15] for r in recent_reqs) if recent_reqs else '无近期记录'
        lines.append(f'- {u.name}（{u.group or ""}）：进行中 {active_count} 个任务，近期经验：{exp}')

    prompt = get_prompt('smart_assign') + '\n\n' + '\n'.join(lines)
    result, raw = call_ollama(prompt)

    if isinstance(result, dict) and result.get('recommended'):
        return jsonify(ok=True, **result)
    return jsonify(ok=False, raw=raw or 'AI服务暂不可用，正在紧急修复')


# ---- AI: Requirement Quality Check ----

@requirement_bp.route('/ai-quality-check', methods=['POST'])
@login_required
def ai_quality_check():
    """AI reviews requirement quality."""
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    data = request.get_json() or {}
    title = data.get('title', '')
    description = data.get('description', '')
    priority = data.get('priority', '')
    estimate = data.get('estimate_days', '')

    context = (
        f'需求标题：{title}\n'
        f'需求描述：{description or "未填写"}\n'
        f'优先级：{priority or "未设置"}\n'
        f'预估工期：{estimate or "未填写"} 人天'
    )
    prompt = get_prompt('req_quality_check') + '\n\n' + context
    result, raw = call_ollama(prompt)

    if isinstance(result, dict) and 'score' in result:
        return jsonify(ok=True, **result)
    return jsonify(ok=False, raw=raw or 'AI服务暂不可用，正在紧急修复')


def _build_requirement_form(obj=None):
    from app.project.routes import _mgr_view_open
    form = RequirementForm(obj=obj)
    projects = Project.query.filter_by(status='active')
    if not _mgr_view_open():
        projects = projects.filter_by(is_hidden=False)
    form.project_id.choices = [(p.id, p.name) for p in projects.all()]
    form.assignee_id.choices = [(0, '-- 未分配 --')] + [
        (u.id, u.name) for u in User.query.filter_by(is_active=True).all()
    ]
    return form


# ---- Batch Update ----

@requirement_bp.route('/batch_update', methods=['POST'])
@login_required
def batch_update():
    """Batch update requirements: category, assignee."""
    data = request.get_json() or {}
    ids = data.get('ids', [])
    action = data.get('action', '')
    value = data.get('value', '')
    if not ids or not action:
        return jsonify(ok=False, msg='参数缺失')

    reqs = Requirement.query.filter(Requirement.id.in_(ids)).all()
    if not reqs:
        return jsonify(ok=False, msg='未找到需求')

    count = 0
    for r in reqs:
        if action == 'category':
            r.category = value or None
            count += 1
        elif action == 'assignee':
            if value:
                r.assignee_id = int(value)
                r.assignee_name = None
            else:
                r.assignee_id = None
                r.assignee_name = None
            count += 1
        elif action == 'status':
            r.status = value
            count += 1
        elif action == 'priority':
            r.priority = value
            count += 1
    db.session.commit()
    return jsonify(ok=True, msg=f'已更新 {count} 条需求')


# ---- CSV Export / Import ----

@requirement_bp.route('/export-csv')
@login_required
def export_csv():
    """Export requirements as CSV (supports project filter)."""
    import csv
    import io

    from flask import Response

    project_id = request.args.get('project_id', type=int)
    query = Requirement.query.options(
        joinedload(Requirement.project), joinedload(Requirement.assignee),
        joinedload(Requirement.parent),
    )
    if project_id:
        query = query.filter_by(project_id=project_id)
    query = query.order_by(Requirement.project_id, Requirement.number)
    reqs = query.all()

    buf = io.StringIO()
    buf.write('\ufeff')  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow([
        'ID', '需求编号', '层级', '需求类型', '业务分类', '标题', '项目', '优先级', '状态',
        '负责人', '工号', '预估工期(天)', '代码行数', '用例数', 'AI辅助(%)', '完成率(%)',
        '开始日期', '截止日期', '父需求编号', '依赖需求', '描述', '评论',
    ])
    # Demo row (id=0)
    writer.writerow([
        0, 'REQ-000(选填)', '(自动)', '编码(选填)', '模型-软件(选填)', '示例需求标题', '项目名称', '高(选填)',
        '待评估(选填)', '张三(选填)', '(自动)', '5(选填)', '1000(选填)', '20(选填)',
        '30(选填)', '60(选填)',
        '2026-01-01(选填)', '2026-03-31(选填)', '(选填)', 'REQ-001,REQ-002(选填)',
        '描述(选填)', '(只读,导入时忽略) 此行为格式示例，导入时自动跳过',
    ])
    for r in reqs:
        assignee_eid = r.assignee.employee_id if r.assignee else ''
        level = '子需求' if r.parent_id else '需求'
        writer.writerow([
            r.id,
            r.number,
            level,
            r.source_label,
            r.category or '',
            r.title,
            r.project.name if r.project else '',
            r.priority_label,
            r.status_label,
            r.assignee_display,
            assignee_eid or '',
            r.estimate_days or '',
            r.code_lines or '',
            r.test_cases or '',
            r.ai_ratio if r.ai_ratio is not None else '',
            r.completion or '',
            r.start_date.isoformat() if r.start_date else '',
            r.due_date.isoformat() if r.due_date else '',
            r.parent.number if r.parent else '',
            ','.join(d.number for d in r.dependencies) if r.dependencies else '',
            r.description or '',
            '\n'.join(f'{c.user.name} {c.created_at.strftime("%m-%d")}：{c.content}' for c in r.comments) if r.comments else '',
        ])

    from urllib.parse import quote
    prefix = ''
    if project_id:
        p = db.session.get(Project, project_id)
        if p:
            prefix = p.name + '_'
    fname = f"{prefix}需求列表_{date.today().strftime('%Y%m%d')}.csv"
    return Response(
        buf.getvalue(), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@requirement_bp.route('/import-csv', methods=['POST'])
@login_required
def import_csv():
    """Import requirements from CSV. Supports parent-child via '父需求编号'."""
    import csv
    import io

    file = request.files.get('csv_file')
    if not file or not file.filename.lower().endswith('.csv'):
        flash('请选择 CSV 文件', 'danger')
        return redirect(url_for('requirement.requirement_list'))

    raw = file.read()
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        flash('编码无法识别', 'danger')
        return redirect(url_for('requirement.requirement_list'))

    reader = csv.DictReader(io.StringIO(text))
    if not {'标题'}.issubset(set(reader.fieldnames or [])):
        flash('CSV 缺少必填列：标题', 'danger')
        return redirect(url_for('requirement.requirement_list'))

    # Reverse lookup maps
    status_rev = {v: k for k, v in Requirement.STATUS_LABELS.items()}
    # Backward compat: old labels → new status
    status_rev.update({'待评估': 'pending', '分析中': 'pending', '开发中': 'in_progress', '测试中': 'in_progress', '待开发': 'pending'})
    priority_rev = {v: k for k, v in Requirement.PRIORITY_LABELS.items()}
    source_rev = {v: k for k, v in Requirement.SOURCE_LABELS.items()}
    user_map = {u.name: u.id for u in User.query.filter_by(is_active=True).all()}
    project_map = {p.name: p.id for p in Project.query.all()}

    # First pass: create requirements (skip parent linking)
    created = []
    skipped = 0
    number_to_req = {}
    for row in reader:
        if (row.get('ID') or '').strip() == '0':
            continue  # Skip demo row
        title = (row.get('标题') or '').strip()
        if not title:
            continue

        # Resolve project
        proj_name = (row.get('项目') or '').strip()
        pid = project_map.get(proj_name)
        if not pid:
            # Use form-submitted project_id, fallback to first active
            pid = request.form.get('project_id', type=int)
            if not pid:
                first_proj = Project.query.filter_by(status='active').first()
                pid = first_proj.id if first_proj else 1

        # Resolve assignee
        assignee_str = (row.get('负责人') or '').strip()
        assignee_id, assignee_name = None, None
        if assignee_str:
            uid = user_map.get(assignee_str)
            if uid:
                assignee_id = uid
            else:
                assignee_name = assignee_str

        # Check if requirement already exists (by number)
        number = (row.get('需求编号') or '').strip()
        existing = Requirement.query.filter_by(number=number).first() if number else None
        if existing:
            # Update existing
            existing.title = title
            existing.priority = priority_rev.get((row.get('优先级') or '').strip(), existing.priority)
            existing.status = status_rev.get((row.get('状态') or '').strip(), existing.status)
            src = source_rev.get((row.get('需求类型') or '').strip())
            if src:
                existing.source = src
            cat = (row.get('业务分类') or '').strip()
            if cat:
                existing.category = cat
            existing.assignee_id = assignee_id or existing.assignee_id
            existing.assignee_name = assignee_name or existing.assignee_name
            est = (row.get('预估工期(天)') or '').strip()
            if est:
                try:
                    existing.estimate_days = float(est)
                except ValueError:
                    pass
            sd = (row.get('开始日期') or '').strip()
            if sd:
                try:
                    existing.start_date = date.fromisoformat(sd)
                except ValueError:
                    pass
            dd = (row.get('截止日期') or '').strip()
            if dd:
                try:
                    existing.due_date = date.fromisoformat(dd)
                except ValueError:
                    pass
            cl = (row.get('代码行数') or '').strip()
            if cl:
                try:
                    existing.code_lines = int(cl)
                except ValueError:
                    pass
            tc = (row.get('用例数') or '').strip()
            if tc:
                try:
                    existing.test_cases = int(tc)
                except ValueError:
                    pass
            ai = (row.get('AI辅助(%)') or '').strip()
            if ai:
                try:
                    existing.ai_ratio = int(ai)
                except ValueError:
                    pass
            comp = (row.get('完成率(%)') or '').strip()
            if comp:
                try:
                    existing.completion = int(comp)
                except ValueError:
                    pass
            desc = (row.get('描述') or '').strip()
            if desc:
                existing.description = desc
            number_to_req[number] = existing
            skipped += 1
            continue

        req = Requirement(
            number=number or Requirement.generate_number(),
            project_id=pid,
            title=title,
            priority=priority_rev.get((row.get('优先级') or '').strip(), 'medium'),
            status=status_rev.get((row.get('状态') or '').strip(), 'pending'),
            source=source_rev.get((row.get('需求类型') or '').strip(), 'coding'),
            category=(row.get('业务分类') or '').strip() or None,
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            description=(row.get('描述') or '').strip() or None,
            created_by=current_user.id,
        )
        est = (row.get('预估工期(天)') or '').strip()
        if est:
            try:
                req.estimate_days = float(est)
            except ValueError:
                pass
        sd = (row.get('开始日期') or '').strip()
        if sd:
            try:
                req.start_date = date.fromisoformat(sd)
            except ValueError:
                pass
        dd = (row.get('截止日期') or '').strip()
        if dd:
            try:
                req.due_date = date.fromisoformat(dd)
            except ValueError:
                pass
        cl = (row.get('代码行数') or '').strip()
        if cl:
            try:
                req.code_lines = int(cl)
            except ValueError:
                pass
        tc = (row.get('用例数') or '').strip()
        if tc:
            try:
                req.test_cases = int(tc)
            except ValueError:
                pass
        ai = (row.get('AI辅助(%)') or '').strip()
        if ai:
            try:
                req.ai_ratio = int(ai)
            except ValueError:
                pass
        comp = (row.get('完成率(%)') or '').strip()
        if comp:
            try:
                req.completion = int(comp)
            except ValueError:
                pass
        db.session.add(req)
        created.append(req)
        number_to_req[req.number] = req

    db.session.flush()  # Get IDs for parent linking

    # Second pass: link parent requirements and dependencies
    reader2 = csv.DictReader(io.StringIO(text))
    for row in reader2:
        number = (row.get('需求编号') or '').strip()
        parent_number = (row.get('父需求编号') or '').strip()
        if number and parent_number:
            req = number_to_req.get(number)
            parent = number_to_req.get(parent_number) or \
                     Requirement.query.filter_by(number=parent_number).first()
            if req and parent:
                req.parent_id = parent.id
        # Dependencies
        dep_str = (row.get('依赖需求') or '').strip()
        if number and dep_str:
            req = number_to_req.get(number)
            if req:
                for dep_num in dep_str.split(','):
                    dep_num = dep_num.strip()
                    if not dep_num:
                        continue
                    dep = number_to_req.get(dep_num) or \
                          Requirement.query.filter_by(number=dep_num).first()
                    if dep and dep not in req.dependencies and dep.id != req.id:
                        req.dependencies.append(dep)

    db.session.commit()
    msg = f'导入成功，新建 {len(created)} 条需求'
    if skipped:
        msg += f'，跳过 {skipped} 条重复'
    flash(msg, 'success')
    return redirect(url_for('requirement.requirement_list'))
