import os


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL', 'postgresql://reqsys:reqsys@localhost:5432/reqsysai'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = 8 * 3600  # 8 hours

    # LDAP (optional - disabled if LDAP_HOST is empty)
    LDAP_HOST = os.getenv('LDAP_HOST', '')
    LDAP_PORT = int(os.getenv('LDAP_PORT', 389))
    LDAP_BASE_DN = os.getenv('LDAP_BASE_DN', 'dc=company,dc=com')
    LDAP_USER_DN = os.getenv('LDAP_USER_DN', 'ou=users')
    LDAP_USER_SEARCH_SCOPE = 'SUBTREE'
    LDAP_USER_LOGIN_ATTR = 'uid'

    # Ollama
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5')

    # Mail
    MAIL_SERVER = os.getenv('MAIL_SERVER', '')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 25))
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@company.com')


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestConfig,
}
