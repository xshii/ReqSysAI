from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

EMPLOYEE_ID_RE = r'^[a-z]\d?00\d{6}$'
EMPLOYEE_ID_MSG = '工号格式：1位小写字母 + 8~9位数字，倒数第7、8位为0，如 a00123456'


class UserCreateForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EMPLOYEE_ID_RE, message=EMPLOYEE_ID_MSG),
    ])
    name = StringField('姓名', validators=[DataRequired(), Length(min=2, max=80)])
    ip_address = StringField('IP 地址', validators=[DataRequired(), Length(max=45)])
    group = StringField('小组', validators=[Optional(), Length(max=50)])
    role_ids = SelectMultipleField('角色', coerce=int, validators=[DataRequired()])
    submit = SubmitField('创建用户')


class UserEditForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EMPLOYEE_ID_RE, message=EMPLOYEE_ID_MSG),
    ])
    name = StringField('姓名', validators=[DataRequired(), Length(min=2, max=80)])
    ip_address = StringField('IP 地址', validators=[Optional(), Length(max=45)])
    group = StringField('小组', validators=[Optional(), Length(max=50)])
    manager = StringField('主管', validators=[Optional(), Length(max=100)])
    domain = StringField('业务领域', validators=[Optional(), Length(max=100)])
    role_ids = SelectMultipleField('角色', coerce=int, validators=[DataRequired()])
    is_active = BooleanField('启用')
    submit = SubmitField('保存')
