import functools
import re
from django.db import connections, connection

from six import text_type

import sqlparse

from . import app_settings

EXPLORER_PARAM_TOKEN = "$$"

# SQL Specific Things


def passes_blacklist(sql):
    clean = functools.reduce(lambda sql, term: sql.upper().replace(term, ""), [t.upper() for t in app_settings.EXPLORER_SQL_WHITELIST], sql)
    fails = [bl_word for bl_word in app_settings.EXPLORER_SQL_BLACKLIST if bl_word in clean.upper()]
    return not any(fails), fails


def get_connection():
    return connections[app_settings.EXPLORER_CONNECTION_NAME] if app_settings.EXPLORER_CONNECTION_NAME else connection


def schema_info():
    """
    Construct schema information via introspection of the django models in the database.

    :return: Schema information of the following form, sorted by db_table_name.
        [
            ("package.name -> ModelClass", "db_table_name",
                [
                    ("db_column_name", "DjangoFieldType"),
                    (...),
                ]
            )
        ]

    """

    schema_sql_postgres = '''
    WITH table_names as (
      select table_name from information_schema.tables WHERE table_schema = 'public'
    ),
    object_ids as (
      SELECT c.oid, c.relname
      FROM pg_catalog.pg_class c
      LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      WHERE c.relname in (select * from table_names)
    )

    SELECT
      oids.relname "Table",
      a.attname as "Column",
      pg_catalog.format_type(a.atttypid, a.atttypmod) as "Datatype"
      FROM
      pg_catalog.pg_attribute a
        inner join object_ids oids on oids.oid = a.attrelid
      WHERE
        a.attnum > 0
      AND NOT a.attisdropped;'''

    schema_sql_mysql = '''
    SELECT TABLE_NAME AS "Table", COLUMN_NAME AS "Column", DATA_TYPE AS "Datatype"
    FROM information_schema.columns WHERE table_schema = 'explorertest';'''

    cur = connection.cursor()

    cur.execute(schema_sql_mysql)
    res = cur.fetchall()
    from collections import defaultdict
    tables = defaultdict(list)
    for r in res:
        tables[r[0]].append((r[1], r[2]))

    return sorted(tables.items(), key=lambda x: x[0])


def _format_field(field):
    return field.get_attname_column()[1], field.get_internal_type()


def param(name):
    return "%s%s%s" % (EXPLORER_PARAM_TOKEN, name, EXPLORER_PARAM_TOKEN)


def swap_params(sql, params):
    p = params.items() if params else {}
    for k, v in p:
        regex = re.compile("\$\$%s(?:\:([^\$]+))?\$\$" % str(k).lower(), re.I)
        sql = regex.sub(text_type(v), sql)
    return sql


def extract_params(text):
    regex = re.compile("\$\$([a-z0-9_]+)(?:\:([^\$]+))?\$\$")
    params = re.findall(regex, text.lower())
    # We support Python 2.6 so can't use a dict comprehension
    return dict(zip([p[0] for p in params], [p[1] if len(p) > 1 else '' for p in params]))


# Helpers
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import login
from django.contrib.auth import REDIRECT_FIELD_NAME


def safe_login_prompt(request):
    defaults = {
        'template_name': 'admin/login.html',
        'authentication_form': AuthenticationForm,
        'extra_context': {
            'title': 'Log in',
            'app_path': request.get_full_path(),
            REDIRECT_FIELD_NAME: request.get_full_path(),
        },
    }
    return login(request, **defaults)


def shared_dict_update(target, source):
    for k_d1 in target:
        if k_d1 in source:
            target[k_d1] = source[k_d1]
    return target


def safe_cast(val, to_type, default=None):
    try:
        return to_type(val)
    except ValueError:
        return default


def get_int_from_request(request, name, default):
    val = request.GET.get(name, default)
    return safe_cast(val, int, default) if val else None


def get_params_from_request(request):
    val = request.GET.get('params', None)
    try:
        d = {}
        tuples = val.split('|')
        for t in tuples:
            res = t.split(':')
            d[res[0]] = res[1]
        return d
    except Exception:
        return None


def get_params_for_url(query):
    if query.params:
        return '|'.join(['%s:%s' % (p, v) for p, v in query.params.items()])


def url_get_rows(request):
    return get_int_from_request(request, 'rows', app_settings.EXPLORER_DEFAULT_ROWS)


def url_get_query_id(request):
    return get_int_from_request(request, 'query_id', None)


def url_get_log_id(request):
    return get_int_from_request(request, 'querylog_id', None)


def url_get_show(request):
    return bool(get_int_from_request(request, 'show', 1))


def url_get_params(request):
    return get_params_from_request(request)


def allowed_query_pks(user_id):
    return app_settings.EXPLORER_GET_USER_QUERY_VIEWS().get(user_id, [])


def user_can_see_query(request, kwargs):
    if not request.user.is_anonymous() and 'query_id' in kwargs:
        return int(kwargs['query_id']) in allowed_query_pks(request.user.id)
    return False


def fmt_sql(sql):
    return sqlparse.format(sql, reindent=True, keyword_case='upper')


def noop_decorator(f):
    return f


def get_s3_connection():
    import tinys3
    return tinys3.Connection(app_settings.S3_ACCESS_KEY,
                             app_settings.S3_SECRET_KEY,
                             default_bucket=app_settings.S3_BUCKET)
