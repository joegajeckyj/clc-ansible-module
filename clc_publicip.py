#!/usr/bin/python

import sys
import os
import datetime
import json
from ansible.module_utils.basic import *
#
#  Requires the clc-python-sdk.
#  sudo pip install clc-sdk
#
try:
    import clc as clc_sdk
    from clc import CLCException
except ImportError:
    clc_found = False
    clc_sdk = None
else:
    clc_found = True


class ClcPublicIp(object):
    clc = clc_sdk
    module = None
    group_dict = {}


    def __init__(self, module):
        self.module = module
        if not clc_found:
            self.module.fail_json(msg='clc-python-sdk required for this module')


    def process_request(self, params):
        self.set_clc_credentials_from_env()
        p = params
        server_ids = p['server_ids']
        ports = p['ports']
        protocol = p['protocol']
        state = p['state']
        command_list = []

        if state == 'present':
            command_list.append(lambda: self.ip_create_command(server_ids=server_ids
                                                               , protocol=protocol
                                                               , ports=ports))
        elif state == 'absent':
            command_list.append(lambda: self.ip_delete_command(server_ids=server_ids))
        else:
            return self.module.fail_json(msg="Unknown State: " + state)

        has_made_changes, result_servers, result_server_ids = self.run_clc_commands(command_list)
        return self.module.exit_json(changed=has_made_changes, servers=result_servers, server_ids=result_server_ids)


    def run_clc_commands(self, command_list):
        requests_list   = []
        changed_servers = []
        for command in command_list:
            requests, servers = command()
            requests_list += requests
            changed_servers += servers

        self._wait_for_requests_to_complete(requests_list)
        changed_server_ids, changed_servers = self._refresh_server_public_ips(changed_servers)
        has_made_changes, result_changed_servers             = self._parse_server_results(changed_servers)
        return has_made_changes, result_changed_servers, changed_server_ids


    def ip_create_command(self, server_ids, protocol, ports):
        servers           = self._get_servers_from_clc_api(server_ids, 'Failed to obtain server list from the CLC API')
        servers_to_change = [server for server in servers if len(server.PublicIPs().public_ips) == 0]
        ports_to_expose         = [{'protocol': protocol, 'port': port} for port in ports]
        return [server.PublicIPs().Add(ports_to_expose) for server in servers_to_change], servers_to_change


    def ip_delete_command(self, server_ids):
        servers           = self._get_servers_from_clc_api(server_ids, 'Failed to obtain server list from the CLC API')
        servers_to_change = [server for server in servers if len(server.PublicIPs().public_ips) > 0]

        ips_to_delete = []
        for server in servers_to_change:
            for ip in server.PublicIPs().public_ips:
                ips_to_delete.append(ip)

        return [ip.Delete() for ip in ips_to_delete], servers_to_change


    def _wait_for_requests_to_complete(self, requests_lst, action='create'):
        for request in requests_lst:
            request.WaitUntilComplete()
            for request_details in request.requests:
                if request_details.Status() != 'succeeded':
                    self.module.fail_json(msg='Unable to ' + action + ' Public IP for '
                                              + request.server.id + ': ' + request.Status())


    def _refresh_server_public_ips(self, servers_to_refresh):
        refreshed_server_ids = [server.id for server in servers_to_refresh]
        refreshed_servers    = self._get_servers_from_clc_api(refreshed_server_ids,
                                                             'Failed to refresh server list from CLC API')
        return refreshed_server_ids, refreshed_servers


    @staticmethod
    def _parse_server_results(servers):
        servers_result = []
        changed = False
        for server in servers:
            hasPublicIp = len(server.PublicIPs().public_ips) > 0
            if hasPublicIp:
                changed = True
                public_ip = str(server.PublicIPs().public_ips[0].id)
                internal_ip = str(server.PublicIPs().public_ips[0].internal)
                server.data['public_ip'] = public_ip
                server.data['internal_ip'] = internal_ip
            ipaddress = server.data['details']['ipAddresses'][0]['internal']
            server.data['ipaddress'] = ipaddress
            servers_result.append(server.data)
        return changed, servers_result


    def _get_servers_from_clc_api(self, server_ids, message):
        try:
            return self.clc.v2.Servers(server_ids).servers
        except CLCException, e:
            self.module.fail_json(msg=message +': %s' % e)


    @staticmethod
    def define_argument_spec():
        argument_spec = dict(
            server_ids=dict(type='list', required=True),
            protocol=dict(default='TCP'),
            ports=dict(type='list'),
            state=dict(default='present', choices=['present', 'absent']),
            )
        return argument_spec


    def set_clc_credentials_from_env(self):
            e = os.environ
            v2_api_passwd = None
            v2_api_username = None
            try:
                v2_api_username = e['CLC_V2_API_USERNAME']
                v2_api_passwd = e['CLC_V2_API_PASSWD']
            except KeyError, e:
                return self.module.fail_json(msg = "You must set the CLC_V2_API_USERNAME and CLC_V2_API_PASSWD environment variables")

            self.clc.v2.SetCredentials(api_username=v2_api_username, api_passwd=v2_api_passwd)


def main():
    module = AnsibleModule(
        argument_spec=ClcPublicIp.define_argument_spec()
    )
    clcPublicIp = ClcPublicIp(module)
    clcPublicIp.process_request(module.params)


if __name__ == '__main__':
    main()