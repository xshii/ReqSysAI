from datetime import date, datetime, timedelta, timezone

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.constants import REQ_INACTIVE_STATUSES, TODO_STATUS_DONE, TODO_STATUS_TODO
from app.extensions import db
from app.models.requirement import Requirement
from app.models.todo import Todo, TodoItem
from app.models.user import Group, User
from app.todo import todo_bp
from app.todo.forms import TodoForm

# ---- Todo CRUD ----

@todo_bp.route('/add', methods=['POST'])
@login_required
def add():
    form = TodoForm()
    if form.validate_on_submit():
        req_ids = request.form.getlist('req_ids', type=int)
        if not req_ids:
            flash('请至少选择一个关联需求', 'danger')
            return redirect(url_for('todo.team'))
        reqs = Requirement.query.filter(Requirement.id.in_(req_ids)).all()
        due_str = request.form.get('due_date', '')
        due = date.fromisoformat(due_str) if due_str else None
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
    data = request.get_json()
    if not data:
        return jsonify(ok=False), 400
    # Accept help request: due_date change without title means acceptance
    if 'due_date' in data and 'title' not in data:
        todo.due_date = date.fromisoformat(data['due_date']) if data['due_date'] else None
        if todo.source == 'help' and todo.parent_id:
            todo.source = 'help_accepted'
            from app.services.notify import notify
            parent = db.session.get(Todo, todo.parent_id)
            if parent:
                days = (todo.due_date - date.today()).days if todo.due_date else 0
                when = '今天' if days <= 0 else (f'{days}天内')
                notify(parent.user_id, 'help',
                       f'{current_user.name} 接纳了你的求助「{todo.title}」，预计{when}完成', '')
        db.session.commit()
        return jsonify(ok=True)

    title = (data.get('title') or '').strip()
    comment = (data.get('comment') or '').strip()
    if not title:
        # Reject help request: mark as rejected instead of deleting
        if comment and todo.parent_id and todo.source == 'help':
            todo.source = 'rejected'
            todo.blocked_reason = comment
            todo.status = 'done'
            todo.done_date = date.today()
            from app.services.notify import notify
            parent = db.session.get(Todo, todo.parent_id)
            if parent:
                notify(parent.user_id, 'help',
                       f'{current_user.name} 暂缓了你的求助「{todo.title}」：{comment}',
                       '')
            db.session.commit()
            return jsonify(ok=True, rejected=True)
        # Normal delete: recursively delete all descendants
        def _delete_descendants(parent_id):
            children = Todo.query.filter_by(parent_id=parent_id).all()
            for child in children:
                _delete_descendants(child.id)
                db.session.delete(child)
        _delete_descendants(todo.id)
        from app.services.audit import log_audit
        log_audit('delete', 'todo', todo.id, todo.title)
        db.session.delete(todo)
        db.session.commit()
        return jsonify(ok=True, deleted=True)
    todo.title = title
    if 'due_date' in data:
        todo.due_date = date.fromisoformat(data['due_date']) if data['due_date'] else None
    if 'category' in data:
        todo.category = data['category']
    db.session.commit()
    return jsonify(ok=True)


@todo_bp.route('/<int:todo_id>/confirm', methods=['POST'])
@login_required
def confirm(todo_id):
    """Mark todo as done."""
    todo = db.get_or_404(Todo, todo_id)
    todo.status = TODO_STATUS_DONE
    todo.done_date = date.today()
    # Record timer if running
    if todo.started_at:
        todo.actual_minutes = todo.elapsed_minutes
        todo.started_at = None
    for item in todo.items:
        item.is_done = True
    db.session.commit()
    # Fire domain event for auto-transitions
    from app.services.events import fire, todo_completed
    fire(todo_completed, todo=todo)
    return jsonify(ok=True)


@todo_bp.route('/<int:todo_id>/reopen', methods=['POST'])
@login_required
def reopen(todo_id):
    """Reopen a done todo."""
    todo = db.get_or_404(Todo, todo_id)
    todo.status = TODO_STATUS_TODO
    todo.done_date = None
    todo.started_at = None
    db.session.commit()
    return jsonify(ok=True)


# ---- Timer ----

@todo_bp.route('/<int:todo_id>/timer', methods=['POST'])
@login_required
def timer(todo_id):
    """Start or stop focus timer."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.started_at:
        # Stop timer — save this session
        from app.models.todo import PomodoroSession
        elapsed_sec = (datetime.now(timezone.utc).replace(tzinfo=None) - todo.started_at).total_seconds()
        elapsed_min = max(1, round(elapsed_sec / 60))  # At least 1 minute
        pomo_min = current_user.pomodoro_minutes or 45
        completed = elapsed_min >= pomo_min
        db.session.add(PomodoroSession(todo_id=todo.id, started_at=todo.started_at, minutes=elapsed_min, completed=completed))
        todo.actual_minutes = (todo.actual_minutes or 0) + elapsed_min
        todo.started_at = None
        db.session.commit()
        return jsonify(ok=True, running=False, minutes=elapsed_min,
                       completed=completed, total_minutes=todo.actual_minutes)
    else:
        todo.started_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(ok=True, running=True, minutes=0)


# ---- Help / Comments ----

@todo_bp.route('/<int:todo_id>/block', methods=['POST'])
@login_required
def toggle_block(todo_id):
    """Toggle blocked status with optional reason."""
    todo = db.get_or_404(Todo, todo_id)
    data = request.get_json() or {}
    if todo.need_help:
        # Unblock
        todo.need_help = False
        todo.blocked_reason = None
    else:
        # Block
        reason = (data.get('reason') or '').strip()[:200] or None
        todo.need_help = True
        todo.blocked_reason = reason
        # Parse @name → create help todo for that person
        if reason:
            import re
            at_match = re.search(r'@(\S+)', reason)
            if at_match:
                from app.models.user import User
                helper_name = at_match.group(1)
                helper = User.query.filter_by(name=helper_name, is_active=True).first()
                if helper and helper.id != current_user.id:
                    from app.models.todo import TodoItem
                    help_todo = Todo(
                        user_id=helper.id,
                        title=f'协助：{todo.title}',
                        category=todo.category,
                        source='help',
                        parent_id=todo.id,
                        due_date=date.today() + timedelta(days=7),
                        created_date=date.today(),
                    )
                    help_todo.items.append(TodoItem(title=f'协助：{todo.title}', sort_order=0))
                    db.session.add(help_todo)
    db.session.commit()
    return jsonify(ok=True, blocked=todo.need_help, reason=todo.blocked_reason)





# ---- Sub-items ----

@todo_bp.route('/<int:todo_id>/items/add', methods=['POST'])
@login_required
def add_item(todo_id):
    """Add a sub-item to a todo."""
    todo = db.get_or_404(Todo, todo_id)
    data = request.get_json()
    title = (data.get('title') or '').strip() if data else ''
    if not title:
        return jsonify(ok=False), 400
    item = TodoItem(todo_id=todo.id, title=title, sort_order=len(todo.items))
    db.session.add(item)
    # Reopen if todo was done (new sub-item means not finished yet)
    if todo.status == TODO_STATUS_DONE:
        todo.status = TODO_STATUS_TODO
        todo.done_date = None
    db.session.commit()
    return jsonify(ok=True, id=item.id, reopened=todo.status == TODO_STATUS_TODO)


@todo_bp.route('/items/<int:item_id>/toggle', methods=['POST'])
@login_required
def toggle_item(item_id):
    """Toggle a sub-item's done state."""
    item = db.get_or_404(TodoItem, item_id)
    item.is_done = not item.is_done
    # Auto-complete todo if all items done; reopen if unchecked
    todo = item.todo
    was_done = todo.status == TODO_STATUS_DONE
    if todo.items and all(i.is_done for i in todo.items):
        todo.status = TODO_STATUS_DONE
        todo.done_date = date.today()
    elif todo.status == TODO_STATUS_DONE:
        todo.status = TODO_STATUS_TODO
        todo.done_date = None
    db.session.commit()
    # Fire event if just completed
    if not was_done and todo.status == TODO_STATUS_DONE:
        from app.services.events import fire, todo_completed
        fire(todo_completed, todo=todo)
        # Sync parent todo (help request): helper done → requester's todo done
        if todo.parent_id:
            parent = db.session.get(Todo, todo.parent_id)
            if parent and parent.status != TODO_STATUS_DONE:
                parent.status = TODO_STATUS_DONE
                parent.done_date = date.today()
                for pi in parent.items:
                    pi.is_done = True
                db.session.commit()
    done, total = todo.items_progress
    return jsonify(ok=True, is_done=item.is_done, todo_done=todo.status == TODO_STATUS_DONE,
                   progress=f'{done}/{total}')


@todo_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete a sub-item."""
    item = db.get_or_404(TodoItem, item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify(ok=True)


# ---- Help request ----

@todo_bp.route('/<int:todo_id>/help', methods=['POST'])
@login_required
def ask_help(todo_id):
    """Create a linked todo for helper."""
    todo = db.get_or_404(Todo, todo_id)
    data = request.get_json() or {}
    helper_id = data.get('helper_id')
    help_title = (data.get('title') or '').strip() or f'协助: {todo.title}'
    helper = db.session.get(User, helper_id) if helper_id else None
    if not helper:
        return jsonify(ok=False, msg='请选择协助人'), 400
    help_due_str = data.get('due_date') or ''
    help_due = date.fromisoformat(help_due_str) if help_due_str else None
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
    if not todo:
        return jsonify(ok=False), 404
    new_status = data.get('status')
    if new_status and new_status in Todo.STATUS_LABELS:
        todo.status = new_status
        todo.done_date = date.today() if new_status == TODO_STATUS_DONE else None
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

    today = date.today()
    week_ago = today - timedelta(days=7)

    # 1. User's active requirements (assigned or unassigned)
    my_reqs = Requirement.query.filter(
        Requirement.status.notin_(REQ_INACTIVE_STATUSES),
        db.or_(Requirement.assignee_id == current_user.id, Requirement.assignee_id.is_(None)),
    ).all()

    # 2. Recent week's completed todos
    recent_done = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.status == TODO_STATUS_DONE, Todo.done_date >= week_ago)\
        .options(joinedload(Todo.items)).all()

    # 3. Current active todos (avoid duplicates)
    active_todos = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.status == TODO_STATUS_TODO).all()

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

    from app.services.prompts import get_prompt
    prompt = get_prompt('todo_recommend') + '\n\n' + '\n'.join(lines)

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

    today = date.today()
    keep_days = current_app.config.get('TODO_KEEP_DAYS', 7)
    week_ago = today - timedelta(days=keep_days)

    groups = [g.name for g in Group.query.order_by(Group.name).all()]

    cur_group = request.args.get('group', current_user.group or '')
    # Default to first group if none selected
    if not cur_group and groups:
        cur_group = groups[0]

    user_query = User.query.filter_by(is_active=True)
    if cur_group:
        user_query = user_query.filter_by(group=cur_group)
    users = user_query.order_by(User.group, User.name).all()

    user_ids = [u.id for u in users]

    # Recent 2 working days (today + yesterday, or Friday if Monday)
    yesterday = today - timedelta(days=1)
    if today.weekday() == 0:  # Monday → look back to Friday
        yesterday = today - timedelta(days=3)

    all_todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        Todo.category != 'personal',
        ~Todo.title.startswith('[情绪跟进]'),
        db.or_(
            Todo.status == TODO_STATUS_TODO,
            db.and_(Todo.status == TODO_STATUS_DONE, Todo.done_date >= week_ago),
            db.and_(Todo.created_date >= yesterday),
        )
    ).options(
        joinedload(Todo.requirements), joinedload(Todo.parent),
        joinedload(Todo.children), joinedload(Todo.items),
        joinedload(Todo.pomodoros),
    ).order_by(
        db.case((Todo.status == TODO_STATUS_TODO, 0), else_=1),
        Todo.sort_order,
        Todo.done_date.desc(),
    ).all() if user_ids else []

    # Group todos by user → by category (same structure as homepage)
    user_data = {}  # uid → {req_todos, risk_todos, team_todos, display_reqs, todo_total, todo_done}
    user_done = {}  # uid → [older done todos]
    for t in all_todos:
        work_date = t.done_date or t.created_date or today
        if t.status == TODO_STATUS_TODO or work_date >= yesterday:
            ud = user_data.setdefault(t.user_id, {
                'req_todos': {}, 'risk_todos': [], 'team_todos': [],
                'display_reqs': [], 'todos': [], '_req_map': {},
            })
            ud['todos'].append(t)
            if t.category == 'risk':
                ud['risk_todos'].append(t)
            elif t.category == 'team' or not t.requirements:
                ud['team_todos'].append(t)
            else:
                for r in t.requirements:
                    if r.status not in REQ_INACTIVE_STATUSES:
                        ud['req_todos'].setdefault(r.id, []).append(t)
                        if r.id not in ud['_req_map']:
                            ud['_req_map'][r.id] = r
                if not t.requirements or all(r.status in REQ_INACTIVE_STATUSES for r in t.requirements):
                    ud['team_todos'].append(t)
        elif t.status == TODO_STATUS_DONE:
            user_done.setdefault(t.user_id, []).append(t)

    # Build display_reqs for each user
    for _uid, ud in user_data.items():
        ud['display_reqs'] = sorted(ud['_req_map'].values(),
            key=lambda r: (r.due_date or date(2099,1,1), r.priority))
        ud['todo_total'] = len(ud['todos'])
        ud['todo_done'] = sum(1 for t in ud['todos'] if t.status == TODO_STATUS_DONE)
        del ud['_req_map'], ud['todos']

    for uid in user_done:
        user_done[uid].sort(key=lambda t: t.done_date or t.created_date, reverse=True)

    form = TodoForm()
    reqs = Requirement.query.filter(Requirement.status.notin_(REQ_INACTIVE_STATUSES))\
        .order_by(Requirement.number).all()
    # Default: inherit requirements from user's most recent todo
    last_todo = Todo.query.filter_by(user_id=current_user.id)\
        .filter(Todo.requirements.any())\
        .order_by(Todo.created_at.desc()).first()
    default_req_ids = [r.id for r in last_todo.requirements] if last_todo else []

    all_users_list = User.query.filter(User.is_active == True, User.id != current_user.id)\
        .order_by(User.name).all()

    # Due date options: weekday -> today/tomorrow; weekend -> today..monday
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    due_options = []
    dow = today.weekday()  # 0=Mon ... 6=Sun
    if dow < 5:  # weekday
        due_options.append((today, f'今天 ({today.strftime("%m-%d")} {weekday_names[dow]})'))
        tmr = today + timedelta(days=1)
        due_options.append((tmr, f'明天 ({tmr.strftime("%m-%d")} {weekday_names[tmr.weekday()]})'))
    else:  # weekend: show today through next Monday
        d = today
        while d.weekday() != 0 or d == today:  # until Monday (inclusive)
            label = '今天' if d == today else weekday_names[d.weekday()]
            due_options.append((d, f'{label} ({d.strftime("%m-%d")} {weekday_names[d.weekday()]})'))
            d += timedelta(days=1)
            if d.weekday() == 1:  # Tuesday, stop
                break

    # Help due date: next 3 workdays
    help_due_options = []
    d = today
    while len(help_due_options) < 3:
        if d.weekday() < 5:
            label = f'{d.strftime("%m-%d")} {weekday_names[d.weekday()]}'
            help_due_options.append((d, label))
        d += timedelta(days=1)

    # Todos marked as needing help (team-wide)
    help_todos = Todo.query.filter(
        Todo.need_help == True, Todo.status == TODO_STATUS_TODO,
        Todo.user_id.in_(user_ids),
    ).options(joinedload(Todo.requirements)).order_by(Todo.created_at.desc()).all()

    return render_template('todo/team.html',
        users=users, user_data=user_data, user_done=user_done, groups=groups,
        cur_group=cur_group, today=today, timedelta=timedelta, form=form,
        reqs=reqs, default_req_ids=default_req_ids, all_users=all_users_list,
        due_options=due_options, help_due_options=help_due_options,
        help_todos=help_todos,
    )
