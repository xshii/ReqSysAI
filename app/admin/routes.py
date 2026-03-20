from flask import render_template, redirect, url_for, flash, request

from app.admin import admin_bp
from app.admin.forms import UserCreateForm, UserEditForm
from app.decorators import admin_required
from app.extensions import db
from app.models.user import User, Role, Group
from app.utils.pinyin import to_pinyin


@admin_bp.route('/users')
@admin_required
def user_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def user_create():
    form = UserCreateForm()
    form.role_ids.choices = [(r.id, r.name) for r in Role.query.order_by(Role.id).all()]

    if form.validate_on_submit():
        if User.query.filter_by(ip_address=form.ip_address.data).first():
            flash('该 IP 已被绑定', 'danger')
            return render_template('admin/user_form.html', form=form, title='创建用户')

        selected_roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        user = User(
            employee_id=form.employee_id.data,
            name=form.name.data,
            pinyin=to_pinyin(form.name.data),
            ip_address=form.ip_address.data,
            group=form.group.data or None,
            roles=selected_roles,
        )
        db.session.add(user)
        db.session.commit()
        flash(f'用户 {user.name} 创建成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title='创建用户')


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    form = UserEditForm(obj=user)
    form.role_ids.choices = [(r.id, r.name) for r in Role.query.order_by(Role.id).all()]
    if not form.is_submitted():
        form.role_ids.data = [r.id for r in user.roles]

    if form.validate_on_submit():
        existing = User.query.filter(
            User.ip_address == form.ip_address.data, User.id != user.id
        ).first()
        if existing:
            flash(f'该 IP 已被 {existing.name} 绑定', 'danger')
            return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.name}', user=user)

        user.employee_id = form.employee_id.data
        user.name = form.name.data
        user.pinyin = to_pinyin(form.name.data)
        user.ip_address = form.ip_address.data
        user.group = form.group.data or None
        user.roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        user.is_active = form.is_active.data
        db.session.commit()
        flash(f'用户 {user.name} 更新成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.name}', user=user)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def user_toggle(user_id):
    user = db.get_or_404(User, user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status = '启用' if user.is_active else '禁用'
    flash(f'用户 {user.name} 已{status}', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/groups', methods=['GET', 'POST'])
@admin_required
def group_list():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            name = request.form.get('group_name', '').strip()
            if not name:
                flash('请输入团队名称', 'danger')
            elif Group.query.filter_by(name=name).first():
                flash(f'团队 {name} 已存在', 'warning')
            else:
                db.session.add(Group(name=name))
                db.session.commit()
                flash(f'团队 {name} 已创建', 'success')
        elif action == 'rename':
            old_name = request.form.get('old_name', '').strip()
            new_name = request.form.get('new_name', '').strip()
            if old_name and new_name:
                g = Group.query.filter_by(name=old_name).first()
                if g:
                    g.name = new_name
                User.query.filter_by(group=old_name).update({'group': new_name})
                db.session.commit()
                flash(f'团队 {old_name} 已重命名为 {new_name}', 'success')
        elif action == 'delete':
            name = request.form.get('group_name', '').strip()
            if name:
                g = Group.query.filter_by(name=name).first()
                if g:
                    db.session.delete(g)
                User.query.filter_by(group=name).update({'group': None})
                db.session.commit()
                flash(f'团队 {name} 已解散', 'success')
        elif action == 'add_member':
            group_name = request.form.get('group_name', '').strip()
            user_id = request.form.get('user_id', type=int)
            user = db.session.get(User, user_id) if user_id else None
            if user and group_name:
                user.group = group_name
                db.session.commit()
                flash(f'{user.name} 已加入 {group_name}', 'success')
        elif action == 'remove_member':
            user_id = request.form.get('user_id', type=int)
            user = db.session.get(User, user_id) if user_id else None
            if user:
                old = user.group
                user.group = None
                db.session.commit()
                flash(f'{user.name} 已移出 {old}', 'success')
        return redirect(url_for('admin.group_list'))

    # All groups from Group table, with member count
    all_groups = Group.query.order_by(Group.name).all()
    groups = []
    group_members = {}
    for g in all_groups:
        members = User.query.filter_by(group=g.name, is_active=True)\
            .order_by(User.name).all()
        groups.append((g.name, len(members)))
        group_members[g.name] = members

    ungrouped = User.query.filter(
        User.is_active == True,
        db.or_(User.group.is_(None), User.group == '')
    ).order_by(User.name).all()

    return render_template('admin/groups.html', groups=groups,
                           group_members=group_members, ungrouped=ungrouped)


# ---- Milestone templates ----

@admin_bp.route('/milestone-templates', methods=['GET', 'POST'])
@admin_required
def milestone_template_list():
    from app.models.project import MilestoneTemplate, MilestoneTemplateItem

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            name = request.form.get('name', '').strip()
            if not name:
                flash('请输入模板名称', 'danger')
            elif MilestoneTemplate.query.filter_by(name=name).first():
                flash(f'模板 {name} 已存在', 'warning')
            else:
                tpl = MilestoneTemplate(
                    name=name,
                    description=request.form.get('description', '').strip() or None,
                )
                # Parse milestone items
                item_names = request.form.getlist('item_name')
                item_offsets = request.form.getlist('item_offset')
                for i, iname in enumerate(item_names):
                    iname = iname.strip()
                    if iname:
                        offset = int(item_offsets[i]) if i < len(item_offsets) and item_offsets[i] else 0
                        tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=offset, sort_order=i))
                db.session.add(tpl)
                db.session.commit()
                flash(f'模板 {name} 已创建', 'success')
        elif action == 'delete':
            tpl_id = request.form.get('template_id', type=int)
            tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
            if tpl:
                db.session.delete(tpl)
                db.session.commit()
                flash(f'模板 {tpl.name} 已删除', 'success')
        return redirect(url_for('admin.milestone_template_list'))

    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()
    return render_template('admin/milestone_templates.html', templates=templates)
