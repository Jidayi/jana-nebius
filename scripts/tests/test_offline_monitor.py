"""Connection monitor of the offline job (ARC-17; the EVL-16 subset pulled forward to M0)."""

from jana_tools.offline import egress_attempts

LOG = """\
101   connect(3, {sa_family=AF_UNIX, sun_path="/run/user/1000/bus"}, 110) = 0
102   connect(4, {sa_family=AF_INET, sin_port=htons(8123), sin_addr=inet_addr("127.0.0.1")}, 16) = 0
103   connect(5, {sa_family=AF_INET6, sin6_port=htons(9000), sin6_flowinfo=htonl(0), \
inet_pton(AF_INET6, "::1", &sin6_addr), sin6_scope_id=0}, 28) = 0
104   connect(6, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("93.184.215.14")}, 16) \
= -1 ENETUNREACH (Network is unreachable)
105   sendto(7, "\\x12\\x34", 30, MSG_NOSIGNAL, {sa_family=AF_INET, sin_port=htons(53), \
sin_addr=inet_addr("127.0.0.53")}, 16) = 30
106   connect(8, {sa_family=AF_INET6, sin6_port=htons(443), sin6_flowinfo=htonl(0), \
inet_pton(AF_INET6, "2606:4700::1111", &sin6_addr), sin6_scope_id=0}, 28) = -1 ENETUNREACH
107   connect(9, {sa_family=AF_INET6, sin6_port=htons(80), sin6_flowinfo=htonl(0), \
inet_pton(AF_INET6, "::ffff:127.0.0.1", &sin6_addr), sin6_scope_id=0}, 28) = 0
108   connect(10, {sa_family=AF_NETLINK, nl_pid=0, nl_groups=00000000}, 12) = 0
"""


def test_monitor_flags_every_non_loopback_attempt_and_dns():
    assert egress_attempts(LOG) == [
        "104 connect 93.184.215.14:443",
        "105 sendto 127.0.0.53:53",
        "106 connect 2606:4700::1111:443",
    ]


def test_monitor_passes_loopback_only_log():
    loopback_only = "\n".join(line for line in LOG.splitlines() if line.startswith(("101", "102", "103", "107", "108")))
    assert egress_attempts(loopback_only) == []
