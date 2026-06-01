import pytest
import requests
from requests import Response

from dvc_studio_client.auth import (
    AuthorizationExpiredError,
    InvalidScopesError,
    check_token_authentication,
    get_access_token,
    start_device_login,
)

MOCK_RESPONSE = {
    "verification_uri": "https://studio.example.com/auth/device-login",
    "user_code": "MOCKCODE",
    "device_code": "random-value",
    "token_uri": "https://studio.example.com/api/device-login/token",
    "token_name": "random-name",
}


@pytest.fixture
def mock_response(mocker):
    def _mock_response(status_code, json):
        response = Response()
        response.status_code = status_code
        mocker.patch.object(response, "json", return_value=json)
        return response

    return _mock_response


@pytest.fixture
def mock_post(mocker, mock_response):
    def _mock_post(method, side_effect):
        return mocker.patch(
            method,
            side_effect=[mock_response(status, resp) for status, resp in side_effect],
        )

    return _mock_post


def test_auth_expired(mocker, mock_post):
    mocker.patch("webbrowser.open")

    mock_login_post = mock_post("requests.post", [(200, MOCK_RESPONSE)])

    mock_poll_post = mock_post(
        "requests.Session.post",
        [(400, {"detail": "authorization_expired"})],
    )

    with pytest.raises(AuthorizationExpiredError):
        get_access_token(client_name="client", hostname="https://studio.example.com")

    assert mock_login_post.call_args == mocker.call(
        url="https://studio.example.com/api/device-login",
        json={
            "client_name": "client",
        },
        headers={"Content-type": "application/json"},
        timeout=5,
    )

    assert mock_poll_post.call_args_list == [
        mocker.call(
            "https://studio.example.com/api/device-login/token",
            json={"code": "random-value"},
            timeout=5,
            allow_redirects=False,
        ),
    ]


def test_auth_success(mocker, mock_post, capfd):
    mocker.patch("time.sleep")
    mocker.patch("webbrowser.open")
    mock_login_post = mock_post("requests.post", [(200, MOCK_RESPONSE)])
    mock_poll_post = mock_post(
        "requests.Session.post",
        [
            (400, {"detail": "authorization_pending"}),
            (200, {"access_token": "isat_access_token"}),
        ],
    )

    assert get_access_token(
        hostname="https://example.com",
        scopes="experiments",
        token_name="random-name",
    ) == ("random-name", "isat_access_token")

    assert mock_login_post.call_args_list == [
        mocker.call(
            url="https://example.com/api/device-login",
            json={
                "client_name": "client",
                "token_name": "random-name",
                "scopes": ["experiments"],
            },
            headers={"Content-type": "application/json"},
            timeout=5,
        ),
    ]
    assert mock_poll_post.call_count == 2
    assert mock_poll_post.call_args_list == [
        mocker.call(
            "https://studio.example.com/api/device-login/token",
            json={"code": "random-value"},
            timeout=5,
            allow_redirects=False,
        ),
        mocker.call(
            "https://studio.example.com/api/device-login/token",
            json={"code": "random-value"},
            timeout=5,
            allow_redirects=False,
        ),
    ]
    out, err = capfd.readouterr()
    assert out == (
        f"Opening link for login at {MOCK_RESPONSE['verification_uri']}?code=MOCKCODE\n"
        "\nOnce you've logged in, return here and you'll be ready to start the "
        "experiments.\n"
    )
    assert not err


def test_webbrowser_open_fails(mocker, mock_post, capfd):
    mock_open = mocker.patch("webbrowser.open")
    mock_open.return_value = False

    mocker.patch("time.sleep")
    mock_post("requests.post", [(200, MOCK_RESPONSE)])
    mock_post(
        "requests.Session.post",
        [
            (400, {"detail": "authorization_pending"}),
            (200, {"access_token": "isat_access_token"}),
        ],
    )

    assert get_access_token(
        hostname="https://example.com",
        scopes="experiments",
        token_name="random-name",
    ) == ("random-name", "isat_access_token")
    out, err = capfd.readouterr()
    assert out == (
        f"Opening link for login at {MOCK_RESPONSE['verification_uri']}?code=MOCKCODE\n"
        "\nOnce you've logged in, return here and you'll be ready to start the "
        "experiments.\n"
    )
    assert (
        err == "\nFailed to open a web browser. "
        "Open the above url to continue in your web browser.\n"
    )


@pytest.mark.parametrize("kwargs", [{"use_device_code": True}, {"open_browser": False}])
def test_start_no_open(mocker, mock_post, capfd, kwargs):
    mock_open = mocker.patch("webbrowser.open")

    mocker.patch("time.sleep")
    mock_post("requests.post", [(200, MOCK_RESPONSE)])
    mock_post(
        "requests.Session.post",
        [
            (400, {"detail": "authorization_pending"}),
            (200, {"access_token": "isat_access_token"}),
        ],
    )

    assert get_access_token(
        hostname="https://example.com",
        scopes="experiments",
        token_name="random-name",
        **kwargs,
    ) == ("random-name", "isat_access_token")
    mock_open.assert_not_called()
    out, err = capfd.readouterr()
    assert out == (
        "Open this url to continue in your web browser: "
        f"{MOCK_RESPONSE['verification_uri']}?code=MOCKCODE\n"
        "\nOnce you've logged in, return here and you'll be ready to start the "
        "experiments.\n"
    )
    assert not err


def test_start_device_login(capfd, mocker, mock_post):
    example_response = {
        "device_code": "random-device-code",
        "user_code": "MOCKCODE",
        "verification_uri": "http://example.com/verify",
        "token_uri": "http://example.com/token",
        "token_name": "token_name",
        "expires_in": 1500,
    }
    mock_post = mock_post("requests.post", [(200, example_response)])

    response = start_device_login(
        base_url="https://example.com",
        client_name="dvc",
        token_name="token_name",
        scopes=["EXPERIMENTS"],
    )

    assert mock_post.called
    assert mock_post.call_args == mocker.call(
        url="https://example.com/api/device-login",
        json={
            "client_name": "dvc",
            "token_name": "token_name",
            "scopes": ["EXPERIMENTS"],
        },
        headers={"Content-type": "application/json"},
        timeout=5,
    )
    assert response == example_response


def test_start_device_login_invalid_scopes(mock_post):
    with pytest.raises(InvalidScopesError):
        start_device_login(
            base_url="https://example.com",
            client_name="dvc",
            token_name="token_name",
            scopes=["INVALID!"],
        )


def test_check_token_authentication_expired(mocker, mock_post):
    mocker.patch("time.sleep")
    mock_post = mock_post(
        "requests.Session.post",
        [
            (400, {"detail": "authorization_pending"}),
            (400, {"detail": "authorization_expired"}),
        ],
    )

    with pytest.raises(AuthorizationExpiredError):
        check_token_authentication(
            uri="https://example.com/token_uri",
            device_code="random_device_code",
        )

    assert mock_post.call_count == 2
    assert mock_post.call_args == mocker.call(
        "https://example.com/token_uri",
        json={"code": "random_device_code"},
        timeout=5,
        allow_redirects=False,
    )


def test_check_token_authentication_error(mocker, mock_post):
    mocker.patch("time.sleep")
    mock_post = mock_post(
        "requests.Session.post",
        [
            (400, {"detail": "authorization_pending"}),
            (500, {"detail": "unexpected_error"}),
        ],
    )

    with pytest.raises(requests.RequestException):
        check_token_authentication(
            uri="https://example.com/token_uri",
            device_code="random_device_code",
        )

    assert mock_post.call_count == 2
    assert mock_post.call_args == mocker.call(
        "https://example.com/token_uri",
        json={"code": "random_device_code"},
        timeout=5,
        allow_redirects=False,
    )


def test_check_token_authentication_success(mocker, mock_post):
    mocker.patch("time.sleep")
    mock_post_call = mock_post(
        "requests.Session.post",
        [
            (400, {"detail": "authorization_pending"}),
            (400, {"detail": "authorization_pending"}),
            (200, {"access_token": "isat_token"}),
        ],
    )

    assert (
        check_token_authentication(
            uri="https://example.com/token_uri",
            device_code="random_device_code",
        )
        == "isat_token"
    )

    assert mock_post_call.call_count == 3
    assert mock_post_call.call_args == mocker.call(
        "https://example.com/token_uri",
        json={"code": "random_device_code"},
        timeout=5,
        allow_redirects=False,
    )


def test_start_device_login_with_new_parameters(mock_post, mocker):
    """Test start_device_login with team scoping and expiration parameters"""
    mock_post_obj = mock_post(
        "requests.post",
        [(200, MOCK_RESPONSE), (200, MOCK_RESPONSE)],
    )

    start_device_login(client_name="test", team_names=["team1"], expires_in_days=30)
    start_device_login(client_name="test", all_teams=False, team_names=["team1"])

    assert mock_post_obj.call_args_list == [
        mocker.call(
            url="https://studio.datachain.ai/api/device-login",
            json={
                "client_name": "test",
                "team_names": ["team1"],
                "expires_in_days": 30,
            },
            headers={"Content-type": "application/json"},
            timeout=5,
        ),
        mocker.call(
            url="https://studio.datachain.ai/api/device-login",
            json={"client_name": "test", "all_teams": False, "team_names": ["team1"]},
            headers={"Content-type": "application/json"},
            timeout=5,
        ),
    ]


def test_get_access_token_parameter_passthrough(mocker, mock_post):
    """Test get_access_token passes new parameters to start_device_login"""
    mocker.patch("webbrowser.open")
    mocker.patch("time.sleep")
    mock_login_post = mock_post("requests.post", [(200, MOCK_RESPONSE)])
    mock_post("requests.Session.post", [(200, {"access_token": "token"})])

    get_access_token(
        hostname="https://example.com", team_names=["team1"], expires_in_days=7
    )

    assert mock_login_post.call_args == mocker.call(
        url="https://example.com/api/device-login",
        json={"client_name": "client", "team_names": ["team1"], "expires_in_days": 7},
        headers={"Content-type": "application/json"},
        timeout=5,
    )


def test_backwards_compatibility(mocker, mock_post):
    """Test existing calls work unchanged"""
    mocker.patch("webbrowser.open")
    mocker.patch("time.sleep")
    mock_login_post = mock_post("requests.post", [(200, MOCK_RESPONSE)])
    mock_post("requests.Session.post", [(200, {"access_token": "token"})])

    token_name, access_token = get_access_token(
        hostname="https://example.com", scopes="experiments"
    )

    assert (token_name, access_token) == ("random-name", "token")
    assert mock_login_post.call_args == mocker.call(
        url="https://example.com/api/device-login",
        json={"client_name": "client", "scopes": ["experiments"]},
        headers={"Content-type": "application/json"},
        timeout=5,
    )


def test_start_device_login_validation_all_teams_false_without_team_names():
    """Test validation error when all_teams=False but team_names not provided"""
    with pytest.raises(
        ValueError, match="team_names must be specified when all_teams is False"
    ):
        start_device_login(client_name="test", all_teams=False)


def test_start_device_login_validation_all_teams_false_with_team_names(mock_post):
    """Test that all_teams=False works when team_names is provided"""
    mock_post("requests.post", [(200, MOCK_RESPONSE)])

    # This should work without raising an error
    result = start_device_login(
        client_name="test", all_teams=False, team_names=["team1"]
    )
    assert result == MOCK_RESPONSE
