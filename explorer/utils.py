import functools
import re
from collections import defaultdict
from django.db import connections, connection
from django.core.cache import cache

from six import text_type

import sqlparse

from schema_sql import SCHEMA_SQL
from . import app_settings

EXPLORER_PARAM_TOKEN = "$$"

# SQL Specific Things


def passes_blacklist(sql):
    clean = functools.reduce(lambda sql, term: sql.upper().replace(term, ""), [t.upper() for t in app_settings.EXPLORER_SQL_WHITELIST], sql)
    fails = [bl_word for bl_word in app_settings.EXPLORER_SQL_BLACKLIST if bl_word in clean.upper()]
    return not any(fails), fails


def get_default_connection():
    return connections[app_settings.EXPLORER_CONNECTION_NAME] if app_settings.EXPLORER_CONNECTION_NAME else connection


def schema_info(connection):
    """
    PARAM: connection is an alias to the valid connection
    Construct schema information via engine-specific queries of the tables in the DB.

    :return: Schema information of the following form, sorted by db_table_name.
        [
            ("db_table_name",
                [
                    ("db_column_name", "DbFieldType"),
                    (...),
                ]
            )
        ]

    """
    connection = connections[connection]
    sql = SCHEMA_SQL[connection.vendor]
    cur = connection.cursor()
    cur.execute(sql)
    res = cur.fetchall()
    tables = defaultdict(list)

    if connection.vendor == 'sqlite':
        for t in res:
            cur.execute('pragma table_info(%s);' % t)
            schema = cur.fetchall()
            for s in schema:
                tables[t[0]].append((s[1], s[2]))
    else:
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


def get_connections():
    key = 'explorer_db_connections_names'
    res = cache.get(key)
    if res is None:
        res = [c.alias for c in connections.all()]
        cache.set(key, res)
    return res
