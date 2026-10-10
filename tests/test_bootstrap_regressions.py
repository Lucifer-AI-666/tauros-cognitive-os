
import pytest
from dotenv import dotenv_values

from tauros.bootstrap import init_environment
from tauros.gmail_auth import GmailAuthConfig
from tauros.security import is_weak_token
from tauros.settings import Settings


@pytest.mark.parametrize('old_token', ['', 'change-me-now', 'short'])
def test_init_repairs_template_token_and_allowlist(tmp_path, old_token):
    env = tmp_path / '.env'
    env.write_text(f'TAUROS_API_TOKEN={old_token}\nTAUROS_OWNER=Owner\nTAUROS_WORKSPACE_ALLOWLIST=\nCUSTOM=value\n')
    init_environment(tmp_path, owner='Tester', allowlist=str(tmp_path / 'workspace'))
    config = dotenv_values(env)
    assert not is_weak_token(config['TAUROS_API_TOKEN'])
    assert config['TAUROS_OWNER'] == 'Tester'
    assert config['TAUROS_WORKSPACE_ALLOWLIST'] == str(tmp_path / 'workspace')
    assert config['CUSTOM'] == 'value'


def test_init_preserves_existing_token_and_permissions(tmp_path):
    first = init_environment(tmp_path, owner='First', allowlist='/original')
    second = init_environment(tmp_path, owner='Second', allowlist='/replacement')
    config = dotenv_values(tmp_path / '.env')
    assert first['api_token'] == second['api_token']
    assert config['TAUROS_OWNER'] == 'First'
    assert config['TAUROS_WORKSPACE_ALLOWLIST'] == '/original'
    rotated = init_environment(tmp_path, force_token=True)
    assert rotated['api_token'] != first['api_token']


def test_auth_shortcuts_require_explicit_opt_in():
    settings = Settings(_env_file=None)
    assert settings.otp_debug is False
    assert settings.local_click_login is False
    assert GmailAuthConfig().otp_debug is False
