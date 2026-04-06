"""Unified audit log for all high-risk operations."""
from app.extensions import _local_now, db


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)   # create/delete/update/approve/reject
    entity_type = db.Column(db.String(50), nullable=False)  # requirement/risk/user/permission/incentive/todo/meeting
    entity_id = db.Column(db.Integer, nullable=True)
    entity_title = db.Column(db.String(300), nullable=True)
    detail = db.Column(db.Text, nullable=True)           # JSON or text description
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=_local_now)

    user = db.relationship('User', backref='audit_logs')

    @property
    def action_label(self):
        return {
            'create': '创建', 'delete': '删除', 'update': '修改',
            'approve': '审批通过', 'reject': '审批拒绝',
            'status_change': '状态变更', 'soft_delete': '软删除',
        }.get(self.action, self.action)
