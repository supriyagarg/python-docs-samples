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
    """Returns the pieces of a metric type.  Arg type is full metric type name
       ('compute.googleapis.com/instance/cpu/utilization'). Result is (g, s, p),
       where g is group code ('gcp'), s is a service code ('compute'), p is path
       to metric ('instance/cpu/utilization').
    """
    path_split = type.split('/')
    first_domain_piece = path_split[0].split('.')[0]
    first_path_piece = path_split[1]
    remaining_path = "/".join(path_split[2:])
    whole_path = "/".join(path_split[1:])
    result = ()

    if first_domain_piece == 'agent':
        result = (first_domain_piece, first_path_piece, remaining_path)
    elif first_domain_piece == 'aws':
        result = (first_domain_piece, first_path_piece, remaining_path)
    elif first_domain_piece == 'custom' and len(path_split) > 2:
        result = (first_domain_piece, first_path_piece, remaining_path)
    elif first_domain_piece == 'custom':
        result = (first_domain_piece, u'', whole_path)
    else:
        # Assume it's a GCP service.
        result = (u'gcp', first_domain_piece, whole_path)
    return result


def get_external_name(g, s, path):
    """Gets the canonical name of the metric or path.
    Result does not end in '/', ever.
    Args:
      g: group code: 'aws', 'gcp', 'agent', 'custom'
      s: service code: 'compute', 'CloudWatch', etc.
      path: optional metric path: 'instance/cpu/utilization'
    """
    if len(path) > 0:
        path = '/' + path
    if len(s) > 0:
        s = '/' + s
    if g == 'agent':
        name = 'agent.googleapis.com{0}{1}'.format(s, path)
    elif g == 'aws':
        name = 'aws.googleapis.com{0}{1}'.format(s, path)
    elif g == 'custom':
        name = 'custom.googleapis.com{0}{1}'.format(s, path)
    else:
        name = '{0}.googleapis.com{1}'.format(s, path)
    return name


def get_group_title_and_descr(g):
    """Gets the title of the metric group."""
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

group_set = set()  # the group names (presently four)
service_set = dict()  # sets of service names per group
metric_dict = dict()  # sets of metric types per service name
timeseries_set = set()  # service names that seem to have timeseries


def read_metric_descriptors(client, project_name, prefix):
    """Reads all the metric descriptors with the given prefix, parses the type names
    into groups, services, and service metrics.  Leaves the data in the global
    variables group_set, service_set, metric_dict, timeseries_set.
    """
    TEST_CAP=100
    request = client.projects().metricDescriptors().list(
        name=project_name,
        filter='metric.type=starts_with("{0}")'.format(prefix) if len(prefix)>0 else '')
    response = request.execute()
    if u'metricDescriptors' not in response:
        print "FAILED TO LIST METRIC DESCRIPTORS"
        print response
    descriptor_list = response[u'metricDescriptors']
    if u'nextPageToken' in response:
        print "RESULTS ARE INCOMPLETE."  # TODO: handle multiple batches

    count = 0
    for descr in descriptor_list:
        count = count + 1
        type = descr[u'type']
        g, s, p = get_type_pieces(type)
        # gs is our canonical name of the service, e.g., "gcp/appengine".
        gs = '{0}/{1}'.format(g, s)

        # Is this the first time we've seen the group?
        if g not in group_set:
            group_set.add(g)
            service_set[g] = set()
        service_set[g].add(s)

        # Is this the first time we've seen the service?  If so, we'll
        # also probe the first metric to see if there are any
        # timeseries data points. (Imperfect heuristic.)
        if gs not in metric_dict:
            metric_dict[gs] = dict()
            # print 'probing: ', type
            # if probe_time_series(client, project_name, type) > 0:
            #     timeseries_set.add(gs)
        # Save whole metricDescriptor, indexed by metric type name.
        metric_dict[gs][type] = descr
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
        print "RESULTS ARE INCOMPLETE."  # TODO: handle multiple batches
        pprint.pprint(response)
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
    for g in sorted(group_set):
        metric_cnt_in_group = 0

        for s in sorted(service_set[g]):
            metric_cnt_in_service = 0
            gs = '{0}/{1}'.format(g, s)

            # Metric count in this service.
            n = len(metric_dict[gs])
            print 'Service',gs,'has',n,'metrics'
            metric_cnt_in_group += n
            metric_cnt += n

        print 'Group',g,'has',len(service_set[g]),'services'
        print 'Group',g,'has',metric_cnt_in_group,'metrics'
        print

    print 'There are',metric_cnt,'total metrics'
    print 'There are', len(timeseries_set),'services with time series'
    pprint.pprint(timeseries_set)


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

This page lists the metrics available in {{product_name_short}}.  For an
introduction to metrics, metric naming, and metric labels, see
[Metrics](/monitoring/api/v3/metrics).  To use the {{api_name_short}} to browse
metrics, retrieve metric data, and create custom metrics, see [Using
Metrics](/monitoring/api/v3/using-metrics)

"""

PAGE_SUFFIX="""
{% endblock %}
"""

def tag_def(t):
    return '{:#' + t + '}'


def format_metric_lists():
    """Traverses the metric data and generates the markdown page."""
    print PAGE_PREFIX
    for g in sorted(group_set):
        if g == 'custom':
            continue
        g_name, g_descr = get_group_title_and_descr(g)
        print '\n## {0} {1}'.format(g_name, tag_def(g))
        print '\n{0}'.format(g_descr)

        for s in sorted(service_set[g]):
            gs = '{0}/{1}'.format(g, s)
            # Custom metrics can have s==''; use 'none' for titles and tags.
            s_tag = s if len(s) > 0 else 'none'
            print '\n### `{0}` {1}'.format(s_tag, tag_def(g + '-' + s_tag))
            print '\nMetrics prefixed with `{0}/`:'.format(get_external_name(g, s, ""))
            print '\nMetric type  | Name | Kind, Type | Labels'
            print '------- | ------ | ----- | ---------'
            for k in sorted(metric_dict[gs]):
                metric_descr = metric_dict[gs][k]
                g, s, p  = get_type_pieces(metric_descr[u'type'])
                displayName = metric_descr[u'displayName']
                metricKind = metric_descr[u'metricKind']
                valueType = metric_descr[u'valueType']
                descr = metric_descr[u'description']
                labels = metric_descr[u'labels'] if u'labels' in metric_descr else ''
                print '{0}  |  {1}  |  {2}, {3}  | {4} '.format(p, displayName, metricKind, valueType, ", ".join(l[u'key'] for l in labels))
    print PAGE_SUFFIX


TEST_METRIC="compute.googleapis.com/instance/cpu/utilization"


def main(project_id):
    project_resource = "projects/{0}".format(project_id)
    client = list_resources.get_client()
    count = read_metric_descriptors(client, project_resource, '')
    print >> sys.stderr, 'Read', count, 'metrics.'
    # show_metric_stats()
    format_metric_lists()
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

    args = parser.parse_args()
    main(args.project_id)

# [END all]
