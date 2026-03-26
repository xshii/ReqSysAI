from flask_wtf import FlaskForm
from wtforms import SelectField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.constants import EID_FULL_RE, EID_MSG


class LoginForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EID_FULL_RE, message=EID_MSG),
    ])
    submit = SubmitField('登录')


class RegisterForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EID_FULL_RE, message=EID_MSG),
    ])
    name = StringField('姓名', validators=[DataRequired(message='请输入姓名'), Length(min=2, max=80)])
    role_ids = SelectMultipleField('角色', coerce=int, validators=[DataRequired(message='请至少选择一个角色')])
    group = SelectField('小组', validators=[Optional()])
    submit = SubmitField('注册')


class ProfileForm(FlaskForm):
    name = StringField('姓名', validators=[DataRequired(message='请输入姓名'), Length(min=2, max=80)])
    role_ids = SelectMultipleField('角色', coerce=int, validators=[DataRequired(message='请至少选择一个角色')])
    group = SelectField('小组', validators=[Optional()])
    submit = SubmitField('保存')
