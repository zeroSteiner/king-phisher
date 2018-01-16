#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  king_phisher/server/graphql/schema.py
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

from __future__ import absolute_import

import king_phisher.version as version
import king_phisher.server.graphql.middleware as gql_middleware
import king_phisher.server.graphql.types as gql_types

import graphene.types.utils

# top level query object for the schema
class Query(graphene.ObjectType):
	"""
	This is the root query object used for GraphQL queries.
	"""
	db = graphene.Field(gql_types.Database)
	geoloc = graphene.Field(gql_types.GeoLocation, ip=graphene.String())
	plugin = graphene.Field(gql_types.Plugin, name=graphene.String())
	plugins = graphene.relay.ConnectionField(gql_types.PluginConnection)
	version = graphene.Field(graphene.String)
	def resolve_db(self, info, **kwargs):
		return gql_types.Database()

	def resolve_geoloc(self, info, **kwargs):
		ip_address = kwargs.get('ip')
		if ip_address is None:
			return
		return gql_types.GeoLocation.from_ip_address(ip_address)

	def resolve_plugin(self, info, **kwargs):
		plugin_manager = info.context.get('plugin_manager', {})
		for _, plugin in plugin_manager:
			if plugin.name != kwargs.get('name'):
				continue
			return Plugin.from_plugin(plugin)

	def resolve_plugins(self, info, **kwargs):
		plugin_manager = info.context.get('plugin_manager', {})
		return [Plugin.from_plugin(plugin) for _, plugin in sorted(plugin_manager, key=lambda i: i[0])]

	def resolve_version(self, info, **kwargs):
		return version.version

class Schema(graphene.Schema):
	"""
	This is the top level schema object for GraphQL. It automatically sets up
	sane defaults to be used by the King Phisher server including setting
	the query to :py:class:`.Query` and adding the
	:py:class:`.AuthorizationMiddleware` to each execution.
	"""
	def __init__(self, **kwargs):
		kwargs['auto_camelcase'] = True
		kwargs['query'] = Query
		super(Schema, self).__init__(**kwargs)

	def execute(self, *args, **kwargs):
		if 'context_value' not in kwargs:
			kwargs['context_value'] = {}
		middleware = list(kwargs.pop('middleware', []))
		middleware.insert(0, gql_middleware.AuthorizationMiddleware())
		kwargs['middleware'] = middleware
		return super(Schema, self).execute(*args, **kwargs)

	def execute_file(self, path, *args, **kwargs):
		with open(path, 'r') as file_h:
			query = file_h.read()
		return self.execute(query, *args, **kwargs)
