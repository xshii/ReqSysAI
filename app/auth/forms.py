from flask_wtf import FlaskForm
from wtforms import SelectField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

EMPLOYEE_ID_RE = r'^[a-z]\d?00\d{6,7}$'
EMPLOYEE_ID_MSG = '工号格式：1位小写字母 + 8~10位数字，倒数第7、8位为0，如 a00123456 或 q3001234567'


class LoginForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EMPLOYEE_ID_RE, message=EMPLOYEE_ID_MSG),
    ])
    submit = SubmitField('登录')


class RegisterForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EMPLOYEE_ID_RE, message=EMPLOYEE_ID_MSG),
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
