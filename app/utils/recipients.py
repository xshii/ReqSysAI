"""Shared logic for computing default email To/Cc recipients."""

from app.extensions import db
from app.models.project_member import ProjectMember
from app.models.risk import Risk
from app.models.user import User


def compute_default_recipients(cur_project_id, include_sub=True, cc_level='full'):
    """Compute default To (member + risk tracker/owner employee_ids) and Cc (their managers).

    Args:
        cur_project_id: primary project id
        include_sub: if True, also include sub-project members and risks
    Returns (to_str, cc_str) with semicolon-separated employee_ids.
    """
    default_to = ''
    default_cc = ''
    if not cur_project_id:
        return default_to, default_cc

    from app.models.project import Project
    all_pids = [cur_project_id]
    if include_sub:
        all_pids += [c.id for c in Project.query.filter_by(parent_id=cur_project_id).all()]

    # To: all project members' employee_ids (project + sub-projects)
    members = ProjectMember.query.filter(ProjectMember.project_id.in_(all_pids)).all()
    to_eids = []
    for m in members:
        if m.user and m.user.employee_id:
            to_eids.append(m.user.employee_id)
    default_to = ';'.join(to_eids)
    if not default_to:
        from flask_login import current_user
        if current_user.is_authenticated and current_user.employee_id:
            default_to = current_user.employee_id

    # To also includes risk tracker + owner
    to_set = set(to_eids)
    open_risks = Risk.query.filter(Risk.project_id.in_(all_pids), Risk.status == 'open')\
        .filter(Risk.deleted_at.is_(None)).all()
    for r in open_risks:
        if r.tracker and r.tracker.employee_id:
            to_set.add(r.tracker.employee_id)
        if r.owner_id:
            owner_user = db.session.get(User, r.owner_id)
            if owner_user and owner_user.employee_id:
                to_set.add(owner_user.employee_id)
    default_to = ';'.join(sorted(to_set))

    # Cc: PM + managers (if cc_managers=True)
    cc_eids = set()
    from flask_login import current_user as _cu
    from app.models.project import Project
    my_mgr_eid = ''
    my_mgr2_eid = ''

    if cc_level not in ('manager', 'full'):
        cc_level = 'full'
    # 'manager': PM + direct managers
    # 'full': PM + direct managers + current user's manager's manager
    all_user_ids = set()
    for m in members:
        if m.user:
            all_user_ids.add(m.user.id)
    for r in open_risks:
        if r.tracker_id:
            all_user_ids.add(r.tracker_id)
        if r.owner_id:
            all_user_ids.add(r.owner_id)
    if _cu.is_authenticated:
        all_user_ids.add(_cu.id)

    project = db.session.get(Project, cur_project_id)
    if project and project.owner_id:
        pm_user = db.session.get(User, project.owner_id)
        if pm_user and pm_user.employee_id:
            if pm_user.employee_id not in to_set:
                cc_eids.add(pm_user.employee_id)
            if pm_user.manager:
                parts = pm_user.manager.strip().split()
                pm_mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
                if pm_mgr_eid:
                    cc_eids.add(pm_mgr_eid)
            all_user_ids.add(pm_user.id)

    if _cu.is_authenticated and _cu.manager:
        parts = _cu.manager.strip().split()
        my_mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
        if my_mgr_eid and cc_level == 'full':
            mgr_user = User.query.filter_by(employee_id=my_mgr_eid, is_active=True).first()
            if mgr_user and mgr_user.manager:
                mgr2_parts = mgr_user.manager.strip().split()
                my_mgr2_eid = mgr2_parts[-1] if len(mgr2_parts) > 1 else mgr2_parts[0]
    for uid in all_user_ids:
        u = db.session.get(User, uid)
        if u and u.manager:
            parts = u.manager.strip().split()
            mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
            if mgr_eid:
                cc_eids.add(mgr_eid)
    # Remove anyone already in To
    cc_eids -= to_set
    cc_list = []
    # Only include manager's manager for 'full' level (weekly reports)
    if cc_level == 'full' and my_mgr2_eid and my_mgr2_eid not in to_set:
        cc_list.append(my_mgr2_eid)
        cc_eids.discard(my_mgr2_eid)
    if my_mgr_eid and my_mgr_eid not in to_set:
        cc_list.append(my_mgr_eid)
        cc_eids.discard(my_mgr_eid)
    cc_list.extend(sorted(cc_eids))
    default_cc = ';'.join(cc_list)
    return default_to, default_cc


def compute_meeting_recipients(project_id, meeting):
    """Compute To/Cc for a meeting email.

    To: 与会人工号 + 关联风险跟踪人/责任人工号
    Cc: 风险责任人主管工号 + 发件人主管工号 + 项目经理工号
    """
    to_set = set()
    risk_owner_ids = set()  # 风险责任人 user_id，用于取主管

    # To: 与会人工号
    if meeting.attendees:
        for name in meeting.attendees.split(','):
            name = name.strip()
            if not name:
                continue
            user = User.query.filter_by(name=name, is_active=True).first()
            if user and user.employee_id:
                to_set.add(user.employee_id)

    # To: 关联风险的跟踪人 + 责任人
    linked_risks = Risk.query.filter_by(meeting_id=meeting.id)\
        .filter(Risk.deleted_at.is_(None)).all()
    for r in linked_risks:
        if r.tracker and r.tracker.employee_id:
            to_set.add(r.tracker.employee_id)
        if r.owner_id:
            owner_user = db.session.get(User, r.owner_id)
            if owner_user:
                if owner_user.employee_id:
                    to_set.add(owner_user.employee_id)
                risk_owner_ids.add(owner_user.id)

    default_to = ';'.join(sorted(to_set))

    # Cc: 风险责任人主管 + 发件人主管 + 项目经理
    cc_set = set()

    # 风险责任人的主管
    for uid in risk_owner_ids:
        u = db.session.get(User, uid)
        if u and u.manager:
            parts = u.manager.strip().split()
            mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
            if mgr_eid:
                cc_set.add(mgr_eid)

    # 发件人（当前用户）的主管
    from flask_login import current_user as _cu2
    if _cu2.is_authenticated and _cu2.manager:
        parts = _cu2.manager.strip().split()
        my_mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
        if my_mgr_eid:
            cc_set.add(my_mgr_eid)

    # 项目经理
    from app.models.project import Project
    project = db.session.get(Project, project_id)
    if project and project.owner_id:
        pm_user = db.session.get(User, project.owner_id)
        if pm_user and pm_user.employee_id:
            cc_set.add(pm_user.employee_id)

    # 去掉已在 To 中的
    cc_set -= to_set
    default_cc = ';'.join(sorted(cc_set))
    return default_to, default_cc


def compute_personal_recipients(user):
    """Compute To/Cc for a personal weekly report.

    To: the user's own employee_id
    Cc: manager + all active members in same group
    """
    from app.models.user import User

    to_eid = user.employee_id or ''
    cc_set = set()

    # Add manager
    if user.manager:
        parts = user.manager.strip().split()
        mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
        if mgr_eid and mgr_eid != to_eid:
            cc_set.add(mgr_eid)

    # Add same-group members
    if user.group:
        group_members = User.query.filter_by(group=user.group, is_active=True).all()
        for m in group_members:
            if m.employee_id and m.employee_id != to_eid:
                cc_set.add(m.employee_id)

    return to_eid, ';'.join(sorted(cc_set))
