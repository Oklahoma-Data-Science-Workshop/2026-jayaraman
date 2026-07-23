import uuid
from datetime import datetime
from app import db


class TripSession(db.Model):
    __tablename__ = "trip_sessions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mode = db.Column(db.String(20), default="plan")  # 'plan' or 'discover'
    title = db.Column(db.String(200), nullable=True)
    messages_json = db.Column(db.Text, default="[]")
    trip_data_json = db.Column(db.Text, nullable=True)
    flights_json = db.Column(db.Text, nullable=True)
    result_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="chatting")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TripSession {self.id} {self.title}>"
