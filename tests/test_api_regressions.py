import os
import subprocess
import sys


def test_api_auth_defaults_and_put_preflight(tmp_path):
    env = os.environ.copy()
    env.update(TAUROS_DATABASE_PATH=str(tmp_path / 'api.db'),
               TAUROS_API_TOKEN='test-api-token-Alpha1234567890!beta',
               TAUROS_PROVIDER='ollama', TAUROS_SKIP_TOKEN_CHECK='false',
               TAUROS_LOCAL_CLICK_LOGIN='false', TAUROS_OTP_DEBUG='false')
    script = '''
from fastapi.testclient import TestClient
from tauros.api import app
with TestClient(app, client=("127.0.0.1", 12345)) as client:
    assert client.get("/health").json()["ok"] is True
    assert client.get("/").status_code == 200
    assert client.get("/console").status_code == 200
    assert client.post("/auth/local").status_code == 403
    response = client.options("/brain", headers={
        "Origin": "http://localhost:8000",
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type"})
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]
    response = client.post("/auth/gmail/request-code", json={"email":"test@gmail.com"})
    assert response.status_code == 200
    assert "debug_code" not in response.json()
'''
    subprocess.run([sys.executable, '-c', script], env=env, check=True,
                   capture_output=True, text=True, timeout=30)
