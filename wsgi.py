import os
import time

# Only set TZ if not already configured by the system
# (avoid mismatch when system clock is already in the desired timezone)
if os.environ.get('FORCE_TZ'):
    os.environ['TZ'] = os.environ['FORCE_TZ']
    if hasattr(time, 'tzset'):
        time.tzset()

import yaml

from app import create_app

app = create_app()

if __name__ == '__main__':
    # Read from config.local.yml > config.yml > defaults
    cfg = {}
    for f in ['config.yml', 'config.local.yml']:
        if os.path.exists(f):
            with open(f, encoding='utf-8') as fp:
                cfg.update(yaml.safe_load(fp) or {})
    app_cfg = cfg.get('app', {})
    app.run(
        host=os.getenv('FLASK_HOST', app_cfg.get('host', '0.0.0.0')),  # noqa: S104
        port=int(os.getenv('FLASK_PORT', app_cfg.get('port', 5001))),
        debug=True,
    )
