from flask import render_template, redirect, url_for, flash

from app.admin import admin_bp
from app.admin.forms import UserCreateForm, UserEditForm
from app.decorators import admin_required
from app.extensions import db
from app.models.user import User, Role


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
