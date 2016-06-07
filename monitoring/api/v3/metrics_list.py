#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Produces an HTML page listing all the Stackdriver Monitoring metrics.

    python metrics_list.py --project_id=your-project-id > your-file.html
"""

# [START all]
import argparse
import datetime
import pprint
import random
import sys
import time

import list_resources


def format_rfc3339(datetime_instance=None):
    """Formats a datetime per RFC 3339.
    :param datetime_instance: Datetime instanec to format, defaults to utcnow
    """
    return datetime_instance.isoformat("T") + "Z"


def get_start_time():
    # Return now- 5 minutes
    start_time = datetime.datetime.utcnow() - datetime.timedelta(days=30)
    return format_rfc3339(start_time)


def get_now_rfc3339():
    # Return now
    end_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
    return format_rfc3339(end_time)


def get_type_pieces(type):
    """Returns the pieces of a metric type: group, service, path.
    Group is 'gcp', 'aws', 'agent', or 'custom'.
    Service is a name in the metric type, e.g., 'compute', 'SNS', 'nginx', etc.
    Path is the path within a service, such as 'instance/CPU/utilization'.

    Args:
        type: for example, 'compute.googleapis.com/instance/CPU/utilization'
    """
    name_split = type.split('/')
    group = name_split[0].split('.')[0]

    if group == 'agent':
        service = name_split[1]
        path = '/'.join(name_split[2:])
    elif group == 'aws':
        service = name_split[1]
        path = '/'.join(name_split[2:])
    elif group == 'custom' and len(name_split) > 2:
        # Call the first path component the "service".
        service = name_split[1]
        path = '/'.join(name_split[2:])
    elif group == 'custom':
        # No "service".
        service = ''
        path = '/'.join(name_split[1:])
    else:
        # Assume it's a GCP service; leading domain is the service.
        service = group
        group = 'gcp'
        path = '/'.join(name_split[1:])
    return (group, service, path)


def get_path_prefix(g, s):
    """Reconstructs the metric type name's path prefix.
    For example ('gcp', 'compute) -> 'compute.googleapis.com', and
    ('agent', 'nginx') -> 'agent.googleapis.com/nginx'.
    Result does not end in '/', ever.
    Args:
      g: group code: 'aws', 'gcp', 'agent', 'custom'
      s: service code: 'compute', 'CloudWatch', etc. Can be '' for custom.
    """
    prefix = None
    if g == 'aws':
        prefix = 'aws.googleapis.com/{0}'.format(s)
    elif g == 'agent':
        prefix = 'agent.googleapis.com/{0}'.format(s)
    elif g == 'gcp':
        prefix = '{0}.googleapis.com'.format(s)
    elif g == 'custom':
        if s:
            prefix = 'custom.googleapis.com/{0}'.format(s)
        else:
            prefix = 'custom.googleapis.com'
    else:
        print >> sys.stderr, 'ERR: group "{0}", service "{1}"'.format(g,s)
    return prefix


def get_group_title_and_descr(g):
    """Returns the name and description of a metric group."""
    if g == 'agent':
        name = 'Agent metrics'
        descr = 'Metrics collected by the Stackdriver Monitoring agent.'
    elif g == 'aws':
        name = 'Amazon Web Services metrics'
        descr = 'Metrics from Amazon Web Services.'
    elif g == 'custom':
        name = 'Custom metrics'
        descr = 'Custom metrics defined by users.'
    else:
        name = 'Google Cloud Platform metrics'
        descr = 'Metrics from Google Cloud Platform services.'
    return (name, descr)


# Global variables to hold metric descriptor information
GROUP_SET = set()  # the group names (presently four)
SERVICE_SET = dict()  # maps from a group code to a set of services
METRIC_DICT = dict()  # maps 'g/s' code to a map of paths to metric descriptors
TIME_SERIES_SET = set()  # a set of 'g/s' services that have time series data


def read_metric_descriptors(client, project_name, prefix, custom, timeseries):
    """Reads all the metric descriptors with the given prefix, parses the type names
    into groups, services, and service metrics.  Leaves the data in the global
    variables GROUP_SET, SERVICE_SET, METRIC_DICT, TIME_SERIES_SET.
    """
    print >> sys.stderr, 'OPTION: PROJECT: ', project_name
    if prefix:
        print >> sys.stderr, 'OPTION: STARTS_WITH: ', prefix
    if custom:
        print >> sys.stderr, 'OPTION: WILL LIST CUSTOM METRICS '
    if timeseries:
        print >> sys.stderr, 'OPTION: WILL PROBE FOR TIME SERIES '
    request = client.projects().metricDescriptors().list(
        name=project_name,
        filter='metric.type=starts_with("{0}")'.format(prefix) if prefix else '')
    response = request.execute()
    if u'metricDescriptors' not in response:
        print >> sys.stderr, 'ERR: FAILED metricDescriptors.list (AUTH?)'
        print >> sys.stderr, response
    descriptor_list = response[u'metricDescriptors']
    if u'nextPageToken' in response:
        # Log but ignore missing results. TODO: handle multiple batches
        print >> sys.stderr, 'ERR: DESCRIPTORS ARE INCOMPLETE.'

    count = 0
    for descr in descriptor_list:
        count = count + 1
        type = descr[u'type']
        g, s, p = get_type_pieces(type)
        # Ignore custom metrics unless asked for.
        if g == 'custom' and not custom:
            continue
        # gs is a unique ID for a service; e.g., "gcp/appengine".
        gs = '{0}/{1}'.format(g, s)

        # Is this the first time we've seen the group?
        if g not in GROUP_SET:
            GROUP_SET.add(g)
            SERVICE_SET[g] = set()
        SERVICE_SET[g].add(s)

        # Is this the first time we've seen the service?  If so, we'll
        # also probe the first metric to see if there are any
        # timeseries data points. (Imperfect heuristic.)
        if gs not in METRIC_DICT:
            METRIC_DICT[gs] = dict()
            # TODO: Add time series probing here.
            # if probe_time_series(client, project_name, type) > 0:
            #     TIME_SERIES_SET.add(gs)
        # Add this metric to the big dictionary of metrics.
        METRIC_DICT[gs][p] = descr
    return count


def probe_time_series(client, project_name, metric_type):
    """Returns the number of time series available for 'metric_type'.
    """
    request = client.projects().timeSeries().list(
        name=project_name,
        filter='metric.type="{0}"'.format(metric_type),
        view='HEADERS',  # Don't want the data points.
        fields='timeSeries.resource.type',
        interval_startTime=get_start_time(),
        interval_endTime=get_now_rfc3339())
    response = request.execute()
    if u'nextPageToken' in response:
        print >> sys.stderr, 'ERR: TIME SERIES INCOMPLETE.'  # TODO: handle multiple batches
    if u'timeSeries' not in response:
        return 0
    timeseries_list = response[u'timeSeries']
    return len(timeseries_list)


def detail_time_series(client, project_name, metric_type):
    """Fetches and prints all time series for 'metric_type'. LOTS OF DATA.
    """
    request = client.projects().timeSeries().list(
        name=project_name,
        filter='metric.type="{0}"'.format(metric_type),
        fields='timeSeries.resource.type,timeSeries.metricKind,timeSeries.metric.labels,timeSeries.points',
        interval_startTime=get_start_time(),
        interval_endTime=get_now_rfc3339())
    response = request.execute()
    if u'nextPageToken' in response:
        print "RESULTS ARE INCOMPLETE."  # TODO: handle multiple batches
    timeseries_list = response[u'timeSeries']
    return len(timeseries_list)


def show_metric_stats():
    """Traverses the metric data and prints statistics of the numbers of groups,
    services in each group, and metrics in each service."""
    metric_cnt = 0
    for g in sorted(GROUP_SET):
        metric_cnt_in_group = 0

        for s in sorted(SERVICE_SET[g]):
            metric_cnt_in_service = 0
            gs = '{0}/{1}'.format(g, s)

            # Metric count in this service.
            n = len(METRIC_DICT[gs])
            print 'Service',gs,'has',n,'metrics'
            metric_cnt_in_group += n
            metric_cnt += n

        print 'Group',g,'has',len(SERVICE_SET[g]),'services'
        print 'Group',g,'has',metric_cnt_in_group,'metrics'
        print

    print 'There are',metric_cnt,'total metrics'
    print 'There are', len(TIME_SERIES_SET),'services with time series'
    pprint.pprint(TIME_SERIES_SET)


PAGE_PREFIX="""{% extends "monitoring/_base.html" %}
{% block page_title %}Metrics List{% endblock %}

{% block body %}

{% comment %}

    CAUTION: THIS IS A GENERATED FILE.
    Do not modify this file. Your changes will be
    overwritten the next time this file is generated.

{% endcomment %}


{% setvar feature_disclaimer %}{{ product_name }}{% endsetvar %}
{% include "cloud/_shared/_notice_beta.html" %}

This page lists the metrics available in {{product_name_short}}.  The
fields listed for each metric are defined in the
[`MetricDescriptor` object](/monitoring/api/ref_v3/rest/v3/projects.metricDescriptors).

For an introduction to metrics, metric naming, and metric labels, see
[Metrics and Time Series](/monitoring/api/v3/metrics).  To use the
{{api_name_short}} to browse metrics, retrieve metric data, and create
custom metrics, see [Using Metrics](/monitoring/api/v3/using-metrics).
"""

PAGE_SUFFIX="""
{% endblock %}
"""

def tag_def(t):
    return '{:#' + t + '}'


def format_metric_lists(starts_with):
    """Traverses the metric data and generates the markdown page."""
    print PAGE_PREFIX

    if starts_with:
        print ('Note: This metric list includes only metrics whose type names ' +
               'begin with "{0}".').format(starts_with)

    for g in sorted(GROUP_SET):
        # Create a heading for each group.
        g_name, g_descr = get_group_title_and_descr(g)
        print '\n## {0} {1}'.format(g_name, tag_def(g))
        print '\n{0}'.format(g_descr)

        for s in sorted(SERVICE_SET[g]):
            gs = '{0}/{1}'.format(g, s)
            # Write heading for service.
            # Custom metrics can have s==''; use 'none' for titles and tags.
            s_tag = s if s else 'none'
            print '\n### `{0}` {1}'.format(s_tag, tag_def(g + '-' + s_tag))
            print ('\nThe following metric types are prefixed with `{0}/`:'
                   .format(get_path_prefix(g, s)))

            print '\nMetric type<br/>Display name<br/>Kind, Type, Unit | Description<br/>Labels'
            print '--------------------------------------------------- | ----------------------'
            # For each metric in the group+service:
            for metric_path in sorted(METRIC_DICT[gs]):
                metric_descriptor = METRIC_DICT[gs][metric_path]
                metric_type = metric_descriptor[u'type']
                display_name = metric_descriptor.get(u'displayName')
                metric_kind = metric_descriptor.get(u'metricKind')
                value_type = metric_descriptor.get(u'valueType')
                unit = metric_descriptor.get(u'unit')
                description = metric_descriptor.get(u'description')
                # Add a period to the end of the description if needed.
                if description and description[-1] != '.':
                    description += '.'
                labels = metric_descriptor.get(u'labels', [])
                formatted_label_list = []
                for label in labels:
                    label_key = label[u'key']
                    label_description = label.get(u'description')
                    if not label_description:
                        print >> sys.stderr, 'NO LABEL DESCRIPTION: metric "{0}", label "{1}".'.format(metric_type, label_key)
                    # Omit the default label value type (string).
                    label_type = label.get(u'valueType')
                    formatted_label_type = '({0})'.format(label_type) if label_type else ''
                    formatted_label_list.append('`{0}`{1}: {2}'.format(label_key, formatted_label_type, label_description))

                print '`{0}`<br/>{1}<br/>`{2}`, `{3}`, {4}  | {5}<br/>{6}'.format(
                    metric_path, display_name.encode('utf-8'),
                    metric_kind, value_type, unit, description.encode('utf-8'),
                    "<br/>".join(formatted_label_list))
    print PAGE_SUFFIX


TEST_METRIC="compute.googleapis.com/instance/cpu/utilization"


def main(project_id, starts_with, custom, timeseries):
    project_resource = "projects/{0}".format(project_id)
    client = list_resources.get_client()
    count = read_metric_descriptors(client, project_resource, starts_with, custom, timeseries)
    print >> sys.stderr, 'Read', count, 'metrics.'
    # show_metric_stats()
    format_metric_lists(starts_with)
#    detail_time_series(client,project_resource, TEST_METRIC)
#    n = probe_time_series(client, project_resource, TEST_METRIC)
#    print TEST_METRIC,'has',n,'time series'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--project_id', help='Project ID you want to access.', required=True)
    parser.add_argument(
        '--custom', help='List custom metrics.', action='store_true')
    parser.add_argument(
        '--timeseries', help='Check first metric of each service for available time series.',
        action='store_true')
    parser.add_argument(
        '--starts_with', help='Only metrics that start with this value.')

    args = parser.parse_args()
    main(args.project_id, args.starts_with, args.custom, args.timeseries)

# [END all]
