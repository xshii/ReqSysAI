from flask import render_template, redirect, url_for, flash, request

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
    form.role_id.choices = [(r.id, r.display_name) for r in Role.query.all()]

    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('用户名已存在', 'danger')
            return render_template('admin/user_form.html', form=form, title='创建用户')
        if User.query.filter_by(email=form.email.data).first():
            flash('邮箱已存在', 'danger')
            return render_template('admin/user_form.html', form=form, title='创建用户')

        user = User(
            username=form.username.data,
            email=form.email.data,
            display_name=form.display_name.data,
            role_id=form.role_id.data,
            auth_type='local',
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'用户 {user.display_name} 创建成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title='创建用户')


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def user_edit(user_id):
    user = db.get_or_404(User, user_id)
    form = UserEditForm(obj=user)
    form.role_id.choices = [(r.id, r.display_name) for r in Role.query.all()]

    if form.validate_on_submit():
        # Check email uniqueness (exclude current user)
        existing = User.query.filter(
            User.email == form.email.data, User.id != user.id
        ).first()
        if existing:
            flash('邮箱已被其他用户使用', 'danger')
            return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.display_name}', user=user)

        user.email = form.email.data
        user.display_name = form.display_name.data
        user.role_id = form.role_id.data
        user.is_active = form.is_active.data
        if form.password.data:
            user.set_password(form.password.data)
        db.session.commit()
        flash(f'用户 {user.display_name} 更新成功', 'success')
        return redirect(url_for('admin.user_list'))

    return render_template('admin/user_form.html', form=form, title=f'编辑用户 - {user.display_name}', user=user)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def user_toggle(user_id):
    user = db.get_or_404(User, user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status = '启用' if user.is_active else '禁用'
    flash(f'用户 {user.display_name} 已{status}', 'success')
    return redirect(url_for('admin.user_list'))
