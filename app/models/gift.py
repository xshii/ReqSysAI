from app.extensions import db


class GiftItem(db.Model):
    """Small gift catalog for incentive rewards."""
    __tablename__ = 'gift_items'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)  # 礼物名称
    description = db.Column(db.String(500), nullable=True)  # 一句话说明
    link = db.Column(db.String(500), nullable=True)  # 购买链接
    image = db.Column(db.String(300), nullable=True)  # 图片路径
    price = db.Column(db.Float, nullable=True)  # 参考价格
    picks = db.Column(db.Integer, default=0)  # 已选择人数
    is_active = db.Column(db.Boolean, default=True)  # 是否可选
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    creator = db.relationship('User', backref='created_gifts')

    def __repr__(self):
        return f'<GiftItem {self.name}>'


class GiftRecord(db.Model):
    """Per-person gift selection record for incentive rewards."""
    __tablename__ = 'gift_records'

    id = db.Column(db.Integer, primary_key=True)
    incentive_id = db.Column(db.Integer, db.ForeignKey('incentives.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    gift_item_id = db.Column(db.Integer, db.ForeignKey('gift_items.id'), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending/selected/purchased
    notified_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    selected_at = db.Column(db.DateTime, nullable=True)
    purchased_at = db.Column(db.DateTime, nullable=True)
    notify_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=db.func.now())

    incentive = db.relationship('Incentive', backref='gift_records')
    user = db.relationship('User', backref='gift_records')
    gift_item = db.relationship('GiftItem', backref='gift_records')
