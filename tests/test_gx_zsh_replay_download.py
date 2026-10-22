import argparse
from contextlib import redirect_stdout
import errno
import hashlib
import http.client
import importlib.util
import io
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/packaging/patches/zsh/focal/reproduce_focal.py'
SPEC = importlib.util.spec_from_file_location('gx_zsh_replay', SCRIPT)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class InterruptedResponse(io.BytesIO):
    def __init__(self, error):
        super().__init__(b'unverified partial content')
        self.error = error
        self.read_count = 0

    def read(self, size=-1):
        self.read_count += 1
        if self.read_count == 2:
            raise self.error
        return super().read(size)


class ReplayDownloadTests(unittest.TestCase):
    name = 'packages/focal--fixture_1_amd64.deb'
    url = 'https://archive.ubuntu.com/ubuntu/pool/fixture_1_amd64.deb'
    payload = b'complete locked package content'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gx-zsh-replay-')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.target = self.work / 'downloads' / self.name
        self.expected = hashlib.sha256(self.payload).hexdigest()
        self.sleep = mock.Mock()
        self.output = io.StringIO()

    def fetch(self, opener, expected=True, **kwargs):
        with redirect_stdout(self.output):
            return replay.fetch(self.name, self.url, self.expected if expected else None,
                                work=self.work, opener=opener, sleep=self.sleep, **kwargs)

    def assert_no_download(self):
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.work / 'downloads').rglob('*.part')), [])

    def assert_failed_once(self, opener):
        self.assertEqual(opener.call_count, 1)
        self.sleep.assert_not_called()
        self.assert_no_download()
        self.assertIn('attempt=1/3', self.output.getvalue())
        self.assertIn('DOWNLOAD_FAILED', self.output.getvalue())

    def test_handshake_timeout_then_success(self):
        timeout = urllib.error.URLError(TimeoutError('The handshake operation timed out'))
        response = io.BytesIO(self.payload)
        opener = mock.Mock(side_effect=[timeout, response])
        self.assertEqual(self.fetch(opener), self.target)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(opener.call_args_list, [mock.call(self.url, timeout=90)] * 2)
        self.sleep.assert_called_once_with(1)
        self.assertTrue(response.closed)
        self.assertEqual(list(self.target.parent.glob('*.part')), [])
        log = self.output.getvalue()
        self.assertIn(self.name, log)
        self.assertIn(self.url, log)
        self.assertIn('attempt=1/3', log)
        self.assertIn('attempt=2/3', log)
        self.assertIn('handshake operation timed out', log)

    def test_timeouts_stop_after_three_attempts(self):
        errors = [urllib.error.URLError(TimeoutError(f'timeout {index}')) for index in range(3)]
        opener = mock.Mock(side_effect=errors)
        with self.assertRaises(urllib.error.URLError) as failure:
            self.fetch(opener)
        self.assertIs(failure.exception, errors[-1])
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [mock.call(1), mock.call(2)])
        self.assert_no_download()
        self.assertEqual(self.output.getvalue().count('DOWNLOAD_FAILED'), 3)
        self.assertIn('attempt=3/3', self.output.getvalue())

    def test_partial_read_failure_is_discarded_before_fresh_attempt(self):
        for error in [ConnectionResetError('connection reset'), TimeoutError('read timeout'),
                      http.client.IncompleteRead(b'partial', 10)]:
            with self.subTest(error=type(error).__name__):
                self.target.unlink(missing_ok=True)
                self.sleep.reset_mock()
                interrupted = InterruptedResponse(error)
                complete = io.BytesIO(self.payload)
                paths = []

                def open_response(url, timeout):
                    self.assertFalse(self.target.exists())
                    current = list(self.target.parent.glob('*.part'))
                    self.assertEqual(len(current), 1)
                    for previous in paths:
                        self.assertFalse(previous.exists())
                    paths.extend(current)
                    return interrupted if len(paths) == 1 else complete

                opener = mock.Mock(side_effect=open_response)
                self.fetch(opener)
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(len(set(paths)), 2)
                self.assertEqual(self.target.read_bytes(), self.payload)
                self.assertTrue(interrupted.closed)
                self.assertTrue(complete.closed)
                self.assertEqual(list(self.target.parent.glob('*.part')), [])
                self.sleep.assert_called_once_with(1)

    def test_checksum_failure_is_not_retried_or_published(self):
        opener = mock.Mock(return_value=io.BytesIO(b'wrong package'))
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.fetch(opener)
        self.assert_failed_once(opener)

    def test_existing_download_is_preserved_when_new_checksum_fails(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.payload)
        opener = mock.Mock(return_value=io.BytesIO(b'wrong replacement'))
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.fetch(opener)
        self.assertEqual(opener.call_count, 1)
        self.sleep.assert_not_called()
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(list(self.target.parent.glob('*.part')), [])

    def test_transient_http_statuses_can_retry(self):
        for status in [408, 429, 500, 502, 503, 504]:
            with self.subTest(status=status):
                self.target.unlink(missing_ok=True)
                self.sleep.reset_mock()
                error = urllib.error.HTTPError(self.url, status, 'temporary failure', {}, None)
                opener = mock.Mock(side_effect=[error, io.BytesIO(self.payload)])
                self.fetch(opener)
                self.assertEqual(opener.call_count, 2)
                self.sleep.assert_called_once_with(1)
                self.assertEqual(self.target.read_bytes(), self.payload)

    def test_permanent_http_statuses_are_not_retried(self):
        for status in [400, 401, 403, 404, 410, 501, 505]:
            with self.subTest(status=status):
                error = urllib.error.HTTPError(self.url, status, 'permanent failure', {}, None)
                opener = mock.Mock(side_effect=error)
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    self.fetch(opener)
                self.assertIs(failure.exception, error)
                self.assert_failed_once(opener)

    def test_certificate_errors_are_not_retried(self):
        certificate = ssl.SSLCertVerificationError(1, 'certificate verify failed')
        for error in [certificate, urllib.error.URLError(certificate),
                      ssl.SSLError(1, 'unclassified TLS failure')]:
            with self.subTest(error=repr(error)):
                opener = mock.Mock(side_effect=error)
                with self.assertRaises(type(error)) as failure:
                    self.fetch(opener)
                self.assertIs(failure.exception, error)
                self.assert_failed_once(opener)

    def test_unclassified_network_errors_are_not_retried(self):
        for error in [urllib.error.URLError('unknown failure'),
                      urllib.error.URLError(OSError('unclassified OS error'))]:
            with self.subTest(error=repr(error)):
                opener = mock.Mock(side_effect=error)
                with self.assertRaises(urllib.error.URLError):
                    self.fetch(opener)
                self.assert_failed_once(opener)

    def test_temporary_file_permission_failure_is_not_retried(self):
        opener = mock.Mock()
        with mock.patch.object(replay.tempfile, 'NamedTemporaryFile',
                               side_effect=PermissionError('file permission denied')):
            with self.assertRaises(PermissionError):
                self.fetch(opener)
        opener.assert_not_called()
        self.sleep.assert_not_called()
        self.assert_no_download()
        self.assertIn('file permission denied', self.output.getvalue())

    def test_disk_write_errors_are_not_retried_even_if_typed_as_timeout(self):
        create_file = tempfile.NamedTemporaryFile
        for error in [OSError(errno.ENOSPC, 'disk full'), PermissionError('write denied'),
                      TimeoutError('disk write timed out')]:
            with self.subTest(error=repr(error)):
                def failing_writer(*args, **kwargs):
                    output = create_file(*args, **kwargs)
                    wrapper = mock.MagicMock(wraps=output)
                    wrapper.name = output.name
                    wrapper.__enter__.return_value = wrapper
                    wrapper.__exit__.side_effect = output.__exit__
                    wrapper.write.side_effect = error
                    return wrapper

                opener = mock.Mock(return_value=io.BytesIO(self.payload))
                with mock.patch.object(replay.tempfile, 'NamedTemporaryFile', failing_writer):
                    with self.assertRaises(type(error)) as failure:
                        self.fetch(opener)
                self.assertIs(failure.exception, error)
                self.assert_failed_once(opener)

    def test_cache_hit_verifies_hash_without_network(self):
        cache = self.work / 'cache'
        source = cache / self.name
        source.parent.mkdir(parents=True)
        source.write_bytes(self.payload)
        opener = mock.Mock(side_effect=AssertionError('network must not be used'))
        self.fetch(opener, cache=cache)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(source.read_bytes(), self.payload)
        opener.assert_not_called()
        self.sleep.assert_not_called()

    def test_corrupt_cache_is_rejected_without_network(self):
        cache = self.work / 'cache'
        source = cache / self.name
        source.parent.mkdir(parents=True)
        source.write_bytes(b'corrupt cache')
        opener = mock.Mock(side_effect=AssertionError('network must not be used'))
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            self.fetch(opener, cache=cache)
        opener.assert_not_called()
        self.sleep.assert_not_called()
        self.assert_no_download()
        self.assertEqual(source.read_bytes(), b'corrupt cache')

    def test_signature_without_expected_hash_keeps_original_semantics(self):
        opener = mock.Mock(return_value=io.BytesIO(self.payload))
        with mock.patch.object(replay, 'sha', side_effect=AssertionError('no expected hash')):
            self.fetch(opener, expected=False)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(opener.call_count, 1)
        self.sleep.assert_not_called()

    def test_import_does_not_parse_arguments_create_directories_or_change_environment(self):
        environment = os.environ.copy()
        spec = importlib.util.spec_from_file_location('gx_zsh_replay_import_check', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(argparse, 'ArgumentParser') as parser, \
                mock.patch.object(Path, 'mkdir') as mkdir, \
                mock.patch.object(subprocess, 'run') as run, \
                mock.patch.object(urllib.request, 'urlopen') as urlopen, \
                mock.patch.object(sys, 'argv', ['reproduce_focal.py', '--work', str(self.work / 'unused')]):
            spec.loader.exec_module(module)
        parser.assert_not_called()
        mkdir.assert_not_called()
        run.assert_not_called()
        urlopen.assert_not_called()
        self.assertEqual(os.environ, environment)
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
