"""Shared logic for computing default email To/Cc recipients."""

from app.extensions import db
from app.models.project_member import ProjectMember
from app.models.risk import Risk
from app.models.user import User


def compute_default_recipients(cur_project_id):
    """Compute default To (member + risk tracker/owner employee_ids) and Cc (their managers).

    Returns (to_str, cc_str) with semicolon-separated employee_ids.
    """
    default_to = ''
    default_cc = ''
    if not cur_project_id:
        return default_to, default_cc

    # To: all project members' employee_ids
    members = ProjectMember.query.filter_by(project_id=cur_project_id).all()
    to_eids = []
    for m in members:
        if m.user and m.user.employee_id:
            to_eids.append(m.user.employee_id)
    default_to = ';'.join(to_eids)
    if not default_to:
        # Fallback: use current user
        from flask_login import current_user
        if current_user.is_authenticated and current_user.employee_id:
            default_to = current_user.employee_id

    # To also includes risk tracker + owner
    to_set = set(to_eids)
    open_risks = Risk.query.filter_by(project_id=cur_project_id, status='open')\
        .filter(Risk.deleted_at.is_(None)).all()
    for r in open_risks:
        if r.tracker and r.tracker.employee_id:
            to_set.add(r.tracker.employee_id)
        if r.owner_id:
            owner_user = db.session.get(User, r.owner_id)
            if owner_user and owner_user.employee_id:
                to_set.add(owner_user.employee_id)
    default_to = ';'.join(sorted(to_set))

    # Cc: all To people's managers + risk owners'/trackers' managers
    cc_eids = set()
    # Managers of all project members
    all_user_ids = set()
    for m in members:
        if m.user:
            all_user_ids.add(m.user.id)
    # Managers of risk tracker/owner
    for r in open_risks:
        if r.tracker_id:
            all_user_ids.add(r.tracker_id)
        if r.owner_id:
            all_user_ids.add(r.owner_id)
    for uid in all_user_ids:
        u = db.session.get(User, uid)
        if u and u.manager:
            parts = u.manager.strip().split()
            mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
            if mgr_eid:
                cc_eids.add(mgr_eid)
    # Remove anyone already in To
    cc_eids -= to_set
    default_cc = ';'.join(sorted(cc_eids))
    return default_to, default_cc


def compute_meeting_recipients(project_id, meeting):
    """Compute To/Cc for a meeting email.

    To: attendees' employee_ids + linked risk tracker/owner employee_ids
    Cc: all above people's managers, minus anyone in To
    """
    to_set = set()
    all_user_ids = set()

    # Attendees: match names to User.employee_id
    if meeting.attendees:
        for name in meeting.attendees.split(','):
            name = name.strip()
            if not name:
                continue
            user = User.query.filter_by(name=name, is_active=True).first()
            if user:
                if user.employee_id:
                    to_set.add(user.employee_id)
                all_user_ids.add(user.id)

    # Project members also go to To
    members = ProjectMember.query.filter_by(project_id=project_id).all()
    for m in members:
        if m.user and m.user.employee_id:
            to_set.add(m.user.employee_id)
        if m.user:
            all_user_ids.add(m.user.id)

    # Linked risks: tracker + owner
    linked_risks = Risk.query.filter_by(meeting_id=meeting.id)\
        .filter(Risk.deleted_at.is_(None)).all()
    for r in linked_risks:
        if r.tracker and r.tracker.employee_id:
            to_set.add(r.tracker.employee_id)
            all_user_ids.add(r.tracker.id)
        if r.owner_id:
            owner_user = db.session.get(User, r.owner_id)
            if owner_user:
                if owner_user.employee_id:
                    to_set.add(owner_user.employee_id)
                all_user_ids.add(owner_user.id)

    # Also include open project risks (same as weekly report)
    open_risks = Risk.query.filter_by(project_id=project_id, status='open')\
        .filter(Risk.deleted_at.is_(None)).all()
    for r in open_risks:
        if r.tracker and r.tracker.employee_id:
            to_set.add(r.tracker.employee_id)
            all_user_ids.add(r.tracker.id)
        if r.owner_id:
            owner_user = db.session.get(User, r.owner_id)
            if owner_user:
                if owner_user.employee_id:
                    to_set.add(owner_user.employee_id)
                all_user_ids.add(owner_user.id)

    default_to = ';'.join(sorted(to_set))

    # Cc: all above people's managers
    cc_eids = set()
    for uid in all_user_ids:
        u = db.session.get(User, uid)
        if u and u.manager:
            parts = u.manager.strip().split()
            mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
            if mgr_eid:
                cc_eids.add(mgr_eid)
    cc_eids -= to_set
    default_cc = ';'.join(sorted(cc_eids))
    return default_to, default_cc


def compute_personal_recipients(user):
    """Compute To/Cc for a personal weekly report.

    To: the user's own employee_id
    Cc: the user's manager
    """
    to_eid = user.employee_id or ''
    cc_eid = ''
    if user.manager:
        parts = user.manager.strip().split()
        mgr_eid = parts[-1] if len(parts) > 1 else parts[0]
        if mgr_eid and mgr_eid != to_eid:
            cc_eid = mgr_eid
    return to_eid, cc_eid
