"""Create local secrets once. Never print or overwrite them."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
path = root / '.work/generator-implementation/simulation.env'
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    print('Existing private environment retained.')
else:
    values = {name: secrets.token_hex(32) for name in [
        'AUTH_SECRET', 'PG_PASSWORD', 'BROKER_PASSWORD', 'GENERATOR_TOKEN', 'MINIO_PASSWORD']}
    values.update(FRONTEND_PORT='8095', BACKEND_PORT='8094', POSTGRES_PORT='5545', STORAGE_BACKEND='local')
    path.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    print('Private simulation environment created in ignored .work/.')
