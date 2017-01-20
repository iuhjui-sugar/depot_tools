# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Google OAuth2 related functions."""

import BaseHTTPServer
import collections
import datetime
import functools
import hashlib
import json
import logging
import optparse
import os
import socket
import sys
import threading
import urllib
import urlparse
import webbrowser

from third_party import httplib2
from third_party.oauth2client import client
from third_party.oauth2client import multistore_file


# depot_tools/.
DEPOT_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))


# Google OAuth2 clients always have a secret, even if the client is an installed
# application/utility such as this. Of course, in such cases the "secret" is
# actually publicly known; security depends entirely on the secrecy of refresh
# tokens, which effectively become bearer tokens. An attacker can impersonate
# service's identity in OAuth2 flow. But that's generally fine as long as a list
# of allowed redirect_uri's associated with client_id is limited to 'localhost'
# or 'urn:ietf:wg:oauth:2.0:oob'. In that case attacker needs some process
# running on user's machine to successfully complete the flow and grab refresh
# token. When you have a malicious code running on your machine, you're screwed
# anyway.
# This particular set is managed by API Console project "chrome-infra-auth".
OAUTH_CLIENT_ID = (
    '446450136466-2hr92jrq8e6i4tnsa56b52vacp7t3936.apps.googleusercontent.com')
OAUTH_CLIENT_SECRET = 'uBfbay2KCy9t4QveJ-dOqHtp'

# List of space separated OAuth scopes for generated tokens. GAE apps usually
# use userinfo.email scope for authentication.
OAUTH_SCOPES = 'https://www.googleapis.com/auth/userinfo.email'

# Additional OAuth scopes.
ADDITIONAL_SCOPES = {
  'code.google.com': 'https://www.googleapis.com/auth/projecthosting',
}

# Path to a file with cached OAuth2 credentials used by default relative to the
# home dir (see _get_token_cache_path). It should be a safe location accessible
# only to a current user: knowing content of this file is roughly equivalent to
# knowing account password. Single file can hold multiple independent tokens
# identified by token_cache_key (see Authenticator).
OAUTH_TOKENS_CACHE = '.depot_tools_oauth2_tokens'


# Authentication configuration extracted from command line options.
# See doc string for 'make_auth_config' for meaning of fields.
AuthConfig = collections.namedtuple('AuthConfig', [
    'use_oauth2', # deprecated, will be always True
    'save_cookies', # deprecated, will be removed
    'use_local_webserver',
    'webserver_port',
    'refresh_token_json',
    'service_account_json',
])


# OAuth access token with its expiration time (UTC datetime or None if unknown).
AccessToken = collections.namedtuple('AccessToken', [
    'token',
    'expires_at',
])


# Refresh token passed via --auth-refresh-token-json.
RefreshToken = collections.namedtuple('RefreshToken', [
    'client_id',
    'client_secret',
    'refresh_token',
])


class AuthenticationError(Exception):
  """Raised on errors related to authentication."""


class LoginRequiredError(AuthenticationError):
  """Interaction with the user is required to authenticate."""

  def __init__(self, token_cache_key):
    # HACK(vadimsh): It is assumed here that the token cache key is a hostname.
    msg = (
        'You are not logged in. Please login first by running:\n'
        '  depot-tools-auth login %s' % token_cache_key)
    super(LoginRequiredError, self).__init__(msg)


def make_auth_config(
    use_oauth2=None,
    save_cookies=None,
    use_local_webserver=None,
    webserver_port=None,
    refresh_token_json=None,
    service_account_json=None):
  """Returns new instance of AuthConfig.

  If some config option is None, it will be set to a reasonable default value.
  This function also acts as an authoritative place for default values of
  corresponding command line options.
  """
  default = lambda val, d: val if val is not None else d
  return AuthConfig(
      default(use_oauth2, True),
      default(save_cookies, True),
      default(use_local_webserver, not _is_headless()),
      default(webserver_port, 8090),
      default(refresh_token_json, ''),
      default(service_account_json, ''))


def add_auth_options(parser, default_config=None):
  """Appends OAuth related options to OptionParser."""
  default_config = default_config or make_auth_config()
  parser.auth_group = optparse.OptionGroup(parser, 'Auth options')
  parser.add_option_group(parser.auth_group)

  # OAuth2 vs password switch.
  auth_default = 'use OAuth2' if default_config.use_oauth2 else 'use password'
  parser.auth_group.add_option(
      '--oauth2',
      action='store_true',
      dest='use_oauth2',
      default=default_config.use_oauth2,
      help='Use OAuth 2.0 instead of a password. [default: %s]' % auth_default)
  parser.auth_group.add_option(
      '--no-oauth2',
      action='store_false',
      dest='use_oauth2',
      default=default_config.use_oauth2,
      help='Use password instead of OAuth 2.0. [default: %s]' % auth_default)

  # Password related options, deprecated.
  parser.auth_group.add_option(
      '--no-cookies',
      action='store_false',
      dest='save_cookies',
      default=default_config.save_cookies,
      help='Do not save authentication cookies to local disk.')

  # OAuth2 related options.
  parser.auth_group.add_option(
      '--auth-no-local-webserver',
      action='store_false',
      dest='use_local_webserver',
      default=default_config.use_local_webserver,
      help='Do not run a local web server when performing OAuth2 login flow.')
  parser.auth_group.add_option(
      '--auth-host-port',
      type=int,
      default=default_config.webserver_port,
      help='Port a local web server should listen on. Used only if '
          '--auth-no-local-webserver is not set. [default: %default]')
  parser.auth_group.add_option(
      '--auth-refresh-token-json',
      default=default_config.refresh_token_json,
      help='Path to a JSON file with role account refresh token to use.')
  parser.auth_group.add_option(
      '--auth-service-account-json',
      default=default_config.service_account_json,
      help='Path to a JSON file with service account information.')

def extract_auth_config_from_options(options):
  """Given OptionParser parsed options, extracts AuthConfig from it.

  OptionParser should be populated with auth options by 'add_auth_options'.
  """
  return make_auth_config(
      use_oauth2=options.use_oauth2,
      save_cookies=False if options.use_oauth2 else options.save_cookies,
      use_local_webserver=options.use_local_webserver,
      webserver_port=options.auth_host_port,
      refresh_token_json=options.auth_refresh_token_json,
      service_account_json=options.auth_service_account_json)


def auth_config_to_command_options(auth_config):
  """AuthConfig -> list of strings with command line options.

  Omits options that are set to default values.
  """
  if not auth_config:
    return []
  defaults = make_auth_config()
  opts = []
  if auth_config.use_oauth2 != defaults.use_oauth2:
    opts.append('--oauth2' if auth_config.use_oauth2 else '--no-oauth2')
  if auth_config.save_cookies != auth_config.save_cookies:
    if not auth_config.save_cookies:
      opts.append('--no-cookies')
  if auth_config.use_local_webserver != defaults.use_local_webserver:
    if not auth_config.use_local_webserver:
      opts.append('--auth-no-local-webserver')
  if auth_config.webserver_port != defaults.webserver_port:
    opts.extend(['--auth-host-port', str(auth_config.webserver_port)])
  if auth_config.refresh_token_json != defaults.refresh_token_json:
    opts.extend([
        '--auth-refresh-token-json', str(auth_config.refresh_token_json)])
  if auth_config.service_account_json != defaults.service_account_json:
    opts.extend([
        '--auth-service-account-json', str(auth_config.service_account_json)])
  return opts


def get_authenticator_for_host(hostname, config):
  """Returns Authenticator instance to access given host.

  Args:
    hostname: a naked hostname or http(s)://<hostname>[/] URL. Used to derive
        a cache key for token cache.
    config: AuthConfig instance.

  Returns:
    Authenticator object.
  """
  hostname = hostname.lower().rstrip('/')
  # Append some scheme, otherwise urlparse puts hostname into parsed.path.
  if '://' not in hostname:
    hostname = 'https://' + hostname
  scopes = OAUTH_SCOPES
  parsed = urlparse.urlparse(hostname)
  if parsed.netloc in ADDITIONAL_SCOPES:
    scopes = "%s %s" % (scopes, ADDITIONAL_SCOPES[parsed.netloc])

  if parsed.path or parsed.params or parsed.query or parsed.fragment:
    raise AuthenticationError(
        'Expecting a hostname or root host URL, got %s instead' % hostname)
  return Authenticator(parsed.netloc, config, scopes)


class Authenticator(object):
  """Object that knows how to refresh access tokens when needed.

  Args:
    token_cache_key: string key of a section of the token cache file to use
        to keep the tokens. See hostname_to_token_cache_key.
    config: AuthConfig object that holds authentication configuration.
  """

  def __init__(self, token_cache_key, config, scopes):
    assert isinstance(config, AuthConfig)
    assert config.use_oauth2
    self._access_token = None
    self._config = config
    self._lock = threading.Lock()
    self._token_cache_key = token_cache_key
    self._external_token = None
    self._scopes = scopes
    self._service_account_data = None
    if config.refresh_token_json:
      self._external_token = _read_refresh_token_json(config.refresh_token_json)
    if config.service_account_json:
      with open(config.service_account_json, 'r') as service_account_file:
        self._service_account_data = service_account_file.read()
    logging.debug('Using auth config %r', config)

  def login(self):
    """Performs interactive login flow if necessary.

    Raises:
      AuthenticationError on error or if interrupted.
    """
    if self._external_token:
      raise AuthenticationError(
          'Can\'t run login flow when using --auth-refresh-token-json.')
    return self.get_access_token(
        force_refresh=True, allow_user_interaction=True)

  def logout(self):
    """Revokes the refresh token and deletes it from the cache.

    Returns True if had some credentials cached.
    """
    with self._lock:
      self._access_token = None
      storage = self._get_storage()
      credentials = storage.get()
      had_creds = bool(credentials)
      if credentials and credentials.refresh_token and credentials.revoke_uri:
        try:
          credentials.revoke(httplib2.Http())
        except client.TokenRevokeError as e:
          logging.warning('Failed to revoke refresh token: %s', e)
      storage.delete()
    return had_creds

  def has_cached_credentials(self):
    """Returns True if long term credentials (refresh token) are in cache.

    Doesn't make network calls.

    If returns False, get_access_token() later will ask for interactive login by
    raising LoginRequiredError.

    If returns True, most probably get_access_token() won't ask for interactive
    login, though it is not guaranteed, since cached token can be already
    revoked and there's no way to figure this out without actually trying to use
    it.
    """
    with self._lock:
      return bool(self._get_cached_credentials())

  def get_access_token(self, force_refresh=False, allow_user_interaction=False):
    """Returns AccessToken, refreshing it if necessary.

    Args:
      force_refresh: forcefully refresh access token even if it is not expired.
      allow_user_interaction: True to enable blocking for user input if needed.

    Raises:
      AuthenticationError on error or if authentication flow was interrupted.
      LoginRequiredError if user interaction is required, but
          allow_user_interaction is False.
    """
    with self._lock:
      if force_refresh:
        logging.debug('Forcing access token refresh')
        self._access_token = self._create_access_token(allow_user_interaction)
        return self._access_token

      # Load from on-disk cache on a first access.
      if not self._access_token:
        self._access_token = self._load_access_token()

      # Refresh if expired or missing.
      if not self._access_token or _needs_refresh(self._access_token):
        # Maybe some other process already updated it, reload from the cache.
        self._access_token = self._load_access_token()
        # Nope, still expired, need to run the refresh flow.
        if not self._access_token or _needs_refresh(self._access_token):
          self._access_token = self._create_access_token(allow_user_interaction)

      return self._access_token

  def get_token_info(self):
    """Returns a result of /oauth2/v2/tokeninfo call with token info."""
    access_token = self.get_access_token()
    resp, content = httplib2.Http().request(
        uri='https://www.googleapis.com/oauth2/v2/tokeninfo?%s' % (
            urllib.urlencode({'access_token': access_token.token})))
    if resp.status == 200:
      return json.loads(content)
    raise AuthenticationError('Failed to fetch the token info: %r' % content)

  def authorize(self, http):
    """Monkey patches authentication logic of httplib2.Http instance.

    The modified http.request method will add authentication headers to each
    request and will refresh access_tokens when a 401 is received on a
    request.

    Args:
       http: An instance of httplib2.Http.

    Returns:
       A modified instance of http that was passed in.
    """
    # Adapted from oauth2client.OAuth2Credentials.authorize.

    request_orig = http.request

    @functools.wraps(request_orig)
    def new_request(
        uri, method='GET', body=None, headers=None,
        redirections=httplib2.DEFAULT_MAX_REDIRECTS,
        connection_type=None):
      headers = (headers or {}).copy()
      headers['Authorization'] = 'Bearer %s' % self.get_access_token().token
      resp, content = request_orig(
          uri, method, body, headers, redirections, connection_type)
      if resp.status in client.REFRESH_STATUS_CODES:
        logging.info('Refreshing due to a %s', resp.status)
        access_token = self.get_access_token(force_refresh=True)
        headers['Authorization'] = 'Bearer %s' % access_token.token
        return request_orig(
            uri, method, body, headers, redirections, connection_type)
      else:
        return (resp, content)

    http.request = new_request
    return http

  ## Private methods.

  def _get_storage(self):
    """Returns oauth2client.Storage with cached tokens."""
    # Do not mix cache keys for different externally provided tokens.
    if self._external_token:
      token_hash = hashlib.sha1(self._external_token.refresh_token).hexdigest()
      cache_key = '%s:refresh_tok:%s' % (self._token_cache_key, token_hash)
    else:
      cache_key = self._token_cache_key
    path = _get_token_cache_path()
    logging.debug('Using token storage %r (cache key %r)', path, cache_key)
    return multistore_file.get_credential_storage_custom_string_key(
        path, cache_key)

  def _get_cached_credentials(self):
    """Returns oauth2client.Credentials loaded from storage."""
    storage = self._get_storage()
    credentials = storage.get()

    if not credentials:
      logging.debug('No cached token')
    else:
      _log_credentials_info('cached token', credentials)

    # Is using --auth-refresh-token-json?
    if self._external_token:
      # Cached credentials are valid and match external token -> use them. It is
      # important to reuse credentials from the storage because they contain
      # cached access token.
      valid = (
          credentials and not credentials.invalid and
          credentials.refresh_token == self._external_token.refresh_token and
          credentials.client_id == self._external_token.client_id and
          credentials.client_secret == self._external_token.client_secret)
      if valid:
        logging.debug('Cached credentials match external refresh token')
        return credentials
      # Construct new credentials from externally provided refresh token,
      # associate them with cache storage (so that access_token will be placed
      # in the cache later too).
      logging.debug('Putting external refresh token into the cache')
      credentials = client.OAuth2Credentials(
          access_token=None,
          client_id=self._external_token.client_id,
          client_secret=self._external_token.client_secret,
          refresh_token=self._external_token.refresh_token,
          token_expiry=None,
          token_uri='https://accounts.google.com/o/oauth2/token',
          user_agent=None,
          revoke_uri=None)
      credentials.set_store(storage)
      storage.put(credentials)
      return credentials

    if not credentials and self._service_account_data:
      logging.debug('Creating service account JSON from provided JSON')
      credentials = client.Credentials.from_json(
        self._service_account_data)
      credentials.set_store(storage)
      storage.put(credentials)

    # Not using external refresh token -> return whatever is cached.
    return credentials if (credentials and not credentials.invalid) else None

  def _load_access_token(self):
    """Returns cached AccessToken if it is not expired yet."""
    logging.debug('Reloading access token from cache')
    creds = self._get_cached_credentials()
    if not creds or not creds.access_token or creds.access_token_expired:
      logging.debug('Access token is missing or expired')
      return None
    return AccessToken(str(creds.access_token), creds.token_expiry)

  def _create_access_token(self, allow_user_interaction=False):
    """Mints and caches a new access token, launching OAuth2 dance if necessary.

    Uses cached refresh token, if present. In that case user interaction is not
    required and function will finish quietly. Otherwise it will launch 3-legged
    OAuth2 flow, that needs user interaction.

    Args:
      allow_user_interaction: if True, allow interaction with the user (e.g.
          reading standard input, or launching a browser).

    Returns:
      AccessToken.

    Raises:
      AuthenticationError on error or if authentication flow was interrupted.
      LoginRequiredError if user interaction is required, but
          allow_user_interaction is False.
    """
    logging.debug(
        'Making new access token (allow_user_interaction=%r)',
        allow_user_interaction)
    credentials = self._get_cached_credentials()

    # 3-legged flow with (perhaps cached) refresh token.
    refreshed = False
    if credentials and not credentials.invalid:
      try:
        logging.debug('Attempting to refresh access_token')
        credentials.refresh(httplib2.Http())
        _log_credentials_info('refreshed token', credentials)
        refreshed = True
      except client.Error as err:
        logging.warning(
            'OAuth error during access token refresh (%s). '
            'Attempting a full authentication flow.', err)

    # Refresh token is missing or invalid, go through the full flow.
    if not refreshed:
      # Can't refresh externally provided token.
      if self._external_token:
        raise AuthenticationError(
            'Token provided via --auth-refresh-token-json is no longer valid.')
      if not allow_user_interaction:
        logging.debug('Requesting user to login')
        raise LoginRequiredError(self._token_cache_key)
      logging.debug('Launching OAuth browser flow')
      credentials = _run_oauth_dance(self._config, self._scopes)
      _log_credentials_info('new token', credentials)

    logging.info(
        'OAuth access_token refreshed. Expires in %s.',
        credentials.token_expiry - datetime.datetime.utcnow())
    storage = self._get_storage()
    credentials.set_store(storage)
    storage.put(credentials)
    return AccessToken(str(credentials.access_token), credentials.token_expiry)


## Private functions.


def _get_token_cache_path():
  # On non Win just use HOME.
  if sys.platform != 'win32':
    return os.path.join(os.path.expanduser('~'), OAUTH_TOKENS_CACHE)
  # Prefer USERPROFILE over HOME, since HOME is overridden in
  # git-..._bin/cmd/git.cmd to point to depot_tools. depot-tools-auth.py script
  # (and all other scripts) doesn't use this override and thus uses another
  # value for HOME. git.cmd doesn't touch USERPROFILE though, and usually
  # USERPROFILE == HOME on Windows.
  if 'USERPROFILE' in os.environ:
    return os.path.join(os.environ['USERPROFILE'], OAUTH_TOKENS_CACHE)
  return os.path.join(os.path.expanduser('~'), OAUTH_TOKENS_CACHE)


def _is_headless():
  """True if machine doesn't seem to have a display."""
  return sys.platform == 'linux2' and not os.environ.get('DISPLAY')


def _read_refresh_token_json(path):
  """Returns RefreshToken by reading it from the JSON file."""
  try:
    with open(path, 'r') as f:
      data = json.load(f)
      return RefreshToken(
          client_id=str(data.get('client_id', OAUTH_CLIENT_ID)),
          client_secret=str(data.get('client_secret', OAUTH_CLIENT_SECRET)),
          refresh_token=str(data['refresh_token']))
  except (IOError, ValueError) as e:
    raise AuthenticationError(
        'Failed to read refresh token from %s: %s' % (path, e))
  except KeyError as e:
    raise AuthenticationError(
        'Failed to read refresh token from %s: missing key %s' % (path, e))


def _needs_refresh(access_token):
  """True if AccessToken should be refreshed."""
  if access_token.expires_at is not None:
    # Allow 5 min of clock skew between client and backend.
    now = datetime.datetime.utcnow() + datetime.timedelta(seconds=300)
    return now >= access_token.expires_at
  # Token without expiration time never expires.
  return False


def _log_credentials_info(title, credentials):
  """Dumps (non sensitive) part of client.Credentials object to debug log."""
  if credentials:
    logging.debug('%s info: %r', title, {
        'access_token_expired': credentials.access_token_expired,
        'has_access_token': bool(credentials.access_token),
        'invalid': credentials.invalid,
        'utcnow': datetime.datetime.utcnow(),
        'token_expiry': credentials.token_expiry,
    })


def _run_oauth_dance(config, scopes):
  """Perform full 3-legged OAuth2 flow with the browser.

  Returns:
    oauth2client.Credentials.

  Raises:
    AuthenticationError on errors.
  """
  flow = client.OAuth2WebServerFlow(
      OAUTH_CLIENT_ID,
      OAUTH_CLIENT_SECRET,
      scopes,
      approval_prompt='force')

  use_local_webserver = config.use_local_webserver
  port = config.webserver_port
  if config.use_local_webserver:
    success = False
    try:
      httpd = _ClientRedirectServer(('localhost', port), _ClientRedirectHandler)
    except socket.error:
      pass
    else:
      success = True
    use_local_webserver = success
    if not success:
      print(
        'Failed to start a local webserver listening on port %d.\n'
        'Please check your firewall settings and locally running programs that '
        'may be blocking or using those ports.\n\n'
        'Falling back to --auth-no-local-webserver and continuing with '
        'authentication.\n' % port)

  if use_local_webserver:
    oauth_callback = 'http://localhost:%s/' % port
  else:
    oauth_callback = client.OOB_CALLBACK_URN
  flow.redirect_uri = oauth_callback
  authorize_url = flow.step1_get_authorize_url()

  if use_local_webserver:
    webbrowser.open(authorize_url, new=1, autoraise=True)
    print(
      'Your browser has been opened to visit:\n\n'
      '    %s\n\n'
      'If your browser is on a different machine then exit and re-run this '
      'application with the command-line parameter\n\n'
      '  --auth-no-local-webserver\n' % authorize_url)
  else:
    print(
      'Go to the following link in your browser:\n\n'
      '    %s\n' % authorize_url)

  try:
    code = None
    if use_local_webserver:
      httpd.handle_request()
      if 'error' in httpd.query_params:
        raise AuthenticationError(
            'Authentication request was rejected: %s' %
            httpd.query_params['error'])
      if 'code' not in httpd.query_params:
        raise AuthenticationError(
            'Failed to find "code" in the query parameters of the redirect.\n'
            'Try running with --auth-no-local-webserver.')
      code = httpd.query_params['code']
    else:
      code = raw_input('Enter verification code: ').strip()
  except KeyboardInterrupt:
    raise AuthenticationError('Authentication was canceled.')

  try:
    return flow.step2_exchange(code)
  except client.FlowExchangeError as e:
    raise AuthenticationError('Authentication has failed: %s' % e)


class _ClientRedirectServer(BaseHTTPServer.HTTPServer):
  """A server to handle OAuth 2.0 redirects back to localhost.

  Waits for a single request and parses the query parameters
  into query_params and then stops serving.
  """
  query_params = {}


class _ClientRedirectHandler(BaseHTTPServer.BaseHTTPRequestHandler):
  """A handler for OAuth 2.0 redirects back to localhost.

  Waits for a single request and parses the query parameters
  into the servers query_params and then stops serving.
  """

  def do_GET(self):
    """Handle a GET request.

    Parses the query parameters and prints a message
    if the flow has completed. Note that we can't detect
    if an error occurred.
    """
    self.send_response(200)
    self.send_header('Content-type', 'text/html')
    self.end_headers()
    query = self.path.split('?', 1)[-1]
    query = dict(urlparse.parse_qsl(query))
    self.server.query_params = query
    self.wfile.write('<html><head><title>Authentication Status</title></head>')
    self.wfile.write('<body><p>The authentication flow has completed.</p>')
    self.wfile.write('</body></html>')

  def log_message(self, _format, *args):
    """Do not log messages to stdout while running as command line program."""
