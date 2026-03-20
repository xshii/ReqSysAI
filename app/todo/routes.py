from datetime import date, timedelta

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.todo import todo_bp
from app.todo.forms import TodoForm
from app.extensions import db
from app.models.todo import Todo, TodoItem
from app.models.user import User

DONE_KEEP_DAYS = 7


# ---- Group management ----

@todo_bp.route('/groups', methods=['GET', 'POST'])
@login_required
def manage_groups():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            name = request.form.get('group_name', '').strip()
            if not name:
                flash('请输入团队名称', 'danger')
            elif User.query.filter_by(group=name).first():
                flash(f'团队 {name} 已存在', 'warning')
            else:
                current_user.group = name
                db.session.commit()
                flash(f'已创建并加入团队 {name}', 'success')
        elif action == 'join':
            name = request.form.get('group_name', '').strip()
            if name:
                current_user.group = name
                db.session.commit()
                flash(f'已加入团队 {name}', 'success')
        elif action == 'leave':
            current_user.group = None
            db.session.commit()
            flash('已退出团队', 'success')
        return redirect(url_for('todo.manage_groups'))

    groups = db.session.query(
        User.group, db.func.count(User.id)
    ).filter(User.group.isnot(None), User.group != '', User.is_active == True)\
     .group_by(User.group).order_by(User.group).all()
    return render_template('todo/groups.html', groups=groups)


# ---- Todo CRUD ----

@todo_bp.route('/add', methods=['POST'])
@login_required
def add():
    from app.models.requirement import Requirement
    form = TodoForm()
    if form.validate_on_submit():
        req_ids = request.form.getlist('req_ids', type=int)
        if not req_ids:
            flash('请至少选择一个关联需求', 'danger')
            return redirect(url_for('todo.team'))
        reqs = Requirement.query.filter(Requirement.id.in_(req_ids)).all()
        due = request.form.get('due_date')
        assignee_id = request.form.get('assignee_id', type=int) or current_user.id
        # Validate assignee exists and is active
        assignee = db.session.get(User, assignee_id)
        if not assignee or not assignee.is_active:
            assignee_id = current_user.id
        todo = Todo(
            user_id=assignee_id,
            title=form.title.data,
            requirements=reqs,
            due_date=due or date.today(),
        )
        # Parse sub-items from form
        item_titles = request.form.getlist('item_title')
        for i, t in enumerate(item_titles):
            t = t.strip()
            if t:
                todo.items.append(TodoItem(title=t, sort_order=i))
        db.session.add(todo)
        db.session.commit()
    return redirect(url_for('todo.team'))


@todo_bp.route('/<int:todo_id>/edit', methods=['POST'])
@login_required
def edit(todo_id):
    """Edit todo: JSON API for title update or delete (empty title)."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    data = request.get_json()
    if not data:
        return jsonify(ok=False), 400
    title = (data.get('title') or '').strip()
    if not title:
        db.session.delete(todo)
        db.session.commit()
        return jsonify(ok=True, deleted=True)
    todo.title = title
    if 'due_date' in data:
        todo.due_date = data['due_date'] or None
    db.session.commit()
    return jsonify(ok=True)


@todo_bp.route('/<int:todo_id>/confirm', methods=['POST'])
@login_required
def confirm(todo_id):
    """Mark todo as done."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    todo.status = 'done'
    todo.done_date = date.today()
    # Also check all items
    for item in todo.items:
        item.is_done = True
    db.session.commit()
    return jsonify(ok=True)


@todo_bp.route('/<int:todo_id>/reopen', methods=['POST'])
@login_required
def reopen(todo_id):
    """Reopen a done todo."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    todo.status = 'todo'
    todo.done_date = None
    db.session.commit()
    return jsonify(ok=True)


# ---- Sub-items ----

@todo_bp.route('/<int:todo_id>/items/add', methods=['POST'])
@login_required
def add_item(todo_id):
    """Add a sub-item to a todo."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    data = request.get_json()
    title = (data.get('title') or '').strip() if data else ''
    if not title:
        return jsonify(ok=False), 400
    item = TodoItem(todo_id=todo.id, title=title, sort_order=len(todo.items))
    db.session.add(item)
    db.session.commit()
    return jsonify(ok=True, id=item.id)


@todo_bp.route('/items/<int:item_id>/toggle', methods=['POST'])
@login_required
def toggle_item(item_id):
    """Toggle a sub-item's done state."""
    item = db.get_or_404(TodoItem, item_id)
    if item.todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    item.is_done = not item.is_done
    # Auto-complete todo if all items done
    todo = item.todo
    if todo.items and all(i.is_done for i in todo.items):
        todo.status = 'done'
        todo.done_date = date.today()
    elif todo.status == 'done':
        todo.status = 'todo'
        todo.done_date = None
    db.session.commit()
    done, total = todo.items_progress
    return jsonify(ok=True, is_done=item.is_done, todo_done=todo.status == 'done',
                   progress=f'{done}/{total}')


@todo_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete a sub-item."""
    item = db.get_or_404(TodoItem, item_id)
    if item.todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    db.session.delete(item)
    db.session.commit()
    return jsonify(ok=True)


# ---- Help request ----

@todo_bp.route('/<int:todo_id>/help', methods=['POST'])
@login_required
def ask_help(todo_id):
    """Create a linked todo for helper."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.user_id != current_user.id:
        return jsonify(ok=False, msg='只能对自己的任务求助'), 403
    data = request.get_json() or {}
    helper_id = data.get('helper_id')
    help_title = (data.get('title') or '').strip() or f'协助: {todo.title}'
    helper = db.session.get(User, helper_id) if helper_id else None
    if not helper:
        return jsonify(ok=False, msg='请选择协助人'), 400
    help_due = data.get('due_date') or None
    child = Todo(
        user_id=helper.id,
        title=help_title,
        parent_id=todo.id,
        requirements=list(todo.requirements),
        due_date=help_due,
    )
    # Copy items if provided
    item_titles = data.get('items', [])
    for i, t in enumerate(item_titles):
        if t.strip():
            child.items.append(TodoItem(title=t.strip(), sort_order=i))
    db.session.add(child)
    db.session.commit()
    return jsonify(ok=True, helper_name=helper.name)


# ---- Drag sort ----

@todo_bp.route('/drag', methods=['POST'])
@login_required
def drag():
    data = request.get_json()
    if not data:
        return jsonify(ok=False), 400
    todo = db.session.get(Todo, data.get('id'))
    if not todo or todo.user_id != current_user.id:
        return jsonify(ok=False), 403
    new_status = data.get('status')
    if new_status and new_status in Todo.STATUS_LABELS:
        todo.status = new_status
        todo.done_date = date.today() if new_status == 'done' else None
    order = data.get('order')
    if isinstance(order, list):
        my_todos = {t.id: t for t in Todo.query.filter(
            Todo.id.in_(order), Todo.user_id == current_user.id
        ).all()}
        for i, tid in enumerate(order):
            if tid in my_todos:
                my_todos[tid].sort_order = i
    db.session.commit()
    return jsonify(ok=True)


# ---- AI Recommend ----

@todo_bp.route('/ai-recommend', methods=['POST'])
@login_required
def ai_recommend():
    from app.services.ai import call_ollama
    from app.models.requirement import Requirement

    today = date.today()
    week_ago = today - timedelta(days=7)

    # 1. User's active requirements (assigned or unassigned)
    my_reqs = Requirement.query.filter(
        Requirement.status.notin_(['done', 'closed']),
        db.or_(Requirement.assignee_id == current_user.id, Requirement.assignee_id.is_(None)),
    ).all()

    # 2. Recent week's completed todos
    recent_done = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.status == 'done', Todo.done_date >= week_ago)\
        .options(joinedload(Todo.items)).all()

    # 3. Current active todos (avoid duplicates)
    active_todos = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.status == 'todo').all()

    # Build context
    lines = [f'今天是 {today.strftime("%Y-%m-%d")}，请为我规划今日任务。\n']

    if my_reqs:
        lines.append('我负责的未完成需求（含截止日期）：')
        for r in my_reqs:
            ddl = f'，截止 {r.updated_at.strftime("%m-%d")}' if r.estimate_days else ''
            lines.append(f'- [{r.number}] {r.title}（优先级: {r.priority_label}，状态: {r.status_label}{ddl}）')

    if recent_done:
        lines.append('\n最近一周已完成的任务：')
        for t in recent_done:
            items_str = ''
            if t.items:
                items_str = '（子项: ' + ', '.join(i.title for i in t.items) + '）'
            lines.append(f'- {t.done_date.strftime("%m-%d")} {t.title}{items_str}')

    if active_todos:
        lines.append('\n当前未完成的任务（不要重复推荐）：')
        for t in active_todos:
            lines.append(f'- {t.title}')

    if not my_reqs:
        flash('没有未完成的需求，无法推荐', 'info')
        return redirect(url_for('todo.team'))

    prompt = (
        '根据以下信息，推荐今天应该新增的任务。\n'
        '要求：\n'
        '1. 根据需求优先级和截止日期排序，紧急的优先\n'
        '2. 参考近一周完成情况，推进未完成的需求\n'
        '3. 不要重复已有任务\n'
        '4. 每个任务拆分为可执行的子项\n'
        '5. 返回 JSON 数组，格式如下，只返回 JSON：\n'
        '[{"title":"任务标题","req_number":"REQ-001","items":["子项1","子项2"]}]\n\n'
        + '\n'.join(lines)
    )

    result, _ = call_ollama(prompt)
    if not result:
        flash('AI 推荐失败，请重试', 'danger')
        return redirect(url_for('todo.team'))
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        flash('AI 返回格式异常', 'danger')
        return redirect(url_for('todo.team'))

    # Build a map of requirement numbers to objects
    req_map = {r.number: r for r in my_reqs}

    count = 0
    for item in result:
        if not isinstance(item, dict) or not item.get('title'):
            continue
        todo = Todo(
            user_id=current_user.id,
            title=item['title'],
            due_date=today,
            sort_order=count,
        )
        # Link requirement by number
        req_num = item.get('req_number', '')
        if req_num in req_map:
            todo.requirements.append(req_map[req_num])
        # Add sub-items
        for i, sub in enumerate(item.get('items', [])):
            if isinstance(sub, str) and sub.strip():
                todo.items.append(TodoItem(title=sub.strip(), sort_order=i))
        db.session.add(todo)
        count += 1
    db.session.commit()
    flash(f'AI 推荐了 {count} 个任务', 'success')
    return redirect(url_for('todo.team'))


# ---- Team view (main entry) ----

@todo_bp.route('/')
@todo_bp.route('/team')
@login_required
def team():
    from app.models.requirement import Requirement

    today = date.today()
    week_ago = today - timedelta(days=DONE_KEEP_DAYS)
    cur_group = request.args.get('group', current_user.group or '')

    groups = db.session.query(User.group).filter(User.group.isnot(None), User.group != '')\
        .distinct().order_by(User.group).all()
    groups = [g[0] for g in groups]

    user_query = User.query.filter_by(is_active=True)
    if cur_group:
        user_query = user_query.filter_by(group=cur_group)
    users = user_query.order_by(User.group, User.name).all()

    user_ids = [u.id for u in users]
    all_todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        db.or_(
            Todo.status == 'todo',
            db.and_(Todo.status == 'done', Todo.done_date >= week_ago),
        )
    ).options(
        joinedload(Todo.requirements), joinedload(Todo.parent),
        joinedload(Todo.children), joinedload(Todo.items),
    ).order_by(Todo.sort_order).all() if user_ids else []

    user_todos = {}
    for t in all_todos:
        user_todos.setdefault(t.user_id, []).append(t)

    form = TodoForm()
    reqs = Requirement.query.filter(Requirement.status.notin_(['done', 'closed']))\
        .order_by(Requirement.number).all()
    # Default: inherit requirements from user's most recent todo
    last_todo = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.requirements.any())\
        .order_by(Todo.created_at.desc()).first()
    default_req_ids = [r.id for r in last_todo.requirements] if last_todo else []

    all_users_list = User.query.filter(User.is_active == True, User.id != current_user.id)\
        .order_by(User.name).all()

    return render_template('todo/team.html',
        users=users, user_todos=user_todos, groups=groups,
        cur_group=cur_group, today=today, form=form,
        reqs=reqs, default_req_ids=default_req_ids, all_users=all_users_list,
        tomorrow=today + timedelta(days=1),
    )
