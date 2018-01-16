#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  king_phisher/server/graphql.py
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

import datetime
import functools
import operator

import king_phisher.geoip as geoip
import king_phisher.ipaddress as ipaddress
import king_phisher.server.database.models as db_models
import king_phisher.version as version

import graphene
import graphene.relay.connection
import graphene.types
import graphene.types.utils
import graphene_sqlalchemy
import graphql.language.ast
import graphql_relay.connection.arrayconnection
import smoke_zephyr.utilities
import sqlalchemy.orm
import sqlalchemy.orm.query

# authorization middlware
class AuthorizationMiddleware(object):
	"""
	An authorization provider to ensure that the permissions on the objects
	that are queried are respected. If no **rpc_session** key is provided in
	the **context** dictionary then no authorization checks can be performed
	and all objects and operations will be accessible. The **rpc_session**
	key's value must be an instance of :py:class:`~.AuthenticatedSession`.
	"""
	def resolve(self, next_, root, info, **kwargs):
		if isinstance(root, db_models.Base) and not self.info_has_read_prop_access(info, root, instance=root):
			return
		return next_(root, info, **kwargs)

	@classmethod
	def info_has_read_prop_access(cls, info, model, field_name=None, instance=None):
		rpc_session = info.context.get('rpc_session')
		if rpc_session is None:
			return True
		field_name = field_name or info.field_name
		return model.session_has_read_prop_access(rpc_session, field_name, instance=instance)

# replacement graphql scalars
class AnyScalar(graphene.types.Scalar):
	@staticmethod
	def serialize(dt):
		raise NotImplementedError()

	@staticmethod
	def parse_literal(node):
		if isinstance(node, graphql.language.ast.FloatValue):
			return float(node.value)
		if isinstance(node, graphql.language.ast.IntValue):
			return int(node.value)
		return node.value

	@staticmethod
	def parse_value(value):
		return value

class DateTimeScalar(graphene.types.Scalar):
	@staticmethod
	def serialize(dt):
		return dt

	@staticmethod
	def parse_literal(node):
		if isinstance(node, graphql.language.ast.StringValue):
			return datetime.datetime.strptime(node.value, '%Y-%m-%dT%H:%M:%S.%f')

	@staticmethod
	def parse_value(value):
		return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f')

# misc definitions
class RelayNode(graphene.relay.Node):
	@classmethod
	def from_global_id(cls, global_id):
		return global_id

	@classmethod
	def to_global_id(cls, _, local_id):
		return local_id

class FilterOperatorEnum(graphene.Enum):
	EQ = 'eq'
	GE = 'ge'
	GT = 'gt'
	LE = 'le'
	LT = 'lt'
	NE = 'ne'

class FilterInput(graphene.InputObjectType):
	AND = graphene.List('king_phisher.server.graphql.FilterInput', name='and')
	OR = graphene.List('king_phisher.server.graphql.FilterInput', name='or')
	field = graphene.String()
	value = AnyScalar()
	operator = FilterOperatorEnum()

class SortDirectionEnum(graphene.Enum):
	AESC = 'aesc'
	DESC = 'desc'

class SortInput(graphene.InputObjectType):
	field = graphene.String(required=True)
	direction = SortDirectionEnum()

def sa_get_relationship(session, model, name):
	mapper = sqlalchemy.inspect(model.__class__)
	relationship = mapper.relationships[name]
	foreign_model = db_models.database_tables[relationship.table.name].model
	query = session.query(foreign_model)
	if relationship.uselist:
		column_name = relationship.primaryjoin.right.name
		return query.filter(getattr(foreign_model, column_name) == model.id)
	column_name = relationship.primaryjoin.left.name
	query = query.filter(getattr(foreign_model, column_name) == getattr(model, relationship.primaryjoin.right.name))
	return query.first()

def sa_object_resolver(attname, default_value, model, info, **kwargs):
	mapper = sqlalchemy.inspect(model.__class__)
	if attname in mapper.relationships:
		return sa_get_relationship(info.context['session'], model, attname)
	return getattr(model, attname)

sa_object_meta = functools.partial(dict, default_resolver=sa_object_resolver, interfaces=(RelayNode,))

# custom sqlalchemy related objects
class SQLAlchemyConnectionField(graphene_sqlalchemy.SQLAlchemyConnectionField):
	__connection_types = {}
	def __init__(self, node, *args, **kwargs):
		if 'filter' not in kwargs:
			kwargs['filter'] = FilterInput()
		if 'sort' not in kwargs:
			kwargs['sort'] = graphene.List(SortInput)
		node = self.connection_factory(node)
		super(SQLAlchemyConnectionField, self).__init__(node, *args, **kwargs)

	@classmethod
	def connection_factory(cls, node):
		name = node.__name__ + 'Connection'
		if name in cls.__connection_types:
			return cls.__connection_types[name]
		connection_type = type(
			node.__name__ + 'Connection',
			(graphene.relay.Connection,),
			{
				'Meta': type('Meta', (), {'node': node}),
				'total': graphene.Int()
			}
		)
		cls.__connection_types[name] = connection_type
		return connection_type

	@classmethod
	def connection_resolver(cls, resolver, connection, model, root, info, **kwargs):
		iterable = resolver(root, info, **kwargs)
		if iterable is None:
			iterable = cls.get_query(model, info, **kwargs)
			_len = iterable.count()
		elif isinstance(iterable, sqlalchemy.orm.query.Query):
			iterable = cls.query_shim(model, info, iterable, **kwargs)
			_len = iterable.count()
		else:
			_len = len(iterable)
		connection = graphql_relay.connection.arrayconnection.connection_from_list_slice(
			iterable,
			kwargs,
			slice_start=0,
			list_length=_len,
			list_slice_length=_len,
			connection_type=functools.partial(connection, total=_len),
			pageinfo_type=graphene.relay.connection.PageInfo,
			edge_type=connection.Edge
		)
		connection.iterable = iterable
		connection.length = _len
		return connection

	@classmethod
	def _query_filter(cls, model, info, query, gql_filter):
		sql_filter = cls.__query_filter(model, info, gql_filter)
		if sql_filter is not None:
			query = query.filter(sql_filter)
		return query

	@classmethod
	def __query_filter(cls, model, info, gql_filter):
		# precedence: AND, OR, field
		sql_filter = None
		if gql_filter.get('AND'):
			sql_filter = sqlalchemy.and_(*cls._query_filter_list(model, info, gql_filter['AND']))
		if gql_filter.get('OR'):
			if sql_filter is not None:
				raise ValueError('the \'and\', \'or\', and \'field\' filter operators are mutually exclusive')
			sql_filter = sqlalchemy.or_(*cls._query_filter_list(model, info, gql_filter['OR']))

		if gql_filter.get('field'):
			if sql_filter is not None:
				raise ValueError('the \'and\', \'or\', and \'field\' filter operators are mutually exclusive')
			operator_name = gql_filter.get('operator', 'eq')
			if operator_name not in ('eq', 'ge', 'gt', 'le', 'lt', 'ne'):
				raise ValueError('invalid operator: ' + operator_name)
			comparison_operator = getattr(operator, operator_name)
			gql_field = gql_filter['field']
			sql_field = smoke_zephyr.utilities.parse_case_camel_to_snake(gql_field)
			if '_' in gql_field or sql_field not in model.columns():
				raise ValueError('invalid filter field: ' + gql_field)
			if AuthorizationMiddleware.info_has_read_prop_access(info, model, sql_field):
				sql_filter = comparison_operator(getattr(model, sql_field), gql_filter.get('value', None))
		return sql_filter

	@classmethod
	def _query_filter_list(cls, model, info, gql_filters):
		query_filter_list = [cls.__query_filter(model, info, gql_filter) for gql_filter in gql_filters]
		return [query_filter for query_filter in query_filter_list if query_filter is not None]

	@classmethod
	def _query_sort(cls, model, info, query, gql_sort):
		for field in gql_sort:
			direction = field.get('direction', 'aesc')
			gql_field = field['field']
			sql_field = smoke_zephyr.utilities.parse_case_camel_to_snake(gql_field)
			if '_' in gql_field or sql_field not in model.columns():
				raise ValueError('invalid sort field: ' + gql_field)
			if not AuthorizationMiddleware.info_has_read_prop_access(info, model, sql_field):
				continue
			if direction == 'aesc':
				field = getattr(model, sql_field)
			elif direction == 'desc':
				field = getattr(model, sql_field).desc()
			else:
				raise ValueError('sort direction must be either \'aesc\' or \'desc\'')
			query = query.order_by(field)
		return query

	@classmethod
	def query_shim(cls, model, info, query, **kwargs):
		if kwargs.get('filter'):
			query = cls._query_filter(model, info, query, kwargs['filter'])
		if kwargs.get('sort'):
			query = cls._query_sort(model, info, query, kwargs['sort'])
		return query

	@classmethod
	def get_query(cls, model, info, **kwargs):
		query = super(SQLAlchemyConnectionField, cls).get_query(model, info, **kwargs)
		query = query.options(sqlalchemy.orm.raiseload('*'))
		return cls.query_shim(model, info, query, **kwargs)

	@property
	def type(self):
		# this is to bypass the one from
		# graphene_sqlalchemy.SQLAlchemyConnectionField which breaks
		return graphene.types.utils.get_type(self._type)

class SQLAlchemyObjectType(graphene_sqlalchemy.SQLAlchemyObjectType):
	class Meta:
		abstract = True

	@classmethod
	def get_query(cls, info, **kwargs):
		query = super(SQLAlchemyObjectType, cls).get_query(info)
		query = query.options(sqlalchemy.orm.raiseload('*'))
		model = cls._meta.model
		for field, value in kwargs.items():
			query = query.filter(getattr(model, field) == value)
		return query

# misc graphql objects
class GeoLocation(graphene.ObjectType):
	city = graphene.Field(graphene.String)
	continent = graphene.Field(graphene.String)
	coordinates = graphene.List(graphene.Float)
	country = graphene.Field(graphene.String)
	postal_code = graphene.Field(graphene.String)
	time_zone = graphene.Field(graphene.String)
	@classmethod
	def from_ip_address(cls, ip_address):
		ip_address = ipaddress.ip_address(ip_address)
		if ip_address.is_private:
			return
		result = geoip.lookup(ip_address)
		if result is None:
			return
		return cls(**result)

class Plugin(graphene.ObjectType):
	class Meta:
		interfaces = (RelayNode,)
	authors = graphene.List(graphene.String)
	title = graphene.Field(graphene.String)
	description = graphene.Field(graphene.String)
	homepage = graphene.Field(graphene.String)
	name = graphene.Field(graphene.String)
	version = graphene.Field(graphene.String)
	@classmethod
	def from_plugin(cls, plugin):
		return cls(
			authors=plugin.authors,
			description=plugin.description,
			homepage=plugin.homepage,
			name=plugin.name,
			title=plugin.title,
			version=plugin.version
		)

class PluginConnection(graphene.relay.Connection):
	class Meta:
		node = Plugin
	total = graphene.Int()
	def resolve_total(self, info, **kwargs):
		return len(info.context.get('plugin_manager', {}))

# database graphql objects
class AlertSubscription(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.AlertSubscription)
	expiration = DateTimeScalar()
	has_expired = graphene.Boolean()

class Credential(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.Credential)
	submitted = DateTimeScalar()

class DeaddropConnection(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.DeaddropConnection)
	first_seen = DateTimeScalar()
	last_seen = DateTimeScalar()
	visitor_geoloc = graphene.Field(GeoLocation)
	def resolve_visitor_geoloc(self, info, **kwargs):
		ip = self.ip
		if not ip:
			return
		return GeoLocation.from_ip_address(ip)

class DeaddropDeployment(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.DeaddropDeployment)
	# relationships
	deaddrop_connections = SQLAlchemyConnectionField(DeaddropConnection)

class Visit(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.Visit)
	first_seen = DateTimeScalar()
	last_seen = DateTimeScalar()
	visitor_geoloc = graphene.Field(GeoLocation)
	# relationships
	credentials = SQLAlchemyConnectionField(Credential)
	def resolve_visitor_geoloc(self, info, **kwargs):
		ip = self.ip
		if not ip:
			return
		return GeoLocation.from_ip_address(ip)

class LandingPage(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.LandingPage)
	first_visits = SQLAlchemyConnectionField(Visit)

class Message(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.Message)
	opened = DateTimeScalar()
	opener_geoloc = graphene.Field(GeoLocation)
	reported = DateTimeScalar()
	sent = DateTimeScalar()
	# relationships
	credentials = SQLAlchemyConnectionField(Credential)
	visits = SQLAlchemyConnectionField(Visit)
	def resolve_opener_geoloc(self, info, **kwargs):
		opener_ip = self.opener_ip
		if not opener_ip:
			return
		return GeoLocation.from_ip_address(opener_ip)

class Campaign(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.Campaign)
	created = DateTimeScalar()
	expiration = DateTimeScalar()
	has_expired = graphene.Boolean()
	# relationships
	alert_subscriptions = SQLAlchemyConnectionField(AlertSubscription)
	credentials = SQLAlchemyConnectionField(Credential)
	deaddrop_connections = SQLAlchemyConnectionField(DeaddropConnection)
	deaddrop_deployments = SQLAlchemyConnectionField(DeaddropDeployment)
	landing_pages = SQLAlchemyConnectionField(LandingPage)
	messages = SQLAlchemyConnectionField(Message)
	visits = SQLAlchemyConnectionField(Visit)

class CampaignType(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.CampaignType)
	# relationships
	campaigns = SQLAlchemyConnectionField(Campaign)

class Company(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.Company)
	# relationships
	campaigns = SQLAlchemyConnectionField(Campaign)

class CompanyDepartment(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.CompanyDepartment)
	# relationships
	messages = SQLAlchemyConnectionField(Message)

class Industry(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.Industry)
	# relationships
	companies = SQLAlchemyConnectionField(Company)

class User(SQLAlchemyObjectType):
	Meta = sa_object_meta(model=db_models.User)
	expiration = DateTimeScalar()
	has_expired = graphene.Boolean()
	last_login = DateTimeScalar()
	# relationships
	alert_subscriptions = SQLAlchemyConnectionField(AlertSubscription)
	campaigns = SQLAlchemyConnectionField(Campaign)

class Database(graphene.ObjectType):
	alert_subscription = graphene.Field(AlertSubscription, id=graphene.String())
	alert_subscriptions = SQLAlchemyConnectionField(AlertSubscription)
	campaign_type = graphene.Field(CampaignType, id=graphene.String())
	campaign_types = SQLAlchemyConnectionField(CampaignType)
	campaign = graphene.Field(Campaign, id=graphene.String(), name=graphene.String())
	campaigns = SQLAlchemyConnectionField(Campaign)
	company = graphene.Field(Company, id=graphene.String(), name=graphene.String())
	companies = SQLAlchemyConnectionField(Company)
	company_department = graphene.Field(CompanyDepartment, id=graphene.String())
	company_departments = SQLAlchemyConnectionField(CompanyDepartment)
	credential = graphene.Field(Credential, id=graphene.String())
	credentials = SQLAlchemyConnectionField(Credential)
	deaddrop_connection = graphene.Field(DeaddropConnection, id=graphene.String())
	deaddrop_connections = SQLAlchemyConnectionField(DeaddropConnection)
	deaddrop_deployment = graphene.Field(DeaddropDeployment, id=graphene.String())
	deaddrop_deployments = SQLAlchemyConnectionField(DeaddropDeployment)
	industry = graphene.Field(Industry, id=graphene.String())
	industries = SQLAlchemyConnectionField(Industry)
	landing_page = graphene.Field(LandingPage, id=graphene.String())
	landing_pages = SQLAlchemyConnectionField(LandingPage)
	message = graphene.Field(Message, id=graphene.String())
	messages = SQLAlchemyConnectionField(Message)
	user = graphene.Field(User, id=graphene.String(), name=graphene.String())
	users = SQLAlchemyConnectionField(User)
	visit = graphene.Field(Visit, id=graphene.String())
	visits = SQLAlchemyConnectionField(Visit)
	def resolve_alert_subscription(self, info, **kwargs):
		return AlertSubscription.get_query(info, **kwargs).first()

	def resolve_campaign(self, info, **kwargs):
		return Campaign.get_query(info, **kwargs).first()

	def resolve_campaign_type(self, info, **kwargs):
		return CampaignType.get_query(info, **kwargs).first()

	def resolve_company(self, info, **kwargs):
		return Company.get_query(info, **kwargs).first()

	def resolve_company_department(self, info, **kwargs):
		return CompanyDepartment.get_query(info, **kwargs).first()

	def resolve_credential(self, info, **kwargs):
		return Credential.get_query(info, **kwargs).first()

	def resolve_deaddrop_connection(self, info, **kwargs):
		return DeaddropConnection.get_query(info, **kwargs).first()

	def resolve_deaddrop_deployment(self, info, **kwargs):
		return DeaddropDeployment.get_query(info, **kwargs).first()

	def resolve_industry(self, info, **kwargs):
		return Industry.get_query(info, **kwargs).first()

	def resolve_landing_page(self, info, **kwargs):
		return LandingPage.get_query(info, **kwargs).first()

	def resolve_message(self, info, **kwargs):
		return Message.get_query(info, **kwargs).first()

	def resolve_user(self, info, **kwargs):
		return User.get_query(info, **kwargs).first()

	def resolve_visit(self, info, **kwargs):
		return Visit.get_query(info, **kwargs).first()

# top level query object for the schema
class Query(graphene.ObjectType):
	"""
	This is the root query object used for GraphQL queries.
	"""
	db = graphene.Field(Database)
	geoloc = graphene.Field(GeoLocation, ip=graphene.String())
	plugin = graphene.Field(Plugin, name=graphene.String())
	plugins = graphene.relay.ConnectionField(PluginConnection)
	version = graphene.Field(graphene.String)
	def resolve_db(self, info, **kwargs):
		return Database()

	def resolve_geoloc(self, info, **kwargs):
		ip_address = kwargs.get('ip')
		if ip_address is None:
			return
		return GeoLocation.from_ip_address(ip_address)

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
		middleware.insert(0, AuthorizationMiddleware())
		kwargs['middleware'] = middleware
		return super(Schema, self).execute(*args, **kwargs)

	def execute_file(self, path, *args, **kwargs):
		with open(path, 'r') as file_h:
			query = file_h.read()
		return self.execute(query, *args, **kwargs)

schema = Schema()
