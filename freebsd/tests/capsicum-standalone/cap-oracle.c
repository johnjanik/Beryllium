/*
 * cap-oracle: Capsicum kernel behaviour oracle and red-team probe set for
 * Beryllium.
 *
 * Records what the running FreeBSD kernel actually allows a process in
 * capability mode to do. No Chromium involved. Output is one JSON document
 * on stdout; a human summary goes to stderr.
 *
 * Every probe runs in its own forked child, so one probe's cap_enter(),
 * rlimits or crashes cannot affect another. Values of sensitive sysctls
 * (host UUID, hostname, ...) are never printed: only whether they could be
 * read and how many bytes came back.
 *
 * Design references: plan/08-TESTING-AND-VERIFICATION.md section 2.1 and
 * plan/12-WORK-PLAN-AND-RED-TEAM.md sections 5 and 6.2.
 *
 * Run as an ordinary (non-root) user. Root bypasses several of the limits
 * being measured (RLIMIT_NPROC, ptrace permission checks).
 *
 * SPDX-License-Identifier: GPL-3.0-only
 */

#include <sys/param.h>
#include <sys/capsicum.h>
#include <sys/event.h>
#include <sys/ipc.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/procctl.h>
#include <sys/procdesc.h>
#include <sys/ptrace.h>
#include <sys/resource.h>
#include <sys/shm.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/thr.h>
#include <sys/time.h>
#include <sys/un.h>
#include <sys/user.h>
#include <sys/utsname.h>
#include <sys/wait.h>

#include <net/if.h>
#include <net/if_dl.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netlink/netlink.h>
#include <netlink/netlink_route.h>

#include <capsicum_helpers.h>
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <kenv.h>
#include <netdb.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define ORACLE_VERSION	2
#define PROBE_TIMEOUT	10	/* seconds per probe child */

/* ------------------------------------------------------------------ */
/* Probe model                                                          */
/* ------------------------------------------------------------------ */

enum expect {
	EXP_DENY,	/* secure expectation: the action is refused */
	EXP_ALLOW,	/* functional requirement: the design needs it to work */
	EXP_RECORD,	/* no expectation; record the kernel's behaviour */
};

enum outcome {
	OUT_ALLOWED = 1,
	OUT_DENIED,
	OUT_SETUP_ERROR,	/* the probe could not set itself up */
};

struct presult {
	int	outcome;
	int	err;
	char	detail[480];
};

typedef int (*pre_fn)(struct presult *);	/* before cap_enter; nonzero = setup error */
typedef void (*probe_fn)(struct presult *);

struct probe {
	const char	*id;
	const char	*rt;		/* red-team finding or spec reference */
	const char	*area;
	const char	*desc;
	enum expect	 expect;
	bool		 capmode;	/* cap_enter() before fn */
	pre_fn		 pre;
	probe_fn	 fn;
};

/* ------------------------------------------------------------------ */
/* Fixture shared by all probes (set up by the parent before forking)   */
/* ------------------------------------------------------------------ */

static struct {
	char	tmpdir[PATH_MAX];
	char	canary_abs[PATH_MAX];
	char	sock_abs[PATH_MAX];
	int	dirfd;
	int	listen_unix;
	pid_t	sleeper;		/* unrelated same-user process, stands in for the browser */
	pid_t	sleeper_notrace;	/* same, with PROC_TRACE_CTL_DISABLE applied */
	char	shm_name[64];
	char	self_path[PATH_MAX];	/* this binary, for re-exec probes */
} fx = { .dirfd = -1, .listen_unix = -1 };

/* ------------------------------------------------------------------ */
/* Small helpers                                                        */
/* ------------------------------------------------------------------ */

static const char *
errname(int e)
{
	static char buf[16];

	switch (e) {
	case 0: return ("0");
	case ECAPMODE: return ("ECAPMODE");
	case ENOTCAPABLE: return ("ENOTCAPABLE");
	case EPERM: return ("EPERM");
	case EACCES: return ("EACCES");
	case ENOENT: return ("ENOENT");
	case EAGAIN: return ("EAGAIN");
	case EINVAL: return ("EINVAL");
	case ENOSYS: return ("ENOSYS");
	case EBADF: return ("EBADF");
	case ESRCH: return ("ESRCH");
	case EAFNOSUPPORT: return ("EAFNOSUPPORT");
	case EPROTONOSUPPORT: return ("EPROTONOSUPPORT");
	case ENOTTY: return ("ENOTTY");
	case EOPNOTSUPP: return ("EOPNOTSUPP");
	case EFAULT: return ("EFAULT");
	case ENOMEM: return ("ENOMEM");
	case ENOTDIR: return ("ENOTDIR");
	case ELOOP: return ("ELOOP");
	case ECONNREFUSED: return ("ECONNREFUSED");
	case EINTR: return ("EINTR");
	case EBUSY: return ("EBUSY");
	case EEXIST: return ("EEXIST");
	case EPROTOTYPE: return ("EPROTOTYPE");
	default:
		snprintf(buf, sizeof(buf), "E%d", e);
		return (buf);
	}
}

static void
res(struct presult *r, bool allowed, int err, const char *fmt, ...)
{
	va_list ap;

	r->outcome = allowed ? OUT_ALLOWED : OUT_DENIED;
	r->err = allowed ? 0 : err;
	if (fmt != NULL) {
		va_start(ap, fmt);
		vsnprintf(r->detail, sizeof(r->detail), fmt, ap);
		va_end(ap);
	}
}

static void
setup_error(struct presult *r, const char *what, int err)
{
	r->outcome = OUT_SETUP_ERROR;
	r->err = err;
	snprintf(r->detail, sizeof(r->detail), "setup failed: %s", what);
}

/* Record the result of a call that returns a descriptor (or -1). */
static void
res_fd(struct presult *r, int fd)
{
	int e = errno;

	if (fd >= 0) {
		close(fd);
		res(r, true, 0, NULL);
	} else {
		res(r, false, e, NULL);
	}
}

/* Record the result of a call that returns 0 / -1. */
static void
res_rc(struct presult *r, int rc)
{
	int e = errno;

	res(r, rc != -1, e, NULL);
}

static int
limited_dup(int fd, cap_rights_t *rights)
{
	int d;

	d = dup(fd);
	if (d < 0)
		return (-1);
	if (cap_rights_limit(d, rights) != 0) {
		close(d);
		return (-1);
	}
	return (d);
}

/* ------------------------------------------------------------------ */
/* Files and directories                                                */
/* ------------------------------------------------------------------ */

static void
p_open_etc_passwd(struct presult *r)
{
	res_fd(r, open("/etc/passwd", O_RDONLY));
}

static void
p_open_canary_abs(struct presult *r)
{
	res_fd(r, open(fx.canary_abs, O_RDONLY));
}

static void
p_open_create_tmp(struct presult *r)
{
	char path[PATH_MAX];

	snprintf(path, sizeof(path), "%s/created-in-capmode", fx.tmpdir);
	res_fd(r, open(path, O_CREAT | O_WRONLY, 0600));
}

static void
p_openat_cwd(struct presult *r)
{
	res_fd(r, openat(AT_FDCWD, fx.canary_abs, O_RDONLY));
}

static int
dir_ro(void)
{
	cap_rights_t rights;

	cap_rights_init(&rights, CAP_LOOKUP, CAP_READ, CAP_FSTAT);
	return (limited_dup(fx.dirfd, &rights));
}

static void
p_openat_beneath(struct presult *r)
{
	int d = dir_ro();

	if (d < 0) {
		setup_error(r, "limited dirfd", errno);
		return;
	}
	res_fd(r, openat(d, "sub/inner", O_RDONLY));
}

static void
p_openat_dotdot(struct presult *r)
{
	int d = dir_ro();

	if (d < 0) {
		setup_error(r, "limited dirfd", errno);
		return;
	}
	res_fd(r, openat(d, "..", O_RDONLY | O_DIRECTORY));
}

static void
p_openat_absolute(struct presult *r)
{
	int d = dir_ro();

	if (d < 0) {
		setup_error(r, "limited dirfd", errno);
		return;
	}
	res_fd(r, openat(d, "/etc/passwd", O_RDONLY));
}

static void
p_openat_symlink_out(struct presult *r)
{
	int d = dir_ro();

	if (d < 0) {
		setup_error(r, "limited dirfd", errno);
		return;
	}
	res_fd(r, openat(d, "link_out", O_RDONLY));
}

static void
p_openat_write_on_ro(struct presult *r)
{
	int d = dir_ro();

	if (d < 0) {
		setup_error(r, "limited dirfd", errno);
		return;
	}
	res_fd(r, openat(d, "canary", O_WRONLY));
}

static void
p_open_dev_null(struct presult *r)
{
	res_fd(r, open("/dev/null", O_RDWR));
}

/* ------------------------------------------------------------------ */
/* Network                                                              */
/* ------------------------------------------------------------------ */

static void
p_socket_generic(struct presult *r, int dom, int type, int proto)
{
	int s = socket(dom, type, proto);

	res_fd(r, s);
}

static void p_socket_inet_stream(struct presult *r) { p_socket_generic(r, AF_INET, SOCK_STREAM, 0); }
static void p_socket_inet_dgram(struct presult *r) { p_socket_generic(r, AF_INET, SOCK_DGRAM, 0); }
static void p_socket_inet6_stream(struct presult *r) { p_socket_generic(r, AF_INET6, SOCK_STREAM, 0); }
static void p_socket_unix(struct presult *r) { p_socket_generic(r, AF_UNIX, SOCK_STREAM, 0); }
static void p_socket_route(struct presult *r) { p_socket_generic(r, PF_ROUTE, SOCK_RAW, AF_UNSPEC); }
static void p_socket_netlink(struct presult *r) { p_socket_generic(r, AF_NETLINK, SOCK_RAW, NETLINK_ROUTE); }

static void
loopback(struct sockaddr_in *sin, uint16_t port)
{
	memset(sin, 0, sizeof(*sin));
	sin->sin_len = sizeof(*sin);
	sin->sin_family = AF_INET;
	sin->sin_port = htons(port);
	sin->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
}

static void
p_connect_inet(struct presult *r)
{
	struct sockaddr_in sin;
	int s;

	s = socket(AF_INET, SOCK_STREAM, 0);
	if (s < 0) {
		setup_error(r, "socket", errno);
		return;
	}
	loopback(&sin, 9);
	res_rc(r, connect(s, (struct sockaddr *)&sin, sizeof(sin)));
}

static void
p_bind_inet(struct presult *r)
{
	struct sockaddr_in sin;
	int s;

	s = socket(AF_INET, SOCK_STREAM, 0);
	if (s < 0) {
		setup_error(r, "socket", errno);
		return;
	}
	loopback(&sin, 0);
	res_rc(r, bind(s, (struct sockaddr *)&sin, sizeof(sin)));
}

static void
p_sendto_udp(struct presult *r)
{
	struct sockaddr_in sin;
	ssize_t n;
	int s, e;

	s = socket(AF_INET, SOCK_DGRAM, 0);
	if (s < 0) {
		setup_error(r, "socket", errno);
		return;
	}
	loopback(&sin, 9);
	n = sendto(s, "x", 1, 0, (struct sockaddr *)&sin, sizeof(sin));
	e = errno;
	res(r, n == 1, e, NULL);
}

/* An Internet socket connected before cap_enter keeps working afterwards. */
static int preconnected_tcp = -1;

static int
pre_tcp_pair(struct presult *r)
{
	struct sockaddr_in sin;
	socklen_t len = sizeof(sin);
	int l, c, a;

	l = socket(AF_INET, SOCK_STREAM, 0);
	loopback(&sin, 0);
	if (l < 0 || bind(l, (struct sockaddr *)&sin, sizeof(sin)) != 0 ||
	    listen(l, 1) != 0 ||
	    getsockname(l, (struct sockaddr *)&sin, &len) != 0) {
		setup_error(r, "tcp listener", errno);
		return (1);
	}
	c = socket(AF_INET, SOCK_STREAM, 0);
	if (c < 0 || connect(c, (struct sockaddr *)&sin, sizeof(sin)) != 0) {
		setup_error(r, "tcp connect", errno);
		return (1);
	}
	a = accept(l, NULL, NULL);
	if (a < 0) {
		setup_error(r, "tcp accept", errno);
		return (1);
	}
	preconnected_tcp = c;
	return (0);
}

static void
p_preconnected_tcp_send(struct presult *r)
{
	ssize_t n = send(preconnected_tcp, "x", 1, 0);
	int e = errno;

	res(r, n == 1, e, "an Internet socket opened before cap_enter keeps its network authority");
}

static void
p_connect_unix_path(struct presult *r)
{
	struct sockaddr_un sun;
	int s;

	s = socket(AF_UNIX, SOCK_STREAM, 0);
	if (s < 0) {
		setup_error(r, "socket", errno);
		return;
	}
	memset(&sun, 0, sizeof(sun));
	sun.sun_family = AF_UNIX;
	strlcpy(sun.sun_path, fx.sock_abs, sizeof(sun.sun_path));
	sun.sun_len = SUN_LEN(&sun);
	res_rc(r, connect(s, (struct sockaddr *)&sun, sun.sun_len));
}

static void
connectat_with(struct presult *r, bool with_connectat)
{
	struct sockaddr_un sun;
	cap_rights_t rights;
	int d, s;

	if (with_connectat)
		cap_rights_init(&rights, CAP_LOOKUP, CAP_CONNECTAT);
	else
		cap_rights_init(&rights, CAP_LOOKUP, CAP_READ);
	d = limited_dup(fx.dirfd, &rights);
	s = socket(AF_UNIX, SOCK_STREAM, 0);
	if (d < 0 || s < 0) {
		setup_error(r, "dirfd or socket", errno);
		return;
	}
	memset(&sun, 0, sizeof(sun));
	sun.sun_family = AF_UNIX;
	strlcpy(sun.sun_path, "sock", sizeof(sun.sun_path));
	sun.sun_len = SUN_LEN(&sun);
	res_rc(r, connectat(d, s, (struct sockaddr *)&sun, sun.sun_len));
}

static void p_connectat_cap(struct presult *r) { connectat_with(r, true); }
static void p_connectat_nocap(struct presult *r) { connectat_with(r, false); }

static void
p_getifaddrs(struct presult *r)
{
	struct ifaddrs *ifa, *i;
	int inet = 0, inet6 = 0, link = 0, e;

	if (getifaddrs(&ifa) != 0) {
		e = errno;
		res(r, false, e, NULL);
		return;
	}
	for (i = ifa; i != NULL; i = i->ifa_next) {
		if (i->ifa_addr == NULL || (i->ifa_flags & IFF_LOOPBACK))
			continue;
		switch (i->ifa_addr->sa_family) {
		case AF_INET: inet++; break;
		case AF_INET6: inet6++; break;
		case AF_LINK:
			if (((struct sockaddr_dl *)i->ifa_addr)->sdl_alen > 0)
				link++;
			break;
		}
	}
	freeifaddrs(ifa);
	/* Counts only: the addresses themselves are never printed. */
	res(r, inet + inet6 + link > 0, ENOENT,
	    "non-loopback inet=%d inet6=%d link-layer-addresses=%d",
	    inet, inet6, link);
}

static void
p_netlink_getaddr(struct presult *r)
{
	struct {
		struct nlmsghdr hdr;
		struct ifaddrmsg ifa;
	} req;
	struct timeval tv = { 2, 0 };
	char buf[16384];
	int s, e, addrs = 0;
	bool done = false;
	ssize_t n;

	s = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
	if (s < 0) {
		e = errno;
		res(r, false, e, "netlink socket refused (module may not be loaded)");
		return;
	}
	(void)setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
	memset(&req, 0, sizeof(req));
	req.hdr.nlmsg_len = sizeof(req);
	req.hdr.nlmsg_type = RTM_GETADDR;
	req.hdr.nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
	req.hdr.nlmsg_seq = 1;
	if (send(s, &req, sizeof(req), 0) < 0) {
		e = errno;
		res(r, false, e, "netlink send refused");
		return;
	}
	while (!done && (n = recv(s, buf, sizeof(buf), 0)) > 0) {
		size_t off = 0;

		/*
		 * Walk the messages by hand: the NLMSG_OK/NLMSG_NEXT macros
		 * change signedness between 14.x and 16 headers.
		 */
		while (off + sizeof(struct nlmsghdr) <= (size_t)n) {
			struct nlmsghdr *h = (struct nlmsghdr *)(void *)(buf + off);

			if (h->nlmsg_len < sizeof(*h) || off + h->nlmsg_len > (size_t)n)
				break;
			if (h->nlmsg_type == NLMSG_DONE ||
			    h->nlmsg_type == NLMSG_ERROR) {
				done = true;
				break;
			}
			if (h->nlmsg_type == RTM_NEWADDR)
				addrs++;
			off += (h->nlmsg_len + 3u) & ~3u;
		}
	}
	res(r, addrs > 0, EAGAIN, "address records received=%d", addrs);
}

static void
p_getaddrinfo(struct presult *r)
{
	struct addrinfo hints, *ai = NULL;
	int rc;

	memset(&hints, 0, sizeof(hints));
	hints.ai_family = AF_UNSPEC;
	hints.ai_socktype = SOCK_STREAM;
	rc = getaddrinfo("localhost", "80", &hints, &ai);
	if (rc == 0) {
		freeaddrinfo(ai);
		res(r, true, 0, NULL);
	} else {
		res(r, false, 0, "%s", gai_strerror(rc));
	}
}

/* ------------------------------------------------------------------ */
/* Identity: sysctls readable from capability mode                      */
/* ------------------------------------------------------------------ */

/*
 * Each identity probe resolves its MIB before cap_enter (name lookup is
 * not what is being tested) and reads the node afterwards. Values are not
 * reported, only success and size.
 */
static int id_mib[CTL_MAXNAME];
static size_t id_miblen;

static int
resolve_mib(struct presult *r, const char *name, pid_t suffix)
{
	id_miblen = CTL_MAXNAME;
	if (sysctlnametomib(name, id_mib, &id_miblen) != 0) {
		setup_error(r, name, errno);
		snprintf(r->detail, sizeof(r->detail),
		    "node %s does not exist on this kernel", name);
		return (1);
	}
	if (suffix > 0)
		id_mib[id_miblen++] = suffix;
	return (0);
}

static void
read_mib(struct presult *r)
{
	char buf[65536];
	size_t len = sizeof(buf);
	int rc, e;

	rc = sysctl(id_mib, (u_int)id_miblen, buf, &len, NULL, 0);
	e = errno;
	if (rc == 0)
		res(r, true, 0, "readable, %zu bytes (value not recorded)", len);
	else if (e == ENOMEM)
		res(r, true, 0, "readable, larger than %zu bytes", sizeof(buf));
	else
		res(r, false, e, NULL);
}

#define ID_PRE(fn, name, suffix)					\
	static int fn(struct presult *r) { return (resolve_mib(r, name, suffix)); }

ID_PRE(pre_hostuuid, "kern.hostuuid", 0)
ID_PRE(pre_hostid, "kern.hostid", 0)
ID_PRE(pre_hostname, "kern.hostname", 0)
ID_PRE(pre_domainname, "kern.domainname", 0)
ID_PRE(pre_boot_id, "kern.boot_id", 0)
ID_PRE(pre_hw_model, "hw.model", 0)
ID_PRE(pre_hw_physmem, "hw.physmem", 0)
ID_PRE(pre_hw_ncpu, "hw.ncpu", 0)
ID_PRE(pre_page_count, "vm.stats.vm.v_page_count", 0)
ID_PRE(pre_osrelease, "kern.osrelease", 0)

static int pre_proc_self(struct presult *r) { return (resolve_mib(r, "kern.proc.pid", getpid())); }
static int pre_proc_other(struct presult *r) { return (resolve_mib(r, "kern.proc.pid", fx.sleeper)); }
static int pre_args_other(struct presult *r) { return (resolve_mib(r, "kern.proc.args", fx.sleeper)); }

static void
p_kenv_smbios(struct presult *r)
{
	char buf[128];
	int rc, e;

	rc = kenv(KENV_GET, "smbios.system.uuid", buf, sizeof(buf));
	e = errno;
	res(r, rc >= 0, e, rc >= 0 ? "readable (value not recorded)" : NULL);
}

static void
p_uname(struct presult *r)
{
	struct utsname u;
	int rc, e;

	rc = uname(&u);
	e = errno;
	/* sysname and machine are what navigator.platform would expose. */
	res(r, rc == 0, e, rc == 0 ? "sysname=%s machine=%s" : NULL,
	    u.sysname, u.machine);
}

/*
 * Sweep: enumerate every sysctl node from inside capability mode and report
 * the names of leaves that can actually be read. Written as text lines to
 * the result pipe (special-cased by the runner).
 */
static int sweep_fd = -1;

static bool
oidfmt_is_node(const int *oid, size_t len)
{
	int q[CTL_MAXNAME + 2];
	char buf[BUFSIZ];
	size_t l = sizeof(buf);
	u_int kind;

	q[0] = CTL_SYSCTL;
	q[1] = CTL_SYSCTL_OIDFMT;
	memcpy(q + 2, oid, len * sizeof(int));
	if (sysctl(q, (u_int)(len + 2), buf, &l, NULL, 0) != 0)
		return (true);	/* unknown: skip it */
	memcpy(&kind, buf, sizeof(kind));
	return ((kind & CTLTYPE) == CTLTYPE_NODE);
}

static void
p_sysctl_sweep(struct presult *r)
{
	int oid[CTL_MAXNAME], next[CTL_MAXNAME], q[CTL_MAXNAME + 2];
	size_t len = 0, l;
	int readable = 0, capdenied = 0, eperm = 0, other = 0, visited = 0;
	char name[1024], line[1100];
	char *buf = NULL;
	size_t bufsz = 0;

	for (;;) {
		q[0] = CTL_SYSCTL;
		q[1] = CTL_SYSCTL_NEXT;
		memcpy(q + 2, oid, len * sizeof(int));
		l = sizeof(next);
		if (sysctl(q, (u_int)(len + 2), next, &l, NULL, 0) != 0)
			break;
		len = l / sizeof(int);
		memcpy(oid, next, l);
		if (++visited > 200000)
			break;

		q[1] = CTL_SYSCTL_NAME;
		memcpy(q + 2, oid, len * sizeof(int));
		l = sizeof(name);
		if (sysctl(q, (u_int)(len + 2), name, &l, NULL, 0) != 0)
			continue;
		/* debug.* handlers are not meant for routine reads. */
		if (strncmp(name, "debug.", 6) == 0)
			continue;
		if (oidfmt_is_node(oid, len))
			continue;

		/*
		 * A size-only query (no buffer) is allowed even for nodes that
		 * are not CTLFLAG_CAPRD, so always read with a real buffer.
		 */
		l = 0;
		(void)sysctl(oid, (u_int)len, NULL, &l, NULL, 0);
		l += 4096;
		if (l > 4 * 1024 * 1024)
			l = 4 * 1024 * 1024;
		if (l > bufsz) {
			free(buf);
			bufsz = l;
			buf = malloc(bufsz);
			if (buf == NULL) {
				bufsz = 0;
				continue;
			}
		}
		if (sysctl(oid, (u_int)len, buf, &l, NULL, 0) == 0 ||
		    errno == ENOMEM) {
			readable++;
			snprintf(line, sizeof(line), "%s\n", name);
			(void)write(sweep_fd, line, strlen(line));
		} else if (errno == ECAPMODE) {
			capdenied++;
		} else if (errno == EPERM) {
			eperm++;
		} else {
			other++;
		}
	}
	free(buf);
	snprintf(line, sizeof(line),
	    "#summary readable=%d ecapmode=%d eperm=%d other=%d\n",
	    readable, capdenied, eperm, other);
	(void)write(sweep_fd, line, strlen(line));
	res(r, readable > 0, 0, NULL);
}

/* ------------------------------------------------------------------ */
/* Processes and signals                                                */
/* ------------------------------------------------------------------ */

static void
p_kill_other(struct presult *r)
{
	res_rc(r, kill(fx.sleeper, 0));
}

static void
p_kill_self(struct presult *r)
{
	res_rc(r, kill(getpid(), 0));
}

static void
p_sigqueue_other(struct presult *r)
{
	union sigval v = { .sival_int = 0 };
	int rc = sigqueue(fx.sleeper, 0, v);
	int e = errno;

	res(r, rc == 0, e, "FreeBSD-SA-26:28.capsicum regression check");
}

static void
p_thr_kill2_other(struct presult *r)
{
	res_rc(r, thr_kill2(fx.sleeper, -1, 0));
}

static void
ptrace_attempt(struct presult *r, pid_t target)
{
	int rc, e, st;

	rc = ptrace(PT_ATTACH, target, NULL, 0);
	e = errno;
	if (rc == 0) {
		/* Clean up: wait for the stop, then detach and resume. */
		(void)waitpid(target, &st, 0);
		(void)ptrace(PT_DETACH, target, (caddr_t)1, 0);
	}
	res(r, rc == 0, e, NULL);
}

static void p_ptrace_other(struct presult *r) { ptrace_attempt(r, fx.sleeper); }
static void p_ptrace_notrace_target(struct presult *r) { ptrace_attempt(r, fx.sleeper_notrace); }

static void
kevent_proc(struct presult *r, pid_t target)
{
	struct kevent kev;
	int kq, rc, e;

	kq = kqueue();
	if (kq < 0) {
		setup_error(r, "kqueue", errno);
		return;
	}
	EV_SET(&kev, target, EVFILT_PROC, EV_ADD, NOTE_EXIT | NOTE_FORK | NOTE_EXEC, 0, NULL);
	rc = kevent(kq, &kev, 1, NULL, 0, NULL);
	e = errno;
	res(r, rc == 0, e, NULL);
}

static void p_kevent_proc_other(struct presult *r) { kevent_proc(r, fx.sleeper); }
static void p_kevent_proc_init(struct presult *r) { kevent_proc(r, 1); }

static void
p_getpriority_user(struct presult *r)
{
	int rc, e;

	errno = 0;
	rc = getpriority(PRIO_USER, getuid());
	e = errno;
	res(r, !(rc == -1 && e != 0), e, NULL);
}

static void
p_getpriority_other(struct presult *r)
{
	int rc, e;

	errno = 0;
	rc = getpriority(PRIO_PROCESS, fx.sleeper);
	e = errno;
	res(r, !(rc == -1 && e != 0), e, NULL);
}

static int sleeper_nice;

static int
pre_sleeper_nice(struct presult *r)
{
	errno = 0;
	sleeper_nice = getpriority(PRIO_PROCESS, fx.sleeper);
	if (sleeper_nice == -1 && errno != 0) {
		setup_error(r, "getpriority before cap_enter", errno);
		return (1);
	}
	return (0);
}

static void
p_setpriority_other(struct presult *r)
{
	int target = sleeper_nice < PRIO_MAX ? sleeper_nice + 1 : sleeper_nice;

	/* Unprivileged users can only lower priority; this cannot harm the sleeper. */
	res_rc(r, setpriority(PRIO_PROCESS, fx.sleeper, target));
}

static void
p_procctl_capmode(struct presult *r)
{
	int status;

	res_rc(r, procctl(P_PID, getpid(), PROC_TRACE_STATUS, &status));
}

static void
p_fork(struct presult *r)
{
	pid_t p = fork();
	int e = errno, st;

	if (p == 0)
		_exit(0);
	if (p > 0)
		(void)waitpid(p, &st, 0);
	res(r, p > 0, e, NULL);
}

static int
pre_nproc_1(struct presult *r)
{
	struct rlimit rl = { 1, 1 };

	if (setrlimit(RLIMIT_NPROC, &rl) != 0) {
		setup_error(r, "setrlimit(RLIMIT_NPROC)", errno);
		return (1);
	}
	return (0);
}

static void
p_fork_nproc1(struct presult *r)
{
	p_fork(r);
	snprintf(r->detail, sizeof(r->detail),
	    "RLIMIT_NPROC=1 set in this process only before cap_enter");
}

static void
p_fork_inherits_capmode(struct presult *r)
{
	int pfd[2], st;
	u_int mode = 0;
	pid_t p;

	if (pipe(pfd) != 0) {
		setup_error(r, "pipe", errno);
		return;
	}
	p = fork();
	if (p == 0) {
		u_int m = 0;

		(void)cap_getmode(&m);
		(void)write(pfd[1], &m, sizeof(m));
		_exit(0);
	}
	if (p < 0) {
		setup_error(r, "fork", errno);
		return;
	}
	close(pfd[1]);
	if (read(pfd[0], &mode, sizeof(mode)) != sizeof(mode))
		mode = 0;
	(void)waitpid(p, &st, 0);
	res(r, mode == 1, EINVAL, "child cap_getmode=%u", mode);
}

static void
p_pdfork_pdkill(struct presult *r)
{
	int pd, rc, e;
	pid_t p;

	p = pdfork(&pd, 0);
	if (p == 0) {
		for (;;)
			pause();
	}
	if (p < 0) {
		e = errno;
		res(r, false, e, "pdfork refused");
		return;
	}
	rc = pdkill(pd, SIGKILL);
	e = errno;
	res(r, rc == 0, e, NULL);
}

static void
p_execve(struct presult *r)
{
	char *argv[] = { "/bin/sh", "-c", "exit 0", NULL };
	char *envp[] = { NULL };
	int pfd[2], err = 0, st;
	ssize_t n;
	pid_t p;

	/*
	 * Exec in a grandchild so a successful exec cannot swallow the
	 * result. The pipe is close-on-exec: no data means exec succeeded.
	 */
	if (pipe2(pfd, O_CLOEXEC) != 0) {
		setup_error(r, "pipe2", errno);
		return;
	}
	p = fork();
	if (p == 0) {
		execve("/bin/sh", argv, envp);
		err = errno;
		(void)write(pfd[1], &err, sizeof(err));
		_exit(127);
	}
	if (p < 0) {
		setup_error(r, "fork", errno);
		return;
	}
	close(pfd[1]);
	n = read(pfd[0], &err, sizeof(err));
	(void)waitpid(p, &st, 0);
	res(r, n == 0, err, NULL);
}

static void
p_dlopen(struct presult *r)
{
	void *h = dlopen("libz.so.6", RTLD_NOW);
	const char *msg = h == NULL ? dlerror() : NULL;

	res(r, h != NULL, 0, "%s", msg != NULL ? msg : "");
}

static void
p_dlopen_control(struct presult *r)
{
	p_dlopen(r);
	if (r->outcome == OUT_ALLOWED)
		snprintf(r->detail, sizeof(r->detail),
		    "library loads outside capability mode");
}

static void
p_posix_openpt(struct presult *r)
{
	res_fd(r, posix_openpt(O_RDWR | O_NOCTTY));
}

/* ------------------------------------------------------------------ */
/* Memory and shared memory                                             */
/* ------------------------------------------------------------------ */

static void
p_shm_anon(struct presult *r)
{
	res_fd(r, shm_open(SHM_ANON, O_RDWR, 0600));
}

static void
p_memfd_seal(struct presult *r)
{
	int fd, e;

	fd = memfd_create("beryllium-oracle", MFD_ALLOW_SEALING);
	if (fd < 0) {
		e = errno;
		res(r, false, e, "memfd_create refused");
		return;
	}
	if (ftruncate(fd, 4096) != 0 ||
	    fcntl(fd, F_ADD_SEALS, F_SEAL_SHRINK | F_SEAL_GROW) != 0) {
		e = errno;
		res(r, false, e, "ftruncate or F_ADD_SEALS refused");
		return;
	}
	res(r, true, 0, NULL);
}

static void
p_shm_named(struct presult *r)
{
	res_fd(r, shm_open(fx.shm_name, O_RDWR | O_CREAT | O_EXCL, 0600));
}

static void
p_sysv_shmget(struct presult *r)
{
	int id = shmget(IPC_PRIVATE, 4096, IPC_CREAT | 0600);
	int e = errno;

	if (id >= 0)
		(void)shmctl(id, IPC_RMID, NULL);
	res(r, id >= 0, e, NULL);
}

/* A read-only twin of a shared-memory region, made read-only by rights. */
static int
ro_twin(struct presult *r, int *rw_out)
{
	cap_rights_t rights;
	int fd, d;

	fd = memfd_create("beryllium-oracle", 0);
	if (fd < 0 || ftruncate(fd, 4096) != 0) {
		setup_error(r, "memfd_create", errno);
		return (-1);
	}
	cap_rights_init(&rights, CAP_READ, CAP_MMAP_R, CAP_FSTAT, CAP_SEEK);
	d = limited_dup(fd, &rights);
	if (d < 0) {
		setup_error(r, "cap_rights_limit", errno);
		return (-1);
	}
	if (rw_out != NULL)
		*rw_out = fd;
	return (d);
}

static void
p_ro_twin_map_rw(struct presult *r)
{
	int d = ro_twin(r, NULL), e;
	void *p;

	if (d < 0)
		return;
	p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, d, 0);
	e = errno;
	res(r, p != MAP_FAILED, e, NULL);
}

static void
p_ro_twin_mprotect(struct presult *r)
{
	int d = ro_twin(r, NULL), rc, e;
	void *p;

	if (d < 0)
		return;
	p = mmap(NULL, 4096, PROT_READ, MAP_SHARED, d, 0);
	if (p == MAP_FAILED) {
		setup_error(r, "read-only mmap", errno);
		return;
	}
	rc = mprotect(p, 4096, PROT_READ | PROT_WRITE);
	e = errno;
	res(r, rc == 0, e, NULL);
}

static void
p_ro_twin_map_exec(struct presult *r)
{
	int d = ro_twin(r, NULL), e;
	void *p;

	if (d < 0)
		return;
	p = mmap(NULL, 4096, PROT_READ | PROT_EXEC, MAP_SHARED, d, 0);
	e = errno;
	res(r, p != MAP_FAILED, e, NULL);
}

static void
p_ro_twin_introspect(struct presult *r)
{
	cap_rights_t rights;
	int fd = -1, d, d2, fl, fl2, e;

	d = ro_twin(r, &fd);
	if (d < 0)
		return;
	fl = fcntl(d, F_GETFL);
	e = errno;
	if (cap_rights_get(d, &rights) != 0) {
		setup_error(r, "cap_rights_get", errno);
		return;
	}
	/* Same twin, but with CAP_FCNTL limited to F_GETFL. */
	cap_rights_init(&rights, CAP_READ, CAP_MMAP_R, CAP_FSTAT, CAP_SEEK, CAP_FCNTL);
	d2 = limited_dup(fd, &rights);
	if (d2 < 0 || cap_fcntls_limit(d2, CAP_FCNTL_GETFL) != 0) {
		setup_error(r, "twin with CAP_FCNTL", errno);
		return;
	}
	fl2 = fcntl(d2, F_GETFL);
	(void)cap_rights_get(d, &rights);
	res(r, true, 0,
	    "F_GETFL without CAP_FCNTL: %s; with CAP_FCNTL_GETFL: %s; "
	    "CAP_MMAP_W present=%s",
	    fl == -1 ? errname(e) : (fl & O_ACCMODE) == O_RDWR ? "O_RDWR" : "other",
	    fl2 == -1 ? "refused" : (fl2 & O_ACCMODE) == O_RDWR ? "O_RDWR" :
	    (fl2 & O_ACCMODE) == O_RDONLY ? "O_RDONLY" : "other",
	    cap_rights_is_set(&rights, CAP_MMAP_W) ? "yes" : "no");
}

static void
p_anon_jit(struct presult *r)
{
	void *p;
	int e;

	p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
	if (p == MAP_FAILED) {
		setup_error(r, "anonymous mmap", errno);
		return;
	}
	if (mprotect(p, 4096, PROT_READ | PROT_EXEC) != 0) {
		e = errno;
		res(r, false, e, NULL);
		return;
	}
	res(r, true, 0, "RW then RX, as V8 and WebAssembly need");
}

static void
p_anon_wx(struct presult *r)
{
	void *p;
	int e;

	p = mmap(NULL, 4096, PROT_READ | PROT_WRITE | PROT_EXEC,
	    MAP_ANON | MAP_PRIVATE, -1, 0);
	e = errno;
	res(r, p != MAP_FAILED, e, "simultaneous write+execute mapping");
}

/* ------------------------------------------------------------------ */
/* Descriptor rights enforcement                                        */
/* ------------------------------------------------------------------ */

static void
p_write_on_read_cap(struct presult *r)
{
	cap_rights_t rights;
	int fd, d;
	ssize_t n;
	int e;

	fd = memfd_create("beryllium-oracle", 0);
	cap_rights_init(&rights, CAP_READ);
	if (fd < 0 || (d = limited_dup(fd, &rights)) < 0) {
		setup_error(r, "memfd or limit", errno);
		return;
	}
	n = write(d, "x", 1);
	e = errno;
	res(r, n == 1, e, NULL);
}

static void
p_rights_widen(struct presult *r)
{
	cap_rights_t rights;
	int fd, d;

	fd = memfd_create("beryllium-oracle", 0);
	cap_rights_init(&rights, CAP_READ);
	if (fd < 0 || (d = limited_dup(fd, &rights)) < 0) {
		setup_error(r, "memfd or limit", errno);
		return;
	}
	cap_rights_init(&rights, CAP_READ, CAP_WRITE);
	res_rc(r, cap_rights_limit(d, &rights));
}

static int ioctl_fd = -1;

static int
pre_ioctl_pipe(struct presult *r)
{
	cap_rights_t rights;
	unsigned long cmds[] = { FIONREAD };
	int p[2];

	if (pipe(p) != 0) {
		setup_error(r, "pipe", errno);
		return (1);
	}
	cap_rights_init(&rights, CAP_READ, CAP_IOCTL, CAP_FCNTL);
	if (cap_rights_limit(p[0], &rights) != 0 ||
	    cap_ioctls_limit(p[0], cmds, 1) != 0 ||
	    cap_fcntls_limit(p[0], CAP_FCNTL_GETFL) != 0) {
		setup_error(r, "cap limits", errno);
		return (1);
	}
	ioctl_fd = p[0];
	return (0);
}

static void
p_ioctl_allowed(struct presult *r)
{
	int n;

	res_rc(r, ioctl(ioctl_fd, FIONREAD, &n));
}

static void
p_ioctl_outside_list(struct presult *r)
{
	int on = 1;

	res_rc(r, ioctl(ioctl_fd, FIONBIO, &on));
}

static void
p_fcntl_outside_list(struct presult *r)
{
	res_rc(r, fcntl(ioctl_fd, F_SETFL, O_NONBLOCK));
}

static void
p_closefrom(struct presult *r)
{
	const int bound = 256;
	int i, open_after = 0;

	/*
	 * Duplicate onto high numbers so closefrom() cannot touch the
	 * result pipe, which sits at a low descriptor.
	 */
	for (i = 0; i < 5; i++)
		if (fcntl(0, F_DUPFD, bound + i) != bound + i) {
			setup_error(r, "F_DUPFD", errno);
			return;
		}
	closefrom(bound);
	for (i = 0; i < 5; i++)
		if (fcntl(bound + i, F_GETFD) != -1)
			open_after++;
	res(r, open_after == 0, EBADF, "descriptors still open after closefrom=%d",
	    open_after);
}

/* ------------------------------------------------------------------ */
/* Process hardening (procctl must precede cap_enter)                    */
/* ------------------------------------------------------------------ */

static void
p_trace_disable(struct presult *r)
{
	int arg = PROC_TRACE_CTL_DISABLE, status = 0;

	if (procctl(P_PID, getpid(), PROC_TRACE_CTL, &arg) != 0) {
		res(r, false, errno, "PROC_TRACE_CTL refused");
		return;
	}
	if (procctl(P_PID, getpid(), PROC_TRACE_STATUS, &status) != 0) {
		setup_error(r, "PROC_TRACE_STATUS", errno);
		return;
	}
	res(r, status == -1, EINVAL, "PROC_TRACE_STATUS=%d (-1 means disabled)", status);
}

static void
p_no_new_privs(struct presult *r)
{
	int arg = PROC_NO_NEW_PRIVS_ENABLE;

	res_rc(r, procctl(P_PID, getpid(), PROC_NO_NEW_PRIVS_CTL, &arg));
}

static volatile sig_atomic_t trapped_code = -1;

static void
on_sigtrap(int sig, siginfo_t *si, void *uc)
{
	(void)sig;
	(void)uc;
	trapped_code = si->si_code;
}

static int
pre_trapcap(struct presult *r)
{
	struct sigaction sa;
	int arg = PROC_TRAPCAP_CTL_ENABLE;

	memset(&sa, 0, sizeof(sa));
	sa.sa_sigaction = on_sigtrap;
	sa.sa_flags = SA_SIGINFO;
	sigemptyset(&sa.sa_mask);
	if (sigaction(SIGTRAP, &sa, NULL) != 0 ||
	    procctl(P_PID, getpid(), PROC_TRAPCAP_CTL, &arg) != 0) {
		setup_error(r, "PROC_TRAPCAP_CTL", errno);
		return (1);
	}
	return (0);
}

static void
p_trapcap(struct presult *r)
{
	int fd = open("/etc/passwd", O_RDONLY);

	if (fd >= 0)
		close(fd);
	res(r, trapped_code == TRAP_CAP, 0, "SIGTRAP si_code=%d (TRAP_CAP=%d)",
	    (int)trapped_code, TRAP_CAP);
}

static void
p_aslr_status(struct presult *r)
{
	int status = 0;

	if (procctl(P_PID, getpid(), PROC_ASLR_STATUS, &status) != 0) {
		res(r, false, errno, NULL);
		return;
	}
	res(r, (status & PROC_ASLR_ACTIVE) != 0, 0,
	    "ASLR active for this binary=%s",
	    (status & PROC_ASLR_ACTIVE) ? "yes" : "no");
}

static void
p_wxmap_status(struct presult *r)
{
	int status = 0;

	if (procctl(P_PID, getpid(), PROC_WXMAP_STATUS, &status) != 0) {
		res(r, false, errno, NULL);
		return;
	}
	res(r, (status & PROC_WXORX_ENFORCE) != 0, 0,
	    "W^X enforced for this process=%s (status=0x%x)",
	    (status & PROC_WXORX_ENFORCE) ? "yes" : "no", (unsigned)status);
}

/*
 * RT-16: can a launcher make W^X mandatory for a child it is about to exec?
 * Sets PROC_WX_MAPPINGS_DISALLOW_EXEC, re-executes this binary in a helper
 * mode that tries a W+X mapping and the RW-to-RX path a JIT uses, and
 * reads two result bytes back.
 */
static void
p_wxorx_after_exec(struct presult *r)
{
	int pfd[2], arg = PROC_WX_MAPPINGS_DISALLOW_EXEC, st;
	char fdstr[16], out[2] = { '?', '?' };
	pid_t p;

	if (fx.self_path[0] == '\0') {
		setup_error(r, "own executable path unknown", ENOENT);
		return;
	}
	if (pipe(pfd) != 0) {
		setup_error(r, "pipe", errno);
		return;
	}
	p = fork();
	if (p == 0) {
		char *argv[] = { fx.self_path, "--wx-child", fdstr, NULL };

		close(pfd[0]);
		snprintf(fdstr, sizeof(fdstr), "%d", pfd[1]);
		if (procctl(P_PID, getpid(), PROC_WXMAP_CTL, &arg) != 0)
			_exit(2);
		execv(fx.self_path, argv);
		_exit(3);
	}
	if (p < 0) {
		setup_error(r, "fork", errno);
		return;
	}
	close(pfd[1]);
	if (read(pfd[0], out, 2) != 2) {
		(void)waitpid(p, &st, 0);
		setup_error(r, "helper produced no result", EINVAL);
		return;
	}
	(void)waitpid(p, &st, 0);
	/* Allowed means W+X was refused while the JIT path still works. */
	res(r, out[0] == 'D' && out[1] == 'A', EINVAL,
	    "after exec with DISALLOW_EXEC: W+X mapping %s; RW then RX %s",
	    out[0] == 'D' ? "refused" : "allowed",
	    out[1] == 'A' ? "works" : "refused");
}

static int
wx_child(int fd)
{
	char out[2];
	void *p;

	p = mmap(NULL, 4096, PROT_READ | PROT_WRITE | PROT_EXEC,
	    MAP_ANON | MAP_PRIVATE, -1, 0);
	out[0] = p == MAP_FAILED ? 'D' : 'A';
	p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
	out[1] = p != MAP_FAILED && mprotect(p, 4096, PROT_READ | PROT_EXEC) == 0 ?
	    'A' : 'D';
	(void)write(fd, out, 2);
	return (0);
}

static void
p_dev_fd_complete(struct presult *r)
{
	struct statfs sfs;
	struct dirent *de;
	DIR *dir;
	bool seen = false;
	const int probe_fd = 60;

	if (dup2(0, probe_fd) < 0) {
		setup_error(r, "dup2", errno);
		return;
	}
	dir = opendir("/dev/fd");
	if (dir == NULL) {
		setup_error(r, "opendir /dev/fd", errno);
		return;
	}
	while ((de = readdir(dir)) != NULL)
		if (atoi(de->d_name) == probe_fd)
			seen = true;
	closedir(dir);
	res(r, seen, ENOENT, "/dev/fd filesystem=%s; fd %d listed=%s",
	    statfs("/dev/fd", &sfs) == 0 ? sfs.f_fstypename : "unknown",
	    probe_fd, seen ? "yes" : "no");
}

static void
p_localtime_uncached(struct presult *r)
{
	time_t t = time(NULL);
	struct tm tm;
	bool fallback;

	if (localtime_r(&t, &tm) == NULL) {
		res(r, false, errno, NULL);
		return;
	}
	/*
	 * Only whether the local zone was loaded is recorded, never the zone
	 * itself: results files are committed to a public repository.
	 */
	fallback = tm.tm_zone == NULL || strcmp(tm.tm_zone, "-00") == 0 ||
	    (strcmp(tm.tm_zone, "UTC") == 0 && tm.tm_gmtoff == 0);
	res(r, !fallback, ENOENT, "%s", fallback ?
	    "local zone not loaded (UTC fallback)" :
	    "local zone loaded (zone not recorded)");
}

static int
pre_tzcache(struct presult *r)
{
	(void)r;
	caph_cache_tzdata();
	return (0);
}

static void
p_arc4random(struct presult *r)
{
	uint32_t a = arc4random(), b = arc4random();

	res(r, a != b, 0, NULL);
}

/* ------------------------------------------------------------------ */
/* Probe table                                                          */
/* ------------------------------------------------------------------ */

#define CAP	true
#define NOCAP	false

static const struct probe probes[] = {
	/* Files */
	{ "fs.open_etc_passwd", "spec 13.1", "files", "open(\"/etc/passwd\") by absolute path", EXP_DENY, CAP, NULL, p_open_etc_passwd },
	{ "fs.open_canary", "spec 13.1", "files", "open() of a canary file by absolute path", EXP_DENY, CAP, NULL, p_open_canary_abs },
	{ "fs.open_create", "spec 13.1", "files", "open(O_CREAT) of a new file in /tmp", EXP_DENY, CAP, NULL, p_open_create_tmp },
	{ "fs.openat_cwd", "spec 13.1", "files", "openat(AT_FDCWD) of an absolute path", EXP_DENY, CAP, NULL, p_openat_cwd },
	{ "fs.open_dev_null", "06 3.2", "files", "open(\"/dev/null\")", EXP_DENY, CAP, NULL, p_open_dev_null },
	{ "fs.openat_beneath", "06 2", "files", "openat(dirfd, \"sub/inner\") with CAP_LOOKUP", EXP_ALLOW, CAP, NULL, p_openat_beneath },
	{ "fs.openat_dotdot", "06 2", "files", "openat(dirfd, \"..\") escape", EXP_DENY, CAP, NULL, p_openat_dotdot },
	{ "fs.openat_absolute", "06 2", "files", "openat(dirfd, \"/etc/passwd\")", EXP_DENY, CAP, NULL, p_openat_absolute },
	{ "fs.openat_symlink_out", "06 2", "files", "openat(dirfd) through a symlink pointing outside", EXP_DENY, CAP, NULL, p_openat_symlink_out },
	{ "fs.openat_write_on_ro", "06 2", "files", "openat(O_WRONLY) beneath a read-only directory capability", EXP_DENY, CAP, NULL, p_openat_write_on_ro },

	/* Network */
	{ "net.socket_inet_stream", "RT-02", "network", "socket(AF_INET, SOCK_STREAM)", EXP_RECORD, CAP, NULL, p_socket_inet_stream },
	{ "net.socket_inet_dgram", "RT-02", "network", "socket(AF_INET, SOCK_DGRAM)", EXP_RECORD, CAP, NULL, p_socket_inet_dgram },
	{ "net.socket_inet6_stream", "RT-02", "network", "socket(AF_INET6, SOCK_STREAM)", EXP_RECORD, CAP, NULL, p_socket_inet6_stream },
	{ "net.socket_unix", "RT-02", "network", "socket(AF_UNIX, SOCK_STREAM)", EXP_RECORD, CAP, NULL, p_socket_unix },
	{ "net.socket_route", "RT-02", "network", "socket(PF_ROUTE, SOCK_RAW)", EXP_DENY, CAP, NULL, p_socket_route },
	{ "net.socket_netlink", "RT-02", "network", "socket(AF_NETLINK, NETLINK_ROUTE)", EXP_DENY, CAP, NULL, p_socket_netlink },
	{ "net.netlink_getaddr", "RT-02 RT-13", "network", "read interface addresses over netlink", EXP_DENY, CAP, NULL, p_netlink_getaddr },
	{ "net.getifaddrs", "RT-02 RT-13", "network", "getifaddrs() reveals local addresses", EXP_DENY, CAP, NULL, p_getifaddrs },
	{ "net.connect_inet", "spec 6.1.5", "network", "connect() to 127.0.0.1", EXP_DENY, CAP, NULL, p_connect_inet },
	{ "net.bind_inet", "spec 6.1.5", "network", "bind() to 127.0.0.1", EXP_DENY, CAP, NULL, p_bind_inet },
	{ "net.sendto_udp", "spec 6.1.5", "network", "sendto() with a destination address", EXP_DENY, CAP, NULL, p_sendto_udp },
	{ "net.preconnected_send", "spec 5.1", "network", "send() on a TCP socket connected before cap_enter", EXP_RECORD, CAP, pre_tcp_pair, p_preconnected_tcp_send },
	{ "net.connect_unix_path", "RT-06", "network", "connect() to a Unix socket by path", EXP_DENY, CAP, NULL, p_connect_unix_path },
	{ "net.connectat_cap", "RT-06", "network", "connectat() beneath a directory with CAP_CONNECTAT", EXP_ALLOW, CAP, NULL, p_connectat_cap },
	{ "net.connectat_nocap", "RT-06", "network", "connectat() beneath a directory without CAP_CONNECTAT", EXP_DENY, CAP, NULL, p_connectat_nocap },
	{ "net.getaddrinfo", "06 2", "network", "getaddrinfo(\"localhost\") without cap_net", EXP_DENY, CAP, NULL, p_getaddrinfo },

	/* Identity */
	{ "id.kern_hostuuid", "RT-01", "identity", "read kern.hostuuid", EXP_DENY, CAP, pre_hostuuid, read_mib },
	{ "id.kern_hostid", "RT-01", "identity", "read kern.hostid", EXP_DENY, CAP, pre_hostid, read_mib },
	{ "id.kern_hostname", "RT-01", "identity", "read kern.hostname", EXP_DENY, CAP, pre_hostname, read_mib },
	{ "id.kern_domainname", "RT-01", "identity", "read kern.domainname", EXP_DENY, CAP, pre_domainname, read_mib },
	{ "id.kern_boot_id", "RT-01", "identity", "read kern.boot_id", EXP_DENY, CAP, pre_boot_id, read_mib },
	{ "id.hw_model", "RT-13", "identity", "read hw.model (CPU model string)", EXP_RECORD, CAP, pre_hw_model, read_mib },
	{ "id.hw_physmem", "RT-13", "identity", "read hw.physmem", EXP_RECORD, CAP, pre_hw_physmem, read_mib },
	{ "id.hw_ncpu", "06 4.6", "identity", "read hw.ncpu", EXP_RECORD, CAP, pre_hw_ncpu, read_mib },
	{ "id.vm_page_count", "06 4.6", "identity", "read vm.stats.vm.v_page_count (the 2023 attempt's failure point)", EXP_RECORD, CAP, pre_page_count, read_mib },
	{ "id.kern_osrelease", "06 4.6", "identity", "read kern.osrelease", EXP_RECORD, CAP, pre_osrelease, read_mib },
	{ "id.kern_proc_self", "06 4.6", "identity", "read kern.proc.pid.<self>", EXP_RECORD, CAP, pre_proc_self, read_mib },
	{ "id.kern_proc_other", "RT-02", "identity", "read kern.proc.pid.<other process>", EXP_DENY, CAP, pre_proc_other, read_mib },
	{ "id.kern_proc_args_other", "RT-02", "identity", "read kern.proc.args.<other process>", EXP_DENY, CAP, pre_args_other, read_mib },
	{ "id.kenv_smbios_uuid", "RT-01", "identity", "kenv(KENV_GET, \"smbios.system.uuid\")", EXP_DENY, CAP, NULL, p_kenv_smbios },
	{ "id.uname", "RT-13", "identity", "uname() sysname and machine", EXP_RECORD, CAP, NULL, p_uname },
	{ "id.sysctl_sweep", "RT-01", "identity", "every sysctl leaf readable from capability mode", EXP_RECORD, CAP, NULL, p_sysctl_sweep },

	/* Processes */
	{ "proc.kill_other", "spec 6.1.6", "processes", "kill(other, 0)", EXP_DENY, CAP, NULL, p_kill_other },
	{ "proc.kill_self", "spec 6.1.6", "processes", "kill(self, 0)", EXP_ALLOW, CAP, NULL, p_kill_self },
	{ "proc.sigqueue_other", "spec 13.2", "processes", "sigqueue(other, 0)", EXP_DENY, CAP, NULL, p_sigqueue_other },
	{ "proc.thr_kill2_other", "spec 6.1.6", "processes", "thr_kill2(other, -1, 0)", EXP_DENY, CAP, NULL, p_thr_kill2_other },
	{ "proc.ptrace_other", "RT-03", "processes", "ptrace(PT_ATTACH) to another same-user process", EXP_DENY, CAP, NULL, p_ptrace_other },
	{ "proc.ptrace_other_control", "RT-03", "processes", "same, outside capability mode (control)", EXP_RECORD, NOCAP, NULL, p_ptrace_other },
	{ "proc.ptrace_trace_disabled", "RT-03", "processes", "ptrace(PT_ATTACH) to a process with PROC_TRACE_CTL_DISABLE, outside capability mode", EXP_DENY, NOCAP, NULL, p_ptrace_notrace_target },
	{ "proc.kevent_proc_other", "RT-02", "processes", "kevent(EVFILT_PROC) on another same-user process", EXP_DENY, CAP, NULL, p_kevent_proc_other },
	{ "proc.kevent_proc_init", "RT-02", "processes", "kevent(EVFILT_PROC) on pid 1 (another user)", EXP_DENY, CAP, NULL, p_kevent_proc_init },
	{ "proc.getpriority_user", "spec 6.1.6", "processes", "getpriority(PRIO_USER)", EXP_DENY, CAP, NULL, p_getpriority_user },
	{ "proc.getpriority_other", "spec 6.1.6", "processes", "getpriority(PRIO_PROCESS, other)", EXP_DENY, CAP, NULL, p_getpriority_other },
	{ "proc.setpriority_other", "RT-02", "processes", "setpriority(PRIO_PROCESS, other, nice+1)", EXP_DENY, CAP, pre_sleeper_nice, p_setpriority_other },
	{ "proc.procctl", "06 2", "processes", "procctl() inside capability mode", EXP_DENY, CAP, NULL, p_procctl_capmode },
	{ "proc.fork", "RT-15", "processes", "fork()", EXP_RECORD, CAP, NULL, p_fork },
	{ "proc.fork_nproc1", "RT-15", "processes", "fork() with RLIMIT_NPROC=1", EXP_DENY, CAP, pre_nproc_1, p_fork_nproc1 },
	{ "proc.fork_inherits", "spec 6.1.9", "processes", "a forked child is still in capability mode", EXP_ALLOW, CAP, NULL, p_fork_inherits_capmode },
	{ "proc.pdfork_pdkill", "02 3", "processes", "pdfork() then pdkill() of own child", EXP_RECORD, CAP, NULL, p_pdfork_pdkill },
	{ "proc.execve", "spec 3.1", "processes", "execve(\"/bin/sh\")", EXP_DENY, CAP, NULL, p_execve },
	{ "proc.dlopen", "06 2", "processes", "dlopen() of a library not yet loaded", EXP_DENY, CAP, NULL, p_dlopen },
	{ "proc.dlopen_control", "06 2", "processes", "same, outside capability mode (control)", EXP_ALLOW, NOCAP, NULL, p_dlopen_control },
	{ "proc.posix_openpt", "RT-02", "processes", "posix_openpt()", EXP_DENY, CAP, NULL, p_posix_openpt },

	/* Memory */
	{ "mem.shm_anon", "06 3.3", "memory", "shm_open(SHM_ANON)", EXP_ALLOW, CAP, NULL, p_shm_anon },
	{ "mem.memfd_seal", "06 3.3", "memory", "memfd_create() plus F_ADD_SEALS", EXP_ALLOW, CAP, NULL, p_memfd_seal },
	{ "mem.shm_named", "06 3.3", "memory", "shm_open() of a named object", EXP_DENY, CAP, NULL, p_shm_named },
	{ "mem.sysv_shmget", "03 4.4", "memory", "SysV shmget(IPC_PRIVATE)", EXP_RECORD, CAP, NULL, p_sysv_shmget },
	{ "mem.ro_twin_map_rw", "06 3.3", "memory", "map a rights-limited read-only twin writable", EXP_DENY, CAP, NULL, p_ro_twin_map_rw },
	{ "mem.ro_twin_mprotect", "06 3.3", "memory", "mprotect() a read-only twin mapping to writable", EXP_DENY, CAP, NULL, p_ro_twin_mprotect },
	{ "mem.ro_twin_map_exec", "06 3.3", "memory", "map a CAP_MMAP_R descriptor executable", EXP_DENY, CAP, NULL, p_ro_twin_map_exec },
	{ "mem.ro_twin_introspect", "06 3.3", "memory", "F_GETFL and cap_rights_get() on a read-only twin", EXP_RECORD, CAP, NULL, p_ro_twin_introspect },
	{ "mem.anon_jit", "06 2", "memory", "anonymous RW mapping changed to RX", EXP_ALLOW, CAP, NULL, p_anon_jit },
	{ "mem.anon_wx", "RT-09", "memory", "anonymous mapping with write and execute at once", EXP_RECORD, CAP, NULL, p_anon_wx },

	/* Descriptor rights */
	{ "fd.write_on_read_cap", "spec 6.1.3", "descriptors", "write() on a CAP_READ-only descriptor", EXP_DENY, CAP, NULL, p_write_on_read_cap },
	{ "fd.rights_widen", "spec 6.1.3", "descriptors", "widen rights with a second cap_rights_limit()", EXP_DENY, CAP, NULL, p_rights_widen },
	{ "fd.ioctl_allowed", "spec 6.1.3", "descriptors", "ioctl(FIONREAD) on the ioctl allowlist", EXP_ALLOW, CAP, pre_ioctl_pipe, p_ioctl_allowed },
	{ "fd.ioctl_outside_list", "spec 6.1.3", "descriptors", "ioctl(FIONBIO) outside the ioctl allowlist", EXP_DENY, CAP, pre_ioctl_pipe, p_ioctl_outside_list },
	{ "fd.fcntl_outside_list", "spec 6.1.3", "descriptors", "fcntl(F_SETFL) outside the fcntl allowlist", EXP_DENY, CAP, pre_ioctl_pipe, p_fcntl_outside_list },
	{ "fd.closefrom", "06 4", "descriptors", "closefrom() closes everything above a bound", EXP_ALLOW, CAP, NULL, p_closefrom },
	{ "fd.dev_fd_complete", "06 4", "descriptors", "/dev/fd lists every open descriptor (upstream CloseSuperfluousFds relies on it)", EXP_RECORD, NOCAP, NULL, p_dev_fd_complete },

	/* Hardening and diagnostics */
	{ "hard.trace_disable", "RT-03", "hardening", "PROC_TRACE_CTL_DISABLE takes effect", EXP_ALLOW, NOCAP, NULL, p_trace_disable },
	{ "hard.no_new_privs", "06 6", "hardening", "PROC_NO_NEW_PRIVS_CTL", EXP_ALLOW, NOCAP, NULL, p_no_new_privs },
	{ "hard.trapcap", "06 2", "hardening", "PROC_TRAPCAP_CTL delivers SIGTRAP/TRAP_CAP on a denied call", EXP_ALLOW, CAP, pre_trapcap, p_trapcap },
	{ "hard.aslr_status", "RT-09", "hardening", "ASLR active for this (oracle) binary", EXP_RECORD, NOCAP, NULL, p_aslr_status },
	{ "hard.wxmap_status", "RT-16", "hardening", "W^X enforced for this process by default", EXP_RECORD, NOCAP, NULL, p_wxmap_status },
	{ "hard.wxorx_after_exec", "RT-16", "hardening", "PROC_WX_MAPPINGS_DISALLOW_EXEC before exec enforces W^X and keeps RW-to-RX working", EXP_ALLOW, NOCAP, NULL, p_wxorx_after_exec },
	{ "misc.localtime_uncached", "06 4.6", "misc", "localtime() in capability mode without caching tzdata", EXP_RECORD, CAP, NULL, p_localtime_uncached },
	{ "misc.localtime_cached", "06 4.6", "misc", "localtime() after caph_cache_tzdata()", EXP_RECORD, CAP, pre_tzcache, p_localtime_uncached },
	{ "misc.arc4random", "03 4.6", "misc", "arc4random() needs no descriptor", EXP_ALLOW, CAP, NULL, p_arc4random },
};

/* ------------------------------------------------------------------ */
/* JSON output                                                          */
/* ------------------------------------------------------------------ */

static void
json_str(FILE *f, const char *s)
{
	fputc('"', f);
	for (; s != NULL && *s != '\0'; s++) {
		unsigned char c = (unsigned char)*s;

		if (c == '"' || c == '\\')
			fprintf(f, "\\%c", c);
		else if (c == '\n')
			fputs("\\n", f);
		else if (c < 0x20)
			fprintf(f, "\\u%04x", c);
		else
			fputc(c, f);
	}
	fputc('"', f);
}

static void
json_sysctl_int(FILE *f, const char *name, bool *first)
{
	int v;
	size_t l = sizeof(v);

	fprintf(f, "%s\n    ", *first ? "" : ",");
	*first = false;
	json_str(f, name);
	if (sysctlbyname(name, &v, &l, NULL, 0) == 0 && l == sizeof(v))
		fprintf(f, ": %d", v);
	else
		fputs(": null", f);
}

static void
json_sysctl_str(FILE *f, const char *name, bool *first, bool cut_at_colon)
{
	char buf[512];
	size_t l = sizeof(buf) - 1;
	char *nl;

	fprintf(f, "%s\n    ", *first ? "" : ",");
	*first = false;
	json_str(f, name);
	if (sysctlbyname(name, buf, &l, NULL, 0) == 0) {
		buf[l] = '\0';
		if ((nl = strchr(buf, '\n')) != NULL)
			*nl = '\0';
		/*
		 * kern.version continues with "user@host:/path" after the
		 * first colon on custom kernels; keep only the release and
		 * source revision before it.
		 */
		if (cut_at_colon && (nl = strchr(buf, ':')) != NULL)
			*nl = '\0';
		fputs(": ", f);
		json_str(f, buf);
	} else {
		fputs(": null", f);
	}
}

static void
print_kernel(FILE *f)
{
	bool first = true;

	fputs("  \"kernel\": {", f);
	json_sysctl_str(f, "kern.ostype", &first, false);
	json_sysctl_str(f, "kern.osrelease", &first, false);
	json_sysctl_int(f, "kern.osreldate", &first);
	json_sysctl_str(f, "kern.version", &first, true);
	json_sysctl_str(f, "hw.machine_arch", &first, false);
	json_sysctl_int(f, "security.bsd.allow_ptrace_in_cap_mode", &first);
	json_sysctl_int(f, "security.bsd.see_other_uids", &first);
	json_sysctl_int(f, "security.bsd.see_other_gids", &first);
	json_sysctl_int(f, "security.bsd.unprivileged_proc_debug", &first);
	json_sysctl_int(f, "kern.trap_enotcap", &first);
	json_sysctl_int(f, "kern.elf64.allow_wx", &first);
	json_sysctl_int(f, "kern.elf64.aslr.enable", &first);
	json_sysctl_int(f, "kern.elf64.aslr.pie_enable", &first);
	json_sysctl_int(f, "kern.ipc.shm_allow_removed", &first);
	fprintf(f, ",\n    \"run_as_root\": %s", getuid() == 0 ? "true" : "false");
	fputs("\n  },\n", f);
}

/* ------------------------------------------------------------------ */
/* Runner                                                               */
/* ------------------------------------------------------------------ */

struct tally {
	int ok, exposed, broken, info, error;
};

static const char *
expect_name(enum expect e)
{
	return (e == EXP_DENY ? "deny" : e == EXP_ALLOW ? "allow" : "record");
}

static const char *
verdict(const struct probe *p, const struct presult *r, bool ran, struct tally *t)
{
	if (!ran || r->outcome == OUT_SETUP_ERROR) {
		t->error++;
		return ("error");
	}
	switch (p->expect) {
	case EXP_DENY:
		if (r->outcome == OUT_DENIED) {
			t->ok++;
			return ("ok");
		}
		t->exposed++;
		return ("exposed");
	case EXP_ALLOW:
		if (r->outcome == OUT_ALLOWED) {
			t->ok++;
			return ("ok");
		}
		t->broken++;
		return ("broken");
	default:
		t->info++;
		return ("info");
	}
}

/*
 * Run one probe in a child. Collects everything the child writes to the
 * result pipe. Returns true if the child produced a complete result.
 */
static bool
run_child(const struct probe *p, struct presult *r, char **sweep_out,
    char *status, size_t statuslen)
{
	int pfd[2], st;
	pid_t pid;
	char *acc = NULL;
	size_t acclen = 0, cap = 0;
	ssize_t n;
	char buf[8192];

	memset(r, 0, sizeof(*r));
	snprintf(status, statuslen, "exited");
	if (pipe(pfd) != 0)
		return (false);
	fflush(NULL);
	pid = fork();
	if (pid < 0)
		return (false);
	if (pid == 0) {
		struct presult cr;
		bool is_sweep = p->fn == p_sysctl_sweep;

		close(pfd[0]);
		memset(&cr, 0, sizeof(cr));
		alarm(is_sweep ? 6 * PROBE_TIMEOUT : PROBE_TIMEOUT);
		if (p->pre != NULL && p->pre(&cr) != 0)
			goto out;
		if (p->capmode) {
			u_int mode = 0;

			if (cap_enter() != 0 || cap_getmode(&mode) != 0 || mode != 1) {
				setup_error(&cr, "cap_enter", errno);
				goto out;
			}
		}
		if (is_sweep)
			sweep_fd = pfd[1];
		p->fn(&cr);
out:
		/* The fixed-size result record always comes last. */
		(void)write(pfd[1], &cr, sizeof(cr));
		_exit(0);
	}
	close(pfd[1]);
	while ((n = read(pfd[0], buf, sizeof(buf))) > 0) {
		if (acclen + (size_t)n + 1 > cap) {
			cap = (acclen + (size_t)n + 1) * 2;
			acc = realloc(acc, cap);
			if (acc == NULL)
				abort();
		}
		memcpy(acc + acclen, buf, (size_t)n);
		acclen += (size_t)n;
	}
	close(pfd[0]);
	(void)waitpid(pid, &st, 0);
	if (WIFSIGNALED(st))
		snprintf(status, statuslen, "%s",
		    WTERMSIG(st) == SIGALRM ? "timeout" : "crashed");
	if (acclen < sizeof(*r)) {
		free(acc);
		return (false);
	}
	memcpy(r, acc + acclen - sizeof(*r), sizeof(*r));
	r->detail[sizeof(r->detail) - 1] = '\0';
	if (sweep_out != NULL) {
		acc[acclen - sizeof(*r)] = '\0';
		*sweep_out = acc;
	} else {
		free(acc);
	}
	return (true);
}

/*
 * RT-04: can the browser verify a child's capability mode from the kernel
 * rather than trusting the child? Reads kinfo_proc.ki_cr_flags for a child
 * that entered capability mode and for a control child that did not.
 */
static bool
kernel_capmode_flag(pid_t pid, bool *flag)
{
	struct kinfo_proc kp;
	size_t len = sizeof(kp);
	int mib[4] = { CTL_KERN, KERN_PROC, KERN_PROC_PID, (int)pid };

	if (sysctl(mib, 4, &kp, &len, NULL, 0) != 0 || len != sizeof(kp))
		return (false);
	*flag = (kp.ki_cr_flags & KI_CRF_CAPABILITY_MODE) != 0;
	return (true);
}

static bool
attest_child(bool enter, bool *flag)
{
	int ready[2], go[2], st;
	char c = 0;
	pid_t pid;
	bool ok;

	if (pipe(ready) != 0 || pipe(go) != 0)
		return (false);
	fflush(NULL);
	pid = fork();
	if (pid == 0) {
		alarm(PROBE_TIMEOUT);
		if (enter)
			(void)cap_enter();
		(void)write(ready[1], "r", 1);
		(void)read(go[0], &c, 1);
		_exit(0);
	}
	if (pid < 0)
		return (false);
	(void)read(ready[0], &c, 1);
	ok = kernel_capmode_flag(pid, flag);
	(void)write(go[1], "g", 1);
	(void)waitpid(pid, &st, 0);
	close(ready[0]); close(ready[1]); close(go[0]); close(go[1]);
	return (ok);
}

static void
print_probe(FILE *f, const struct probe *p, const struct presult *r, bool ran,
    const char *status, const char *v, bool first)
{
	fprintf(f, "%s\n    {\"id\": ", first ? "" : ",");
	json_str(f, p->id);
	fputs(", \"ref\": ", f);
	json_str(f, p->rt);
	fputs(", \"area\": ", f);
	json_str(f, p->area);
	fputs(", \"capmode\": ", f);
	fputs(p->capmode ? "true" : "false", f);
	fputs(", \"description\": ", f);
	json_str(f, p->desc);
	fputs(", \"expect\": ", f);
	json_str(f, expect_name(p->expect));
	fputs(", \"outcome\": ", f);
	if (!ran)
		json_str(f, status);
	else
		json_str(f, r->outcome == OUT_ALLOWED ? "allowed" :
		    r->outcome == OUT_DENIED ? "denied" : "setup_error");
	fputs(", \"errno\": ", f);
	json_str(f, ran && r->outcome != OUT_ALLOWED ? errname(r->err) : "");
	fputs(", \"detail\": ", f);
	json_str(f, ran ? r->detail : "");
	fputs(", \"verdict\": ", f);
	json_str(f, v);
	fputc('}', f);
}

/* Name fragments that mark a sysctl as a potential identifier. */
static bool
sensitive_name(const char *n)
{
	static const char *frag[] = { "uuid", "hostid", "hostname", "domainname",
	    "boot_id", "serial", "ident", "ether", "lladdr", "macaddr", NULL };

	for (int i = 0; frag[i] != NULL; i++)
		if (strstr(n, frag[i]) != NULL)
			return (true);
	return (false);
}

static void
print_sweep(FILE *f, char *text)
{
	char *line, *save = NULL;
	bool first = true, sfirst = true;
	char summary[128] = "";
	char *sens[512];
	int nsens = 0;

	fputs("  \"caprd_sysctls\": {\n    \"readable\": [", f);
	for (line = strtok_r(text, "\n", &save); line != NULL;
	    line = strtok_r(NULL, "\n", &save)) {
		if (line[0] == '#') {
			strlcpy(summary, line, sizeof(summary));
			continue;
		}
		fprintf(f, "%s\n      ", first ? "" : ",");
		first = false;
		json_str(f, line);
		if (sensitive_name(line) && nsens < 512)
			sens[nsens++] = line;
	}
	fputs("\n    ],\n    \"identifier_like\": [", f);
	for (int i = 0; i < nsens; i++) {
		fprintf(f, "%s", sfirst ? "" : ", ");
		sfirst = false;
		json_str(f, sens[i]);
	}
	fputs("],\n    \"summary\": ", f);
	json_str(f, summary);
	fputs("\n  },\n", f);
	fprintf(stderr, "sysctl sweep: %s; identifier-like readable nodes: %d\n",
	    summary, nsens);
}

/* ------------------------------------------------------------------ */
/* Fixture setup and teardown                                           */
/* ------------------------------------------------------------------ */

static pid_t
spawn_sleeper(bool notrace)
{
	pid_t p;

	fflush(NULL);
	p = fork();
	if (p == 0) {
		if (notrace) {
			int arg = PROC_TRACE_CTL_DISABLE;

			(void)procctl(P_PID, getpid(), PROC_TRACE_CTL, &arg);
		}
		for (;;)
			pause();
	}
	return (p);
}

static int
fixture_setup(void)
{
	struct sockaddr_un sun;
	char path[PATH_MAX];
	int fd;

	strlcpy(fx.tmpdir, "/tmp/beryllium-oracle.XXXXXXXX", sizeof(fx.tmpdir));
	if (mkdtemp(fx.tmpdir) == NULL)
		return (-1);
	snprintf(fx.canary_abs, sizeof(fx.canary_abs), "%s/canary", fx.tmpdir);
	fd = open(fx.canary_abs, O_CREAT | O_WRONLY | O_EXCL, 0600);
	if (fd < 0)
		return (-1);
	(void)write(fd, "beryllium canary\n", 17);
	close(fd);

	snprintf(path, sizeof(path), "%s/sub", fx.tmpdir);
	if (mkdir(path, 0700) != 0)
		return (-1);
	snprintf(path, sizeof(path), "%s/sub/inner", fx.tmpdir);
	fd = open(path, O_CREAT | O_WRONLY | O_EXCL, 0600);
	if (fd < 0)
		return (-1);
	close(fd);
	snprintf(path, sizeof(path), "%s/link_out", fx.tmpdir);
	if (symlink("/etc/passwd", path) != 0)
		return (-1);

	snprintf(fx.sock_abs, sizeof(fx.sock_abs), "%s/sock", fx.tmpdir);
	fx.listen_unix = socket(AF_UNIX, SOCK_STREAM, 0);
	memset(&sun, 0, sizeof(sun));
	sun.sun_family = AF_UNIX;
	strlcpy(sun.sun_path, fx.sock_abs, sizeof(sun.sun_path));
	sun.sun_len = SUN_LEN(&sun);
	if (fx.listen_unix < 0 ||
	    bind(fx.listen_unix, (struct sockaddr *)&sun, sun.sun_len) != 0 ||
	    listen(fx.listen_unix, 64) != 0)
		return (-1);

	fx.dirfd = open(fx.tmpdir, O_RDONLY | O_DIRECTORY);
	if (fx.dirfd < 0)
		return (-1);

	snprintf(fx.shm_name, sizeof(fx.shm_name), "/beryllium-oracle-%d",
	    (int)getpid());

	{
		int mib[4] = { CTL_KERN, KERN_PROC, KERN_PROC_PATHNAME, -1 };
		size_t len = sizeof(fx.self_path);

		if (sysctl(mib, 4, fx.self_path, &len, NULL, 0) != 0)
			fx.self_path[0] = '\0';
	}

	fx.sleeper = spawn_sleeper(false);
	fx.sleeper_notrace = spawn_sleeper(true);
	if (fx.sleeper < 0 || fx.sleeper_notrace < 0)
		return (-1);
	usleep(100000);	/* let the second sleeper apply its procctl */
	return (0);
}

static void
fixture_teardown(void)
{
	char path[PATH_MAX];
	int st;

	if (fx.sleeper > 0) {
		kill(fx.sleeper, SIGKILL);
		waitpid(fx.sleeper, &st, 0);
	}
	if (fx.sleeper_notrace > 0) {
		kill(fx.sleeper_notrace, SIGKILL);
		waitpid(fx.sleeper_notrace, &st, 0);
	}
	(void)shm_unlink(fx.shm_name);
	if (fx.tmpdir[0] == '\0')
		return;
	unlink(fx.sock_abs);
	unlink(fx.canary_abs);
	snprintf(path, sizeof(path), "%s/created-in-capmode", fx.tmpdir);
	unlink(path);
	snprintf(path, sizeof(path), "%s/link_out", fx.tmpdir);
	unlink(path);
	snprintf(path, sizeof(path), "%s/sub/inner", fx.tmpdir);
	unlink(path);
	snprintf(path, sizeof(path), "%s/sub", fx.tmpdir);
	rmdir(path);
	rmdir(fx.tmpdir);
}

/* ------------------------------------------------------------------ */
/* main                                                                 */
/* ------------------------------------------------------------------ */

static void
usage(void)
{
	fprintf(stderr,
	    "usage: cap-oracle [-l] [-o prefix]\n"
	    "  -l         list probes and exit\n"
	    "  -o prefix  run only probes whose id starts with prefix\n");
	exit(2);
}

int
main(int argc, char **argv)
{
	const char *only = NULL;
	struct tally t = { 0 };
	bool first = true, list = false, ok, capflag = false, ctlflag = true;
	char *sweep = NULL;
	time_t now;
	struct tm tm;
	char date[32];
	int ch;

	if (argc == 3 && strcmp(argv[1], "--wx-child") == 0)
		return (wx_child(atoi(argv[2])));

	while ((ch = getopt(argc, argv, "lo:")) != -1) {
		switch (ch) {
		case 'l': list = true; break;
		case 'o': only = optarg; break;
		default: usage();
		}
	}
	if (list) {
		for (size_t i = 0; i < nitems(probes); i++)
			printf("%-28s %-6s %s\n", probes[i].id,
			    expect_name(probes[i].expect), probes[i].desc);
		return (0);
	}
	if (getuid() == 0)
		fprintf(stderr, "warning: running as root; RLIMIT_NPROC and "
		    "ptrace results do not reflect an ordinary user\n");

	if (fixture_setup() != 0) {
		perror("cap-oracle: fixture setup");
		fixture_teardown();
		return (1);
	}

	/*
	 * No strftime() or localtime() in the parent: strftime() calls
	 * tzset(), and loaded timezone state would be inherited by every
	 * child and spoil the misc.localtime_* probes.
	 */
	now = time(NULL);
	gmtime_r(&now, &tm);
	snprintf(date, sizeof(date), "%04d-%02d-%02dT%02d:%02d:%02dZ",
	    tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour,
	    tm.tm_min, tm.tm_sec);

	printf("{\n  \"oracle_version\": %d,\n  \"run_at\": \"%s\",\n",
	    ORACLE_VERSION, date);
	print_kernel(stdout);

	/* RT-04: kernel-attested capability mode. */
	ok = attest_child(true, &capflag) && attest_child(false, &ctlflag);
	printf("  \"kernel_attestation\": {\"available\": %s, "
	    "\"capmode_child_flag\": %s, \"control_child_flag\": %s, "
	    "\"verdict\": \"%s\"},\n",
	    ok ? "true" : "false", capflag ? "true" : "false",
	    ctlflag ? "true" : "false",
	    ok && capflag && !ctlflag ? "ok" : "broken");
	if (ok && capflag && !ctlflag)
		t.ok++;
	else
		t.broken++;

	printf("  \"probes\": [");
	for (size_t i = 0; i < nitems(probes); i++) {
		const struct probe *p = &probes[i];
		struct presult r;
		char status[32];
		bool ran, is_sweep = p->fn == p_sysctl_sweep;
		const char *v;

		if (only != NULL && strncmp(p->id, only, strlen(only)) != 0)
			continue;
		ran = run_child(p, &r, is_sweep ? &sweep : NULL, status,
		    sizeof(status));
		v = verdict(p, &r, ran, &t);
		print_probe(stdout, p, &r, ran, status, v, first);
		first = false;
		if (strcmp(v, "exposed") == 0 || strcmp(v, "broken") == 0 ||
		    strcmp(v, "error") == 0)
			fprintf(stderr, "%-8s %-28s %s%s%s\n", v, p->id, p->desc,
			    ran && r.detail[0] ? ": " : "",
			    ran ? r.detail : status);
	}
	printf("\n  ],\n");

	if (sweep != NULL) {
		print_sweep(stdout, sweep);
		free(sweep);
	}

	printf("  \"summary\": {\"ok\": %d, \"exposed\": %d, \"broken\": %d, "
	    "\"info\": %d, \"error\": %d}\n}\n",
	    t.ok, t.exposed, t.broken, t.info, t.error);
	fprintf(stderr, "summary: ok=%d exposed=%d broken=%d info=%d error=%d\n",
	    t.ok, t.exposed, t.broken, t.info, t.error);

	fixture_teardown();
	return (t.broken > 0 || t.error > 0 ? 1 : 0);
}
