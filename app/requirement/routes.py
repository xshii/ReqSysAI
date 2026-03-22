from collections import namedtuple
from datetime import date

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

TodoProgress = namedtuple('TodoProgress', 'total done')

from app.requirement import requirement_bp
from app.requirement.forms import RequirementForm, CommentForm

from app.extensions import db
from app.models.project import Project
from app.models.requirement import Requirement, Comment, Activity
from app.models.todo import Todo, TodoItem, todo_requirements
from app.models.user import User

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
            source='manual',
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
                try:
                    assignee = int(sub_assignees[i]) if i < len(sub_assignees) and sub_assignees[i] else None
                except (ValueError, IndexError):
                    assignee = None
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
        _log_activity(req, 'edited', '编辑了需求')
        db.session.commit()
        flash('需求更新成功', 'success')
        return redirect(url_for('requirement.requirement_detail', req_id=req.id))
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('requirement/form.html', form=form, title=f'编辑需求 - {req.number}', users=users)


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
    return redirect(url_for('requirement.requirement_detail', req_id=req.id))


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
    from collections import Counter

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
