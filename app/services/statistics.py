# -*- coding: utf-8 -*-
"""Centralized statistics and data gathering for dashboard & weekly reports.

Eliminates duplicated data-gathering logic across routes.
"""
from collections import Counter, defaultdict, namedtuple
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.requirement import Requirement
from app.models.todo import Todo, todo_requirements
from app.models.user import User

UserStat = namedtuple('UserStat', 'user created done rate')
UserDays = namedtuple('UserDays', 'user days')
ProjectInv = namedtuple('ProjectInv', 'project user_days total_days people_count')
TodoProgress = namedtuple('TodoProgress', 'total done')


def week_range(offset=0):
    """Return (monday, sunday) for current week + offset."""
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def gather_project_data(monday, sunday, project_id=None):
    """Gather todos, requirements, investment data for a project in a week.

    Returns a dict with all data needed by weekly report and stats.
    Single source of truth — replaces 4+ copies of this logic.
    """
    from app.models.project import Project
    from app.models.risk import Risk

    # Todos: done + active, optionally filtered by project
    def _filter_by_project(q):
        if project_id:
            q = q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                 .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                 .filter(Requirement.project_id == project_id)
        return q

    todos_done = _filter_by_project(
        Todo.query.filter(Todo.done_date >= monday, Todo.done_date <= sunday)
            .options(joinedload(Todo.user), joinedload(Todo.requirements))
    ).all()

    todos_active = _filter_by_project(
        Todo.query.filter(Todo.created_date <= sunday, Todo.status == 'todo')
            .options(joinedload(Todo.user), joinedload(Todo.requirements))
    ).all()

    # Per-person stats
    person_done = Counter(t.user.name for t in todos_done)
    person_active = Counter(t.user.name for t in todos_active)
    all_persons = sorted(set(list(person_done.keys()) + list(person_active.keys())))

    # Per-requirement investment
    req_investment = {}
    for t in todos_done + todos_active:
        for r in t.requirements:
            inv = req_investment.setdefault(r.number, {'title': r.title, 'people': set(), 'days': 0})
            inv['people'].add(t.user.name)
            inv['days'] += 1

    # Requirements overview (top-level only)
    req_q = Requirement.query.filter(Requirement.parent_id.is_(None))
    if project_id:
        req_q = req_q.filter_by(project_id=project_id)
    all_reqs = req_q.order_by(Requirement.number).all()

    # Requirement changes this week
    req_changes_q = Requirement.query.filter(
        Requirement.updated_at >= monday,
        Requirement.updated_at <= sunday + timedelta(days=1),
    )
    if project_id:
        req_changes_q = req_changes_q.filter_by(project_id=project_id)
    req_changes = req_changes_q.all()

    # Open risks
    risk_q = Risk.query.filter_by(status='open').filter(Risk.deleted_at.is_(None))
    if project_id:
        risk_q = risk_q.filter_by(project_id=project_id)
    open_risks = risk_q.order_by(Risk.severity, Risk.due_date).all()

    # Milestones
    milestones = []
    cur_project = None
    if project_id:
        cur_project = db.session.get(Project, project_id)
        if cur_project:
            milestones = cur_project.milestones

    # People map: person × requirement matrix
    people_map = {}
    people_map_reqs = sorted(req_investment.keys())
    for rnum, inv in req_investment.items():
        for pname in inv['people']:
            if pname not in people_map:
                people_map[pname] = {'_total': 0}
            share = inv['days'] // max(len(inv['people']), 1)
            people_map[pname][rnum] = share
            people_map[pname]['_total'] += share

    project_name = cur_project.name if cur_project else '研发团队'

    # Sub-project progress (for parent projects)
    sub_projects = []
    if cur_project and cur_project.children:
        from app.models.report import WeeklyReport
        for child in cur_project.children:
            # Get saved summary for this child project this week
            child_report = WeeklyReport.query.filter_by(
                project_id=child.id, week_start=monday
            ).first()
            sub_projects.append({
                'project': child,
                'owner': child.owner,
                'summary': child_report.summary if child_report else '未生成周报',
            })

    return {
        'project_name': project_name,
        'today': date.today(),
        'monday': monday,
        'sunday': sunday,
        'milestones': milestones,
        'all_reqs': all_reqs,
        'req_changes': req_changes,
        'req_investment': req_investment,
        'person_done': dict(person_done),
        'person_active': dict(person_active),
        'all_persons': all_persons,
        'todos_done': todos_done,
        'todos_active': todos_active,
        'open_risks': open_risks,
        'people_map': people_map,
        'people_map_reqs': people_map_reqs,
        'sub_projects': sub_projects,
    }


def gather_week_stats(monday, sunday, group=None, project_id=None):
    """Gather weekly stats for stats page. Returns WeekStats namedtuple."""
    from app.models.project import Project

    user_query = User.query.filter_by(is_active=True)
    if group:
        user_query = user_query.filter_by(group=group)
    users = user_query.order_by(User.group, User.name).all()
    user_ids = [u.id for u in users]

    def _todo_filter(q):
        if project_id:
            q = q.join(todo_requirements, Todo.id == todo_requirements.c.todo_id)\
                 .join(Requirement, Requirement.id == todo_requirements.c.requirement_id)\
                 .filter(Requirement.project_id == project_id)
        return q

    created_map = dict(_todo_filter(db.session.query(
        Todo.user_id, func.count(db.distinct(Todo.id))
    ).filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= monday, Todo.created_date <= sunday,
    )).group_by(Todo.user_id).all())

    done_map = dict(_todo_filter(db.session.query(
        Todo.user_id, func.count(db.distinct(Todo.id))
    ).filter(
        Todo.user_id.in_(user_ids),
        Todo.done_date >= monday, Todo.done_date <= sunday,
    )).group_by(Todo.user_id).all())

    user_stats = []
    for u in users:
        created = created_map.get(u.id, 0)
        done = done_map.get(u.id, 0)
        if project_id and created == 0 and done == 0:
            continue
        user_stats.append(UserStat(
            user=u, created=created, done=done,
            rate=round(done / created * 100) if created else 0,
        ))

    req_query = Requirement.query
    if project_id:
        req_query = req_query.filter_by(project_id=project_id)
    req_total = req_query.count()
    req_done = req_query.filter(Requirement.status.in_(['done', 'closed'])).count()

    # Per-user per-project investment
    week_todos = Todo.query.filter(
        Todo.user_id.in_(user_ids),
        Todo.created_date >= monday, Todo.created_date <= sunday,
    ).options(joinedload(Todo.requirements)).all()

    user_date_projects = defaultdict(lambda: defaultdict(set))
    for t in week_todos:
        for r in t.requirements:
            if r.project_id:
                user_date_projects[t.user_id][t.created_date].add(r.project_id)

    user_project_days = defaultdict(float)
    for uid, date_projects in user_date_projects.items():
        for _dt, pids in date_projects.items():
            share = 1.0 / len(pids) if pids else 0
            for pid in pids:
                user_project_days[(uid, pid)] += share

    project_ids = set(pid for (_, pid) in user_project_days)
    if project_id:
        project_ids = {pid for pid in project_ids if pid == project_id}
    projects = {p.id: p for p in Project.query.filter(Project.id.in_(project_ids)).all()} if project_ids else {}

    project_investment = []
    for pid in sorted(project_ids):
        p = projects.get(pid)
        if not p:
            continue
        udays = []
        total = 0.0
        for u in users:
            d = user_project_days.get((u.id, pid), 0)
            if d > 0:
                udays.append(UserDays(user=u, days=round(d, 1)))
                total += d
        project_investment.append(ProjectInv(
            project=p, user_days=udays,
            total_days=round(total, 1), people_count=len(udays),
        ))

    WeekStats = namedtuple('WeekStats', 'user_stats req_total req_done req_rate project_investment')
    return WeekStats(
        user_stats=user_stats,
        req_total=req_total,
        req_done=req_done,
        req_rate=round(req_done / req_total * 100) if req_total else 0,
        project_investment=project_investment,
    )


def get_reviewer(current_user):
    """Determine reviewer based on current user's role and group.
    PL → LM/XM (global, not group-specific)
    Others → same-group PL
    """
    from app.models.user import Role
    if current_user.has_role('PL'):
        # LM/XM are global roles (one per org, not per group)
        for role_name in ('LM', 'XM'):
            reviewer = User.query.filter(User.is_active == True)\
                .join(User.roles).filter(Role.name == role_name).first()
            if reviewer:
                return reviewer.name
        return '待定'
    else:
        # Find PL in same group
        pl = User.query.filter(User.is_active == True, User.group == current_user.group)\
            .join(User.roles).filter(Role.name == 'PL').first()
        return pl.name if pl else '待定'


def get_todo_progress(req_ids):
    """Get todo progress for a list of requirement IDs. Returns dict of {req_id: TodoProgress}."""
    if not req_ids:
        return {}
    rows = db.session.query(
        todo_requirements.c.requirement_id,
        func.count(Todo.id),
        func.sum(db.case((Todo.status == 'done', 1), else_=0)),
    ).join(Todo, Todo.id == todo_requirements.c.todo_id)\
     .filter(todo_requirements.c.requirement_id.in_(req_ids))\
     .group_by(todo_requirements.c.requirement_id).all()
    return {rid: TodoProgress(total=total, done=int(done or 0)) for rid, total, done in rows}


def get_hidden_roles():
    """Get set of hidden role names + Admin."""
    from flask import current_app
    return set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])


def get_delivery_metrics(project_id=None):
    """Calculate lead time and cycle time for completed requirements.

    - lead_time: created_at -> status='done' (in days)
    - cycle_time: status='in_dev' -> status='done' (in days)
    Returns list of dicts with req info + lead_time + cycle_time.
    """
    from app.models.requirement import Activity

    # Get all done requirements
    req_q = Requirement.query.filter(Requirement.status.in_(['done', 'closed']))
    if project_id:
        req_q = req_q.filter_by(project_id=project_id)
    done_reqs = req_q.options(joinedload(Requirement.project)).all()

    if not done_reqs:
        return []

    req_ids = [r.id for r in done_reqs]

    # Fetch all status_changed activities for these requirements
    activities = Activity.query.filter(
        Activity.requirement_id.in_(req_ids),
        Activity.action == 'status_changed',
    ).order_by(Activity.created_at).all()

    # Build lookup: req_id -> list of activities
    act_map = defaultdict(list)
    for a in activities:
        act_map[a.requirement_id].append(a)

    done_label = Requirement.STATUS_LABELS['done']
    in_dev_label = Requirement.STATUS_LABELS['in_dev']

    results = []
    for req in done_reqs:
        req_activities = act_map.get(req.id, [])

        # Find the first activity where status changed TO done (detail ends with done_label)
        done_at = None
        in_dev_at = None
        for act in req_activities:
            detail = act.detail or ''
            # detail format: "旧状态 → 新状态"
            if detail.endswith(done_label) and done_at is None:
                done_at = act.created_at
            if detail.endswith(in_dev_label) and in_dev_at is None:
                in_dev_at = act.created_at

        if done_at is None:
            continue

        lead_time = (done_at - req.created_at).days
        cycle_time = (done_at - in_dev_at).days if in_dev_at else None

        results.append({
            'req_number': req.number,
            'title': req.title,
            'project_name': req.project.name if req.project else '-',
            'created_at': req.created_at,
            'done_at': done_at,
            'lead_time': lead_time,
            'cycle_time': cycle_time,
        })

    return results


def get_estimate_deviation(project_id=None):
    """Compare estimate_days vs actual effort (from linked todos actual_minutes).

    Returns list of dicts: {req_number, title, estimate_days, actual_days, deviation_pct}
    """
    # Get requirements with estimate_days > 0
    req_q = Requirement.query.filter(
        Requirement.estimate_days.isnot(None),
        Requirement.estimate_days > 0,
    )
    if project_id:
        req_q = req_q.filter_by(project_id=project_id)
    reqs = req_q.options(joinedload(Requirement.project)).all()

    if not reqs:
        return []

    req_ids = [r.id for r in reqs]

    # Sum actual_minutes from linked todos via todo_requirements M2M
    rows = db.session.query(
        todo_requirements.c.requirement_id,
        func.sum(Todo.actual_minutes),
    ).join(Todo, Todo.id == todo_requirements.c.todo_id)\
     .filter(
        todo_requirements.c.requirement_id.in_(req_ids),
        Todo.actual_minutes.isnot(None),
    ).group_by(todo_requirements.c.requirement_id).all()

    minutes_map = {rid: int(total or 0) for rid, total in rows}

    results = []
    for req in reqs:
        total_minutes = minutes_map.get(req.id, 0)
        if total_minutes == 0:
            continue
        actual_days = round(total_minutes / 480, 2)  # 8h/day = 480 min
        deviation_pct = round((actual_days - req.estimate_days) / req.estimate_days * 100, 1)

        results.append({
            'req_number': req.number,
            'title': req.title,
            'project_name': req.project.name if req.project else '-',
            'estimate_days': req.estimate_days,
            'actual_days': actual_days,
            'deviation_pct': deviation_pct,
        })

    return results
