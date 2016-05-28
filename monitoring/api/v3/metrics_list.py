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


def get_group_and_service(type):
    """Returns the group (agent, aws, custom, or gcp) and service
       (pubsub, CloudFront,...).
    """
    path_split = type.split('/')
    first_path_piece = path_split[1]
    first_domain_piece = path_split[0].split('.')[0]
    result = ()

    if first_domain_piece == 'agent':
        result = (first_domain_piece, first_path_piece)
    elif first_domain_piece == 'aws':
        result = (first_domain_piece, first_path_piece)
    elif first_domain_piece == 'custom' and len(path_split) > 2:
        result = (first_domain_piece, first_path_piece)
    elif first_domain_piece == 'custom':
        result = (first_domain_piece, u'')
    else:
        result = (u'gcp', first_domain_piece)
    return result

group_set = set()  # the group names (presently four)
service_set = dict()  # sets of service names per group
metric_set = dict()  # sets of metric types per service name
timeseries_set = set()  # service names that seem to have timeseries

def read_metric_descriptors(client, project_name):
    """Reads all the metric descriptors and indexes them.
    """
    request = client.projects().metricDescriptors().list(
        name=project_name,
        # filter='metric.type:"utilization"',
        fields='metricDescriptors.type')
    response = request.execute()
    descriptor_list = response[u'metricDescriptors']
    if u'nextPageToken' in response:
        print "RESULTS ARE INCOMPLETE."

    for descr in descriptor_list:
        type = descr[u'type']
        g, s = get_group_and_service(type)
        gs = '{0}/{1}'.format(g, s)

        # Is this the first time we've seen the group?
        if g not in group_set:
            group_set.add(g)
            service_set[g] = set()
        service_set[g].add(s)

        # Is this the first time we've seen the service?
        if gs not in metric_set:
            metric_set[gs] = set()
            print 'probing: ', type
            if probe_time_series(client, project_name, type) > 0:
                timeseries_set.add(gs)
        metric_set[gs].add(type)


def probe_time_series(client, project_name, metric_type):
    """Returns the number of time series available for 'metric_type'
    """
    request = client.projects().timeSeries().list(
        name=project_name,
        filter='metric.type="{0}"'.format(metric_type),
        view='HEADERS',
        fields='timeSeries.resource.type',
        interval_startTime=get_start_time(),
        interval_endTime=get_now_rfc3339())
    response = request.execute()
    if u'nextPageToken' in response:
        print "RESULTS ARE INCOMPLETE."
    if u'timeSeries' not in response:
        return 0
    timeseries_list = response[u'timeSeries']
    # pprint.pprint(response)
    return len(timeseries_list)


def detail_time_series(client, project_name, metric_type):
    """Prints details on the time series in 'metric_type'.
    """
    request = client.projects().timeSeries().list(
        name=project_name,
        filter='metric.type="{0}"'.format(metric_type),
        fields='timeSeries.resource.type,timeSeries.metricKind,timeSeries.metric.labels,timeSeries.points',
        interval_startTime=get_start_time(),
        interval_endTime=get_now_rfc3339())
    response = request.execute()
    if u'nextPageToken' in response:
        print "RESULTS ARE INCOMPLETE."
    pprint.pprint(response)
    timeseries_list = response[u'timeSeries']
    return len(timeseries_list)


def show_metric_stats():
    """Prints statistics of numbers of groups, services, metrics.
    """
    metric_cnt = 0
    for g in sorted(group_set):
        metric_cnt_in_group = 0

        for s in sorted(service_set[g]):
            metric_cnt_in_service = 0
            gs = '{0}/{1}'.format(g, s)

            # Metric count in this service.
            n = len(metric_set[gs])
            print 'Service',gs,'has',n,'metrics'
            metric_cnt_in_group += n
            metric_cnt += n

        print 'Group',g,'has',len(service_set[g]),'services'
        print 'Group',g,'has',metric_cnt_in_group,'metrics'
        print

    print 'There are',metric_cnt,'total metrics'
    print 'There are', len(timeseries_set),'services with time series'
    pprint.pprint(timeseries_set)

# TEST_METRIC="logging.googleapis.com/log_entry_count"
TEST_METRIC="compute.googleapis.com/instance/cpu/utilization"

def main(project_id):
    project_resource = "projects/{0}".format(project_id)
    client = list_resources.get_client()
#    read_metric_descriptors(client, project_resource)
#    show_metric_stats()
    detail_time_series(client,project_resource, TEST_METRIC)
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
