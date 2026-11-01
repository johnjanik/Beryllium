# Beryllium Phase 0 baseline

Collected 2026-11-01 08:18 UTC by freebsd/tools/baseline-collect.sh. Home directory, user name and host name are redacted.

## Machine and kernel

```text
16.0-CURRENT
16.0-CURRENT
16.0-CURRENT
```
```text
FreeBSD 16.0-CURRENT amd64
```
```text
kern.version: FreeBSD 16.0-CURRENT main-n290153-617c700abae7 GENERIC
```
```text
kern.osreldate: 1600028
hw.machine_arch: amd64
hw.ncpu: 24
hw.physmem: 136679825408
security.bsd.allow_ptrace_in_cap_mode: 1
security.bsd.see_other_uids: 0
security.bsd.see_other_gids: 0
security.bsd.unprivileged_proc_debug: 0
kern.trap_enotcap: 0
kern.elf64.allow_wx: 1
kern.elf64.aslr.enable: 1
kern.elf64.aslr.pie_enable: 1
kern.ipc.shm_allow_removed: 1
kern.racct.enable: 0
```

## Graphics and display

```text
    device     = 'Arrow Lake-S [Intel Graphics]'
    class      = display
    subclass   = VGA
none0@pci0:0:4:0:	class=0x118000 rev=0x01 hdr=0x00 vendor=0x8086 device=0xad03 subvendor=0x1043 subdevice=0x1214
    vendor     = 'Intel Corporation'
    device     = 'Core Ultra 200 Series Processors Dynamic Tuning Technology (DTT)'
--
    device     = 'GB203M / GN22-X11 [GeForce RTX 5090 Max-Q / Mobile]'
    class      = display
    subclass   = VGA
hdac0@pci0:2:0:1:	class=0x040300 rev=0xa1 hdr=0x00 vendor=0x10de device=0x22e9 subvendor=0x10de subdevice=0x0000
    vendor     = 'NVIDIA Corporation'
    device     = 'GB203 High Definition Audio Controller'
```
```text
nvidia-drm.ko
drm.ko
linuxkpi_video.ko
nvidia.ko
linux.ko
linux_common.ko
nvidia-modeset.ko
i915kms.ko
```
```text
XDG_SESSION_TYPE=wayland
WAYLAND_DISPLAY set
DISPLAY set
```

## Filesystems relevant to the sandbox

```text
fdescfs mounts: 0
```

## Packages

```text
chromium-156.0.8078.47_1
mesa-dri-26.2.2_1
mesa-libs-26.2.2_1
nvidia-driver-595.99.02_1
nvidia-drm-612-kmod-595.99.02.1600025_1
nvidia-drm-kmod-595.99.02
pipewire-1.6.9
pulseaudio-17.0_5
pulseaudio-qt6-1.9.0
sndio-1.10.0_1
wayland-1.26.0
wayland-protocols-1.49
wayland-utils-1.3.0
```
```text
chromium-156.0.8078.47_1:
```

## Source revisions

```text
d48855093718eb62019d19eff962e670eab132b2
```
```text
 2f81b9cafa38a95071e20de3f9cd6b0aca6d3c65 helium (0.3.4-1301-g2f81b9ca)
```
```text
fatal: detected dubious ownership in repository at '/usr/ports'
To add an exception for this directory, call:

	git config --global --add safe.directory /usr/ports
```
```text
156.0.8078.47
1
```

## Running Chromium processes

No chromium process found for this user. Start chromium, open one page, and run this script again to record the per-process baseline.
