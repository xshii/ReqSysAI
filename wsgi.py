import os
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
    server = cfg.get('server', {})
    app.run(
        host=os.getenv('FLASK_HOST', server.get('host', '127.0.0.1')),
        port=int(os.getenv('FLASK_PORT', server.get('port', 5001))),
        debug=True,
    )
