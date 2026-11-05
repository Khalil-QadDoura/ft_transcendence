"""Isolated Linux/WSL reference backend harness; never touches the team's backend.

Run `python3 scripts/reference-dev.py setup` after installing the README prerequisites.
Override WOZU_REFERENCE_REPO/ENV/VENV/MINIO to reuse a local reference checkout.
"""
import os
import pathlib
import runpy
import secrets
import subprocess
import sys

FRONTEND = pathlib.Path(__file__).resolve().parents[1]
LOCAL = FRONTEND / '.local'
REPO = pathlib.Path(os.environ.get('WOZU_REFERENCE_REPO', str(LOCAL / 'reference'))).resolve()
ENV = pathlib.Path(os.environ.get('WOZU_REFERENCE_ENV', str(LOCAL / 'reference.env'))).resolve()
VENV = pathlib.Path(os.environ.get('WOZU_REFERENCE_VENV', str(LOCAL / 'venv'))).resolve()
MINIO = pathlib.Path(os.environ.get('WOZU_REFERENCE_MINIO', str(LOCAL / 'bin/minio'))).resolve()
PIN = 'adcee1b90bec967fd2a4fce20bc6564a488db2a6'
API = REPO / 'backend/fastapi'

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def load_env():
    if not ENV.exists():
        raise SystemExit('Run setup first; reference.env does not exist.')
    os.environ.update(dict(line.split('=', 1) for line in ENV.read_text().splitlines() if '=' in line and not line.startswith('#')))
    sys.path.insert(0, str(API))
    os.chdir(API)

def setup():
    LOCAL.mkdir(parents=True, exist_ok=True)
    ENV.parent.mkdir(parents=True, exist_ok=True)
    if not REPO.exists():
        run('git', 'clone', 'https://github.com/byul-byul/ft_transcendence.git', str(REPO))
        run('git', '-C', str(REPO), 'checkout', '-b', 'wozu-web-support', PIN)
    head = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PIN:
        raise SystemExit('Reference checkout differs from the pinned baseline. Use a separate checkout.')
    patch = FRONTEND / 'scripts/reference-web.patch'
    applied = subprocess.run(['git', '-C', str(REPO), 'apply', '--reverse', '--check', '--ignore-space-change', str(patch)], capture_output=True).returncode == 0
    if not applied:
        run('git', '-C', str(REPO), 'apply', '--check', str(patch))
        run('git', '-C', str(REPO), 'apply', str(patch))
    if not (VENV / 'bin/python').exists():
        run(sys.executable, '-m', 'venv', str(VENV))
    run(str(VENV / 'bin/pip'), 'install', '-r', str(API / 'requirements.txt'))
    if not ENV.exists():
        password = secrets.token_hex(24)
        values = {
            'ENV': 'ft', 'DATABASE_URL': f'postgresql+asyncpg://wozu_frontend_dev:{password}@127.0.0.1:5432/wozu_frontend_dev',
            'POSTGRES_PASSWORD': password, 'REDIS_URL': 'redis://127.0.0.1:6389/0',
            'SECRET_KEY': secrets.token_hex(32), 'INTERNAL_API_KEY': secrets.token_hex(32),
            'JWT_ISS': 'wozu-ft', 'JWT_AUD': 'wozu-ft-app',
            'ALLOWED_ORIGINS': 'http://localhost:5173,http://127.0.0.1:5173',
            'PUBLIC_BASE_URL': 'http://localhost:5173/api', 'FRONTEND_BASE_URL': 'http://localhost:5173',
            'MINIO_ENDPOINT': 'localhost:9000', 'MINIO_ROOT_USER': 'wozu_frontend_dev',
            'MINIO_ROOT_PASSWORD': secrets.token_hex(24), 'MINIO_BUCKET': 'intro-videos',
            'MINIO_API_CORS_ALLOW_ORIGIN': 'http://localhost:5173,http://127.0.0.1:5173',
            'MODERATION_FAIL_OPEN': 'false', 'BREVO_API_KEY': '', 'OPENAI_API_KEY': '',
        }
        ENV.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
        ENV.chmod(0o600)
    load_env()
    if 'wozu_frontend_dev' not in os.environ['DATABASE_URL']:
        raise SystemExit('Setup only supports the isolated wozu_frontend_dev database.')
    def psql(sql):
        prefix = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else ['sudo', '-u', 'postgres', '--']
        return subprocess.check_output([*prefix, 'psql', '-tAc', sql], text=True).strip()
    if psql("SELECT 1 FROM pg_roles WHERE rolname='wozu_frontend_dev'") != '1':
        password = os.environ['POSTGRES_PASSWORD'].replace("'", "''")
        psql(f"CREATE ROLE wozu_frontend_dev LOGIN PASSWORD '{password}'")
    if psql("SELECT 1 FROM pg_database WHERE datname='wozu_frontend_dev'") != '1':
        psql('CREATE DATABASE wozu_frontend_dev OWNER wozu_frontend_dev')
    prefix = ['runuser', '-u', 'postgres', '--'] if os.geteuid() == 0 else ['sudo', '-u', 'postgres', '--']
    run(*prefix, 'psql', '-d', 'wozu_frontend_dev', '-c', 'CREATE EXTENSION IF NOT EXISTS postgis')
    run(str(VENV / 'bin/alembic'), 'upgrade', 'head')
    print('Isolated database and pinned reference backend prepared. See README for service commands.')

if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'help'
    if command == 'setup':
        setup()
    elif command in ('api', 'minio', 'seed', 'seed-media', 'check', 'worker', 'redis'):
        if command in ('seed', 'seed-media', 'check') and pathlib.Path(sys.executable).parent != VENV / 'bin':
            os.execv(str(VENV / 'bin/python'), [str(VENV / 'bin/python'), str(pathlib.Path(__file__).resolve()), command])
        load_env()
        if command == 'api':
            os.execv(str(VENV / 'bin/uvicorn'), ['uvicorn', 'app.main_ft:app', '--host', '127.0.0.1', '--port', '8000', '--no-access-log', '--log-level', 'warning'])
        elif command == 'minio':
            storage = LOCAL / 'storage'; storage.mkdir(parents=True, exist_ok=True)
            os.execv(str(MINIO), ['minio', 'server', str(storage), '--address', '127.0.0.1:9000', '--console-address', '127.0.0.1:9001'])
        elif command == 'redis':
            os.execvp('redis-server', ['redis-server', '--port', '6389', '--bind', '127.0.0.1', '--dir', str(LOCAL)])
        elif command == 'worker':
            if not os.environ.get('OPENAI_API_KEY'):
                raise SystemExit('Configure OPENAI_API_KEY first. Uploaded videos stay pending until the moderation worker runs.')
            os.execv(str(VENV / 'bin/celery'), ['celery', '-A', 'app.worker.celery_app:celery_app', 'worker', '--loglevel=warning', '--concurrency=1'])
        else:
            name = {'seed': 'seed-reference.py', 'seed-media': 'seed-media.py', 'check': 'check-reference.py'}[command]
            runpy.run_path(str(FRONTEND / 'scripts' / name), run_name='__main__')
    else:
        print('Commands: setup, redis, minio, api, seed, seed-media, check, worker')
