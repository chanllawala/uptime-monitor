import requests
import responses

from app.checker import perform_check

URL = "https://example.com/"


@responses.activate
def test_expected_status_is_up():
    responses.add(responses.GET, URL, status=200, body="ok")
    result = perform_check(URL)
    assert result.is_up is True
    assert result.status_code == 200
    assert result.error is None


@responses.activate
def test_unexpected_status_is_down_but_records_the_code():
    responses.add(responses.GET, URL, status=503, body="nope")
    result = perform_check(URL)
    assert result.is_up is False
    assert result.status_code == 503
    assert "expected 200" in result.error


@responses.activate
def test_non_200_expectation_can_be_healthy():
    """A monitor watching a redirect or an auth wall may expect something else."""
    responses.add(responses.GET, URL, status=301)
    result = perform_check(URL, expected_status=301)
    assert result.is_up is True


@responses.activate
def test_connection_error_is_down_with_no_status_code():
    responses.add(responses.GET, URL, body=requests.ConnectionError("refused"))
    result = perform_check(URL)
    assert result.is_up is False
    assert result.status_code is None
    assert "connection error" in result.error


@responses.activate
def test_timeout_is_reported_as_a_timeout():
    responses.add(responses.GET, URL, body=requests.Timeout())
    result = perform_check(URL, timeout_seconds=3)
    assert result.is_up is False
    assert "timed out after 3s" in result.error


@responses.activate
def test_head_method_is_honoured():
    responses.add(responses.HEAD, URL, status=200)
    result = perform_check(URL, method="HEAD")
    assert result.is_up is True
    assert responses.calls[0].request.method == "HEAD"
