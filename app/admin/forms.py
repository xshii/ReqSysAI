from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Optional, Length


class UserCreateForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(min=2, max=80)])
    email = StringField('邮箱', validators=[DataRequired(), Email()])
    display_name = StringField('姓名', validators=[DataRequired(), Length(max=80)])
    password = PasswordField('密码', validators=[DataRequired(), Length(min=6)])
    role_id = SelectField('角色', coerce=int, validators=[DataRequired()])
    submit = SubmitField('创建用户')


class UserEditForm(FlaskForm):
    email = StringField('邮箱', validators=[DataRequired(), Email()])
    display_name = StringField('姓名', validators=[DataRequired(), Length(max=80)])
    password = PasswordField('新密码（留空则不修改）', validators=[Optional(), Length(min=6)])
    role_id = SelectField('角色', coerce=int, validators=[DataRequired()])
    is_active = BooleanField('启用')
    submit = SubmitField('保存')
