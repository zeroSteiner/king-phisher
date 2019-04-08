# -*- coding: utf-8 -*-
#
#  king_phisher/server/__main__.py
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are
#  met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following disclaimer
#    in the documentation and/or other materials provided with the
#    distribution.
#  * Neither the name of the project nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#  A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#  SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#  THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
#  pylint: disable=too-many-locals

import argparse
import functools
import logging
import os
import signal
import sys
import threading

from king_phisher import startup
from king_phisher import color
from king_phisher import constants
from king_phisher import errors
from king_phisher import find
from king_phisher import geoip
from king_phisher import utilities
from king_phisher import version
from king_phisher.server import build
from king_phisher.server import configuration
from king_phisher.server import plugins
from king_phisher.server import pylibc

from boltons import strutils

logger = logging.getLogger('KingPhisher.Server.CLI')

def sig_handler(server, name, number, frame):
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	signal.signal(signal.SIGTERM, signal.SIG_IGN)
	logger.info("received signal {0}, shutting down the server".format(name))
	threading.Thread(target=server.shutdown).start()

def build_and_run(arguments, config, plugin_manager, log_file=None):
	# fork into the background
	should_fork = True
	if arguments.foreground:
		should_fork = False
	elif config.has_option('server.fork'):
		should_fork = bool(config.get('server.fork'))
	if should_fork:
		if os.fork():
			return sys.exit(os.EX_OK)
		os.setsid()

	try:
		king_phisher_server = build.server_from_config(config, plugin_manager=plugin_manager)
	except errors.KingPhisherDatabaseAuthenticationError:
		logger.critical('failed to authenticate to the database, this usually means the password is incorrect and needs to be updated')
		return os.EX_SOFTWARE
	except errors.KingPhisherError as error:
		logger.critical('server failed to build with error: ' + error.message)
		return os.EX_SOFTWARE

	server_pid = os.getpid()
	logger.info("server running in process: {0} main tid: 0x{1:x}".format(server_pid, threading.current_thread().ident))

	if should_fork and config.has_option('server.pid_file'):
		pid_file = open(config.get('server.pid_file'), 'w')
		pid_file.write(str(server_pid))
		pid_file.close()

	if config.has_option('server.setuid_username'):
		setuid_username = config.get('server.setuid_username')
		try:
			passwd = pylibc.getpwnam(setuid_username)
		except KeyError:
			logger.critical('an invalid username was specified as \'server.setuid_username\'')
			king_phisher_server.shutdown()
			return os.EX_NOUSER

		if log_file is not None:
			utilities.fs_chown(log_file, user=passwd.pw_uid, group=passwd.pw_gid, recursive=False)
		data_path = config.get_if_exists('server.letsencrypt.data_path')
		if data_path and config.get_if_exists('server.letsencrypt.chown_data_path', True):
			utilities.fs_chown(data_path, user=passwd.pw_uid, group=passwd.pw_gid, recursive=True)

		os.setgroups(pylibc.getgrouplist(setuid_username))
		os.setresgid(passwd.pw_gid, passwd.pw_gid, passwd.pw_gid)
		os.setresuid(passwd.pw_uid, passwd.pw_uid, passwd.pw_uid)
		logger.info("dropped privileges to the {} account (uid: {}, gid: {})".format(setuid_username, passwd.pw_uid, passwd.pw_gid))
	else:
		logger.warning('running with root privileges is dangerous, drop them by configuring \'server.setuid_username\'')
	os.umask(0o077)

	db_engine_url = king_phisher_server.database_engine.url
	if db_engine_url.drivername == 'sqlite':
		logger.warning('sqlite is no longer fully supported, see https://github.com/securestate/king-phisher/wiki/Database#sqlite for more details')
		database_dir = os.path.dirname(db_engine_url.database)
		if not os.access(database_dir, os.W_OK):
			logger.critical('sqlite requires write permissions to the folder containing the database')
			king_phisher_server.shutdown()
			return os.EX_NOPERM

	signal.signal(signal.SIGHUP, functools.partial(sig_handler, king_phisher_server, 'SIGHUP'))
	signal.signal(signal.SIGINT, functools.partial(sig_handler, king_phisher_server, 'SIGINT'))
	signal.signal(signal.SIGTERM, functools.partial(sig_handler, king_phisher_server, 'SIGTERM'))

	try:
		king_phisher_server.serve_forever(fork=False)
	except KeyboardInterrupt:
		pass
	king_phisher_server.shutdown()
	return os.EX_OK

def _ex_config_logging(arguments, config, console_handler):
	"""
	If a setting is configured improperly, this will terminate execution via
	:py:func:`sys.exit`.

	:return: The path to a log file if one is in use.
	:rtype: str
	"""
	default_log_level = min(
		getattr(logging, (arguments.loglvl or constants.DEFAULT_LOG_LEVEL)),
		getattr(logging, config.get_if_exists('logging.level', 'critical').upper())
	)
	log_levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'FATAL')
	file_path = None
	if config.has_option('logging.file'):
		options = config.get('logging.file')
		for _ in range(1):
			default_format = '%(asctime)s %(name)-50s %(levelname)-8s %(message)s'
			if isinstance(options, dict):   # new style
				if not options.get('enabled', True):
					break
				if 'path' not in options:
					color.print_error('logging.file is missing required key \'path\'')
					sys.exit(os.EX_CONFIG)
				if 'level' not in options:
					color.print_error('logging.file is missing required key \'level\'')
					sys.exit(os.EX_CONFIG)
				file_path = options['path']
				formatter = logging.Formatter(options.get('format', default_format))
				if not options['level'].upper() in log_levels:
					color.print_error('logging.file.level is invalid, must be one of: ' + ', '.join(log_levels))
					sys.exit(os.EX_CONFIG)
				log_level = getattr(logging, options['level'].upper())
				root = options.get('root', '')
			elif isinstance(options, str):  # old style
				file_path = options
				formatter = logging.Formatter(default_format)
				log_level = default_log_level
				root = ''
			else:
				break
			file_handler = logging.FileHandler(file_path)
			file_handler.setFormatter(formatter)
			logging.getLogger(root).addHandler(file_handler)
			file_handler.setLevel(log_level)

	if config.has_option('logging.console'):
		options = config.get('logging.console')
		for _ in range(1):
			if isinstance(options, dict):   # new style
				if not options.get('enabled', True):
					break
				if 'format' in options:
					console_handler.setFormatter(color.ColoredLogFormatter(options['format']))

				if arguments.loglvl is None and 'level' in options:
					log_level = str(options.get('level', '')).upper()
					if log_level not in log_levels:
						color.print_error('logging.console.level is invalid, must be one of: ' + ', '.join(log_levels))
						sys.exit(os.EX_CONFIG)
					console_handler.setLevel(getattr(logging, log_level))
			elif isinstance(options, str):  # old style
				console_handler.setLevel(default_log_level)
	return file_path

def main():
	parser = argparse.ArgumentParser(description='King Phisher Server', conflict_handler='resolve')
	utilities.argp_add_args(parser)
	startup.argp_add_server(parser)
	arguments = parser.parse_args()

	# basic runtime checks
	if sys.version_info < (3, 4):
		color.print_error('the Python version is too old (minimum required is 3.4)')
		return 0

	console_log_handler = utilities.configure_stream_logger(arguments.logger, arguments.loglvl)
	del parser

	if os.getuid():
		color.print_error('the server must be started as root, configure the')
		color.print_error('\'server.setuid_username\' option in the config file to drop privileges')
		return os.EX_NOPERM

	# configure environment variables and load the config
	find.init_data_path('server')
	config = configuration.ex_load_config(arguments.config_file)
	if arguments.verify_config:
		color.print_good('configuration verification passed')
		color.print_good('all required settings are present')
		return os.EX_OK
	if config.has_option('server.data_path'):
		find.data_path_append(config.get('server.data_path'))

	if arguments.update_geoip_db:
		color.print_status('downloading a new geoip database')
		try:
			size = geoip.download_geolite2_city_db(config.get('server.geoip.database'))
		except errors.KingPhisherResourceError as error:
			color.print_error(error.message)
			return os.EX_UNAVAILABLE
		color.print_good("download complete, file size: {0}".format(strutils.bytes2human(size)))
		return os.EX_OK

	# setup logging based on the configuration
	if config.has_section('logging'):
		log_file = _ex_config_logging(arguments, config, console_log_handler)
	logger.debug("king phisher version: {0} python version: {1}.{2}.{3}".format(version.version, sys.version_info[0], sys.version_info[1], sys.version_info[2]))

	# initialize the plugin manager
	try:
		plugin_manager = plugins.ServerPluginManager(config)
	except errors.KingPhisherError as error:
		if isinstance(error, errors.KingPhisherPluginError):
			color.print_error("plugin error: {0} ({1})".format(error.plugin_name, error.message))
		else:
			color.print_error(error.message)
		return os.EX_SOFTWARE

	status_code = build_and_run(arguments, config, plugin_manager, log_file)
	plugin_manager.shutdown()
	logging.shutdown()
	return status_code

if __name__ == '__main__':
	sys.exit(main())
