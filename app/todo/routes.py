from datetime import date, datetime, timedelta

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.constants import REQ_INACTIVE_STATUSES, TODO_STATUS_DONE, TODO_STATUS_TODO
from app.extensions import db
from app.models.requirement import Requirement
from app.models.todo import Todo, TodoItem
from app.models.user import Group, User
from app.todo import todo_bp
from app.todo.forms import TodoForm
from app.utils.api import api_err, api_ok


def _sync_ext_request(todo, status):
    """同步外部诉求的 ExternalRequest 状态。通过 blocked_reason 里的 ext_req:ID 精确匹配。"""
    from app.models.external_request import ExternalRequest
    if not todo.blocked_reason or not todo.blocked_reason.startswith('ext_req:'):
        return
    try:
        er_id = int(todo.blocked_reason.split(':')[1])
    except (IndexError, ValueError):
        return
    er = db.session.get(ExternalRequest, er_id)
    if er:
        er.status = status
        if not er.assigned_id:
            from flask_login import current_user
            er.assigned_id = current_user.id

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
        return api_err(status=400)
    # Accept help request: due_date change without title means acceptance
    if 'due_date' in data and 'title' not in data:
        todo.due_date = date.fromisoformat(data['due_date']) if data['due_date'] else None
        if todo.source == 'help':
            todo.source = 'help_accepted'
            if todo.parent_id:
                from app.services.notify import notify
                parent = db.session.get(Todo, todo.parent_id)
                if parent:
                    days = (todo.due_date - date.today()).days if todo.due_date else 0
                    when = '今天' if days <= 0 else (f'{days}天内')
                    # 同步求助方 due_date：被求助方承诺的日期更晚时，拉齐求助方的截止日
                    if todo.due_date and (not parent.due_date or todo.due_date > parent.due_date):
                        parent.due_date = todo.due_date
                    notify(parent.user_id, 'help',
                           f'{current_user.name} 接纳了你的求助「{todo.title}」，预计{when}完成', '')
            # 同步外部诉求状态 + 标记通知已读
            if todo.title.startswith('[外部诉求]'):
                _sync_ext_request(todo, 'accepted')
                from app.models.notification import Notification
                Notification.query.filter_by(user_id=current_user.id, type='request', is_read=False).update({'is_read': True})
        db.session.commit()
        return api_ok()

    title = (data.get('title') or '').strip()
    comment = (data.get('comment') or '').strip()
    if not title:
        # Reject help request: mark as rejected instead of deleting
        if comment and todo.source == 'help':
            # 同步外部诉求状态（必须在覆盖 blocked_reason 之前）
            if todo.title.startswith('[外部诉求]'):
                _sync_ext_request(todo, 'rejected')
                from app.models.notification import Notification
                Notification.query.filter_by(user_id=current_user.id, type='request', is_read=False).update({'is_read': True})
            todo.source = 'rejected'
            todo.blocked_reason = comment
            todo.status = 'done'
            todo.done_date = date.today()
            if todo.parent_id:
                from app.services.notify import notify
                parent = db.session.get(Todo, todo.parent_id)
                if parent:
                    notify(parent.user_id, 'help',
                           f'{current_user.name} 暂缓了你的求助「{todo.title}」：{comment}',
                           '')
            db.session.commit()
            return api_ok(rejected=True)
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
        return api_ok(deleted=True)
    todo.title = title
    if 'due_date' in data:
        todo.due_date = date.fromisoformat(data['due_date']) if data['due_date'] else None
    if 'category' in data:
        todo.category = data['category']
    db.session.commit()
    return api_ok()


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
    return api_ok()


@todo_bp.route('/<int:todo_id>/reopen', methods=['POST'])
@login_required
def reopen(todo_id):
    """Reopen a done todo."""
    todo = db.get_or_404(Todo, todo_id)
    todo.status = TODO_STATUS_TODO
    todo.done_date = None
    todo.started_at = None
    db.session.commit()
    return api_ok()


# ---- Timer ----

@todo_bp.route('/<int:todo_id>/timer', methods=['POST'])
@login_required
def timer(todo_id):
    """Start or stop focus timer."""
    todo = db.get_or_404(Todo, todo_id)
    if todo.started_at:
        # Stop timer — save this session
        from app.models.todo import PomodoroSession
        elapsed_sec = (datetime.now() - todo.started_at).total_seconds()
        elapsed_min = max(1, round(elapsed_sec / 60))  # At least 1 minute
        pomo_min = current_user.pomodoro_minutes or 45
        completed = elapsed_min >= pomo_min
        db.session.add(PomodoroSession(todo_id=todo.id, started_at=todo.started_at, minutes=elapsed_min, completed=completed))
        todo.actual_minutes = (todo.actual_minutes or 0) + elapsed_min
        todo.started_at = None
        db.session.commit()
        return api_ok(running=False, minutes=elapsed_min,
                      completed=completed, total_minutes=todo.actual_minutes)
    else:
        todo.started_at = datetime.now()
        db.session.commit()
        return api_ok(running=True, minutes=0)


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
    return api_ok(blocked=todo.need_help, reason=todo.blocked_reason)





# ---- Sub-items ----

@todo_bp.route('/<int:todo_id>/items/add', methods=['POST'])
@login_required
def add_item(todo_id):
    """Add a sub-item to a todo."""
    todo = db.get_or_404(Todo, todo_id)
    data = request.get_json()
    title = (data.get('title') or '').strip() if data else ''
    if not title:
        return api_err(status=400)
    item = TodoItem(todo_id=todo.id, title=title, sort_order=len(todo.items))
    db.session.add(item)
    # Reopen if todo was done (new sub-item means not finished yet)
    if todo.status == TODO_STATUS_DONE:
        todo.status = TODO_STATUS_TODO
        todo.done_date = None
    db.session.commit()
    return api_ok(id=item.id, reopened=todo.status == TODO_STATUS_TODO)


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
    return api_ok(is_done=item.is_done, todo_done=todo.status == TODO_STATUS_DONE,
                  progress=f'{done}/{total}')


@todo_bp.route('/items/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    """Delete a sub-item."""
    item = db.get_or_404(TodoItem, item_id)
    db.session.delete(item)
    db.session.commit()
    return api_ok()


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
        return api_err(msg='请选择协助人', status=400)
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
    return api_ok(helper_name=helper.name)


# ---- Drag sort ----

@todo_bp.route('/drag', methods=['POST'])
@login_required
def drag():
    data = request.get_json()
    if not data:
        return api_err(status=400)
    todo = db.session.get(Todo, data.get('id'))
    if not todo:
        return api_err(status=404)
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
    return api_ok()


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
        flash('AI服务暂不可用，正在紧急修复', 'danger')
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

    # Hidden project filtering (privacy mode)
    _hidden_pids = set(g.hidden_pids)

    view_mode = current_user.team_view_mode or 'group'
    groups = [g.name for g in Group.query.order_by(Group.name).all()]
    cur_group = ''
    cur_project_id = None
    cur_project_obj = None

    project_pids = []  # project + sub-project ids for filtering

    if view_mode == 'project':
        from app.models.project import Project
        from app.models.project_member import ProjectMember
        cur_project_id = request.args.get('project_id', type=int)
        # Default: first followed project > first membership
        if not cur_project_id:
            followed = current_user.followed_projects.filter(Project.status == 'active').first()
            if followed:
                cur_project_id = followed.id
            else:
                first_membership = ProjectMember.query.filter_by(user_id=current_user.id)\
                    .join(Project).filter(Project.status == 'active').first()
                if first_membership:
                    cur_project_id = first_membership.project_id
        if cur_project_id:
            cur_project_obj = Project.query.get(cur_project_id)
            # 权限校验：仅项目成员、关注者、管理视图开启的管理层可查看
            mgr_view_on = current_user.is_team_manager and request.cookies.get('mgr_view') == '1'
            if cur_project_obj and not mgr_view_on:
                is_member = ProjectMember.query.filter_by(
                    project_id=cur_project_id, user_id=current_user.id).first()
                is_follower = cur_project_id in {
                    p.id for p in current_user.followed_projects.all()}
                if not is_member and not is_follower:
                    abort(403)
            # Include sub-projects (exclude hidden)
            sub_pids = [c.id for c in Project.query.filter_by(parent_id=cur_project_id).all()
                        if c.id not in _hidden_pids]
            project_pids = [cur_project_id] + sub_pids
            # Members from project + sub-projects, record per-user project for sorting
            _members = ProjectMember.query.filter(
                ProjectMember.project_id.in_(project_pids)).all()
            member_uids = list({m.user_id for m in _members if m.user_id})
            # user → project mapping; sort projects by member count asc (人少的项目在前)
            _pid_member_count = {}
            for m in _members:
                if m.user_id:
                    _pid_member_count[m.project_id] = _pid_member_count.get(m.project_id, 0) + 1
            _sorted_pids = sorted(project_pids, key=lambda pid: _pid_member_count.get(pid, 0))
            _pid_order = {pid: i for i, pid in enumerate(_sorted_pids)}
            _user_pid = {}  # user_id → project index for sorting
            for m in _members:
                if m.user_id:
                    cur = _pid_order.get(m.project_id, 999)
                    if m.user_id not in _user_pid or cur < _user_pid[m.user_id]:
                        _user_pid[m.user_id] = cur
            users = User.query.filter(User.id.in_(member_uids), User.is_active == True).all()  # noqa: E712
        else:
            users = []
    else:
        cur_group = request.args.get('group', current_user.group or '')
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
                _has_visible_req = False
                _30_days_ago = today - timedelta(days=30)
                for r in t.requirements:
                    _is_active = r.status not in REQ_INACTIVE_STATUSES
                    _is_recently_done = r.status in REQ_INACTIVE_STATUSES and r.updated_at and r.updated_at.date() >= _30_days_ago
                    if (_is_active or _is_recently_done) and r.project_id not in _hidden_pids:
                        # In project mode, only show requirements belonging to project + sub-projects
                        if view_mode == 'project' and project_pids and r.project_id not in project_pids:
                            continue
                        ud['req_todos'].setdefault(r.id, []).append(t)
                        if r.id not in ud['_req_map']:
                            ud['_req_map'][r.id] = r
                        _has_visible_req = True
                if not _has_visible_req:
                    ud['team_todos'].append(t)

    # Build display_reqs — batch load all user requirements at once (avoid N+1)
    from app.models.requirement import Requirement
    _30_days_ago = today - timedelta(days=30)
    _all_user_reqs_q = Requirement.query.filter(
        Requirement.assignee_id.in_(user_ids),
        db.or_(
            db.and_(Requirement.status.notin_(REQ_INACTIVE_STATUSES), Requirement.start_date <= today),
            db.and_(Requirement.status.in_(REQ_INACTIVE_STATUSES), Requirement.updated_at >= _30_days_ago),
        ),
    )
    if view_mode == 'project' and project_pids:
        _all_user_reqs_q = _all_user_reqs_q.filter(Requirement.project_id.in_(project_pids))
    _all_user_reqs = _all_user_reqs_q.options(joinedload(Requirement.project)).all()
    _reqs_by_uid = {}
    for r in _all_user_reqs:
        _reqs_by_uid.setdefault(r.assignee_id, []).append(r)

    for u in users:
        ud = user_data.setdefault(u.id, {
            'req_todos': {}, 'risk_todos': [], 'team_todos': [],
            'display_reqs': [], 'todos': [], '_req_map': {},
        })
        for r in _reqs_by_uid.get(u.id, []):
            if r.id not in ud['_req_map'] and r.project_id not in _hidden_pids:
                ud['_req_map'][r.id] = r
        # Sort: active first (by due_date), completed last (by updated_at desc)
        ud['display_reqs'] = sorted(ud['_req_map'].values(),
            key=lambda r: (0 if r.status not in REQ_INACTIVE_STATUSES else 1,
                           r.due_date or date(2099,1,1), r.priority))
        ud['todo_total'] = len(ud.get('todos', []))
        ud['todo_done'] = sum(1 for t in ud.get('todos', []) if t.status == TODO_STATUS_DONE)
        ud['overdue_count'] = sum(1 for t in ud.get('todos', [])
                                  if t.status == TODO_STATUS_TODO and t.due_date and t.due_date < today)
        if '_req_map' in ud:
            del ud['_req_map']
        if 'todos' in ud:
            del ud['todos']

    # Project mode: sort users by project order, then overdue count desc
    if view_mode == 'project' and project_pids:
        users.sort(key=lambda u: (
            _user_pid.get(u.id, 999),
            -(user_data.get(u.id, {}).get('overdue_count', 0)),
            u.name,
        ))

    # Todos marked as needing help (filtered by project in project mode)
    _help_q = Todo.query.filter(
        Todo.need_help == True, Todo.status == TODO_STATUS_TODO,  # noqa: E712
        Todo.user_id.in_(user_ids),
    ).options(joinedload(Todo.requirements))
    if view_mode == 'project' and project_pids:
        from app.models.requirement import Requirement as _Req
        _project_req_ids = set(r.id for r in _Req.query.filter(_Req.project_id.in_(project_pids)).all())
        help_todos_raw = _help_q.order_by(Todo.created_at.desc()).all()
        help_todos = [t for t in help_todos_raw
                      if not t.requirements or any(r.id in _project_req_ids for r in t.requirements)]
    else:
        help_todos = _help_q.order_by(Todo.created_at.desc()).all()

    # Guard: user must belong to a group (group mode) or project (project mode)
    if view_mode == 'group' and not current_user.group:
        return render_template('todo/team.html',
            no_group=True, users=[], user_data={}, groups=groups,
            cur_group='', today=today, timedelta=timedelta,
            help_todos=[], req_comments={},
            view_mode=view_mode, cur_project_id=None, cur_project_obj=None,
            open_risks=[],
        )

    # Open risks & blocked todos for standup review
    from sqlalchemy.orm import joinedload as _jl

    from app.models.risk import Risk
    risk_query = Risk.query.filter_by(status='open').filter(Risk.deleted_at.is_(None))
    if view_mode == 'project' and project_pids:
        risk_query = risk_query.filter(Risk.project_id.in_(project_pids))
    open_risks = risk_query.options(
        _jl(Risk.project), _jl(Risk.owner_user), _jl(Risk.tracker), _jl(Risk.comments)
    ).order_by(
        Risk.project_id,
        db.case({'high': 0, 'medium': 1, 'low': 2}, value=Risk.severity, else_=3),
        Risk.due_date,
    ).all()

    # Recent requirement comments (last 3 days)
    from app.models.requirement import Comment as ReqComment
    three_days_ago = today - timedelta(days=3)
    all_req_ids = set()
    for ud in user_data.values():
        all_req_ids.update(ud.get('req_todos', {}).keys())
    req_comments = {}  # req_id → [comments]
    if all_req_ids:
        recent_comments = ReqComment.query.filter(
            ReqComment.requirement_id.in_(all_req_ids),
            ReqComment.created_at >= str(three_days_ago),
        ).options(joinedload(ReqComment.user)).order_by(ReqComment.created_at.desc()).all()
        for c in recent_comments:
            req_comments.setdefault(c.requirement_id, []).append(c)

    # Build project divider info for template (project mode)
    _user_project_idx = {}
    _project_names = {}
    if view_mode == 'project' and project_pids:
        _user_project_idx = _user_pid  # user_id → sorted project index
        _all_projs = Project.query.filter(Project.id.in_(project_pids)).all()
        _proj_map = {p.id: p.name for p in _all_projs}
        _project_names = {_pid_order[pid]: _proj_map.get(pid, '') for pid in project_pids}

    return render_template('todo/team.html',
        users=users, user_data=user_data, groups=groups,
        cur_group=cur_group, today=today, timedelta=timedelta,
        help_todos=help_todos, req_comments=req_comments, no_group=False,
        view_mode=view_mode, cur_project_id=cur_project_id, cur_project_obj=cur_project_obj,
        open_risks=open_risks,
        user_project_idx=_user_project_idx, project_names=_project_names,
    )
