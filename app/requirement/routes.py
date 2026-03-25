from collections import namedtuple
from datetime import date

from flask import flash, jsonify, redirect, render_template, request, url_for
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
    project_id = request.args.get('project_id', type=int)
    assignee_id = request.args.get('assignee_id', type=int)
    search = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')

    if status:
        query = query.filter_by(status=status)
    if priority:
        query = query.filter_by(priority=priority)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if assignee_id:
        query = query.filter_by(assignee_id=assignee_id)
    if search:
        query = query.filter(
            db.or_(Requirement.title.contains(search), Requirement.description.contains(search))
        )

    # Sort
    order = {
        'newest': Requirement.created_at.desc(),
        'oldest': Requirement.created_at.asc(),
        'priority': db.case({'high': 0, 'medium': 1, 'low': 2}, value=Requirement.priority),
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

    return render_template('requirement/list.html',
        pagination=pagination, requirements=pagination.items,
        projects=Project.query.all(),
        users=User.query.filter_by(is_active=True).all(),
        statuses=Requirement.STATUS_LABELS, priorities=Requirement.PRIORITY_LABELS,
        cur_status=status, cur_priority=priority, cur_project=project_id,
        cur_assignee=assignee_id, cur_search=search, cur_sort=sort,
        todo_counts=todo_counts,
    )


@requirement_bp.route('/new', methods=['GET', 'POST'])
@login_required
def requirement_create():
    form = _build_requirement_form()
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
            source=form.source.data or None,
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
                sub = Requirement(
                    number=Requirement.generate_number(),
                    title=st,
                    project_id=req.project_id,
                    priority=req.priority,
                    assignee_id=assignee,
                    assignee_name=assignee_name_ext,
                    estimate_days=days,
                    code_lines=est_lines if sub_type == 'coding' else None,
                    test_cases=est_cases if sub_type == 'testing' else None,
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
    return render_template('requirement/form.html', form=form, title='创建需求', users=users)


@requirement_bp.route('/<int:req_id>')
@login_required
def requirement_detail(req_id):
    req = db.get_or_404(Requirement, req_id)
    comment_form = CommentForm()
    return render_template('requirement/detail.html', req=req,
                           comment_form=comment_form)


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
        req.source = form.source.data or req.source
        _log_activity(req, 'edited', '编辑了需求')
        db.session.commit()
        flash('需求更新成功', 'success')
        return redirect(url_for('requirement.requirement_detail', req_id=req.id))
    if request.method == 'POST':
        flash('请检查必填项（标题、截止日期）', 'danger')
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('requirement/form.html', form=form, title=f'编辑需求 - {req.number}', users=users, req=req)


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
    if new_status not in req.allowed_next_statuses:
        return jsonify(ok=False, msg=f'不允许从「{req.status_label}」流转到该状态')
    old_status = req.status
    old_label = req.status_label
    req.status = new_status
    _log_activity(req, 'status_changed', f'{old_label} → {req.status_label}')
    db.session.commit()
    from app.services.events import fire, requirement_status_changed
    fire(requirement_status_changed, requirement=req, old_status=old_status, new_status=new_status)
    return jsonify(ok=True, status=new_status, label=req.status_label)


@requirement_bp.route('/board')
@login_required
def requirement_board():
    """Kanban board view for requirements."""
    project_id = request.args.get('project_id', type=int)
    assignee_id = request.args.get('assignee_id', type=int)
    swimlane = request.args.get('swimlane', '')  # '' or 'assignee'

    query = Requirement.query.filter(Requirement.parent_id.is_(None)).options(
        joinedload(Requirement.project), joinedload(Requirement.assignee),
        joinedload(Requirement.children),
    )
    if project_id:
        query = query.filter_by(project_id=project_id)
    if assignee_id:
        query = query.filter_by(assignee_id=assignee_id)

    reqs = query.order_by(Requirement.priority, Requirement.updated_at.desc()).all()

    # Group by status for columns
    columns = list(Requirement._STATUS_META.keys())
    board = {s: [] for s in columns}
    for r in reqs:
        if r.status in board:
            board[r.status].append(r)

    return render_template('requirement/board.html',
        board=board, columns=columns,
        status_meta=Requirement._STATUS_META,
        projects=Project.query.filter_by(status='active').all(),
        users=User.query.filter_by(is_active=True).order_by(User.name).all(),
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
    return jsonify(ok=False, raw=raw or '生成失败')


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
    return jsonify(ok=False, raw=raw or '生成失败')


def _build_requirement_form(obj=None):
    form = RequirementForm(obj=obj)
    form.project_id.choices = [(p.id, p.name) for p in Project.query.filter_by(status='active').all()]
    form.assignee_id.choices = [(0, '-- 未分配 --')] + [
        (u.id, u.name) for u in User.query.filter_by(is_active=True).all()
    ]
    return form


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
        'ID', '需求编号', '层级', '需求类型', '标题', '项目', '优先级', '状态',
        '负责人', '工号', '预估工期(天)', '代码行数', '用例数',
        '开始日期', '截止日期', '父需求编号', '描述',
    ])
    # Demo row (id=0)
    writer.writerow([
        0, 'REQ-000(选填)', '(自动)', '编码(选填)', '示例需求标题', '项目名称', '高(选填)',
        '待评估(选填)', '张三(选填)', '(自动)', '5(选填)', '1000(选填)', '20(选填)',
        '2026-01-01(选填)', '2026-03-31(选填)', '(选填)', '描述(选填) 此行为格式示例，导入时自动跳过',
    ])
    for r in reqs:
        assignee_eid = r.assignee.employee_id if r.assignee else ''
        level = '子需求' if r.parent_id else '需求'
        writer.writerow([
            r.id,
            r.number,
            level,
            r.source_label,
            r.title,
            r.project.name if r.project else '',
            r.priority_label,
            r.status_label,
            r.assignee_display,
            assignee_eid or '',
            r.estimate_days or '',
            r.code_lines or '',
            r.test_cases or '',
            r.start_date.isoformat() if r.start_date else '',
            r.due_date.isoformat() if r.due_date else '',
            r.parent.number if r.parent else '',
            r.description or '',
        ])

    return Response(
        buf.getvalue(), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=requirements.csv'},
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
            status=status_rev.get((row.get('状态') or '').strip(), 'pending_review'),
            source=source_rev.get((row.get('需求类型') or '').strip()),
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
        db.session.add(req)
        created.append(req)
        number_to_req[req.number] = req

    db.session.flush()  # Get IDs for parent linking

    # Second pass: link parent requirements
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

    db.session.commit()
    msg = f'导入成功，新建 {len(created)} 条需求'
    if skipped:
        msg += f'，跳过 {skipped} 条重复'
    flash(msg, 'success')
    return redirect(url_for('requirement.requirement_list'))
