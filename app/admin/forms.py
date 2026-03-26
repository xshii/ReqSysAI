from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.constants import EID_FULL_RE, EID_MSG, MGR_FIELD_RE, MGR_FIELD_MSG


class UserCreateForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EID_FULL_RE, message=EID_MSG),
    ])
    name = StringField('姓名', validators=[DataRequired(), Length(min=2, max=80)])
    ip_address = StringField('IP 地址', validators=[Optional(), Length(max=45)])
    group = StringField('小组', validators=[Optional(), Length(max=50)])
    manager = StringField('主管', validators=[Optional(), Length(max=100),
                          Regexp(MGR_FIELD_RE, message=MGR_FIELD_MSG)])
    domain = StringField('业务领域', validators=[Optional(), Length(max=100)])
    role_ids = SelectMultipleField('角色', coerce=int, validators=[DataRequired()])
    submit = SubmitField('创建用户')


class UserEditForm(FlaskForm):
    employee_id = StringField('工号', validators=[
        DataRequired(message='请输入工号'),
        Regexp(EID_FULL_RE, message=EID_MSG),
    ])
    name = StringField('姓名', validators=[DataRequired(), Length(min=2, max=80)])
    ip_address = StringField('IP 地址', validators=[Optional(), Length(max=45)])
    group = StringField('小组', validators=[Optional(), Length(max=50)])
    manager = StringField('主管', validators=[Optional(), Length(max=100),
                          Regexp(MGR_FIELD_RE, message=MGR_FIELD_MSG)])
    domain = StringField('业务领域', validators=[Optional(), Length(max=100)])
    role_ids = SelectMultipleField('角色', coerce=int, validators=[DataRequired()])
    is_active = BooleanField('启用')
    submit = SubmitField('保存')
