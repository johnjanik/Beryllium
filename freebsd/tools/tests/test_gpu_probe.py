# SPDX-License-Identifier: GPL-3.0-only
"""Tests for freebsd/tools/gpu-probe.

They run the real script with POSIX sh against stand-ins for the commands it
calls (uname, pciconf, kldstat, pkg, ssh) and a made-up /sys tree, and check
what it says about each kind of machine.
"""

import os
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PROBE = os.path.join(REPO, "freebsd", "tools", "gpu-probe")

INTEL = """\
hostb0@pci0:0:0:0:	class=0x060000 rev=0x02 hdr=0x00 vendor=0x8086 device=0x4621 subvendor=0x17aa subdevice=0x22e7
    vendor     = 'Intel Corporation'
    device     = '12th Gen Core Processor Host Bridge'
    class      = bridge
vgapci0@pci0:0:2:0:	class=0x030000 rev=0x0c hdr=0x00 vendor=0x8086 device=0x46a6 subvendor=0x17aa subdevice=0x22e7
    vendor     = 'Intel Corporation'
    device     = 'Alder Lake-P GT2 [Iris Xe Graphics]'
    class      = display
    subclass   = VGA
"""

NVIDIA = """\
vgapci1@pci0:1:0:0:	class=0x030000 rev=0xa1 hdr=0x00 vendor=0x10de device=0x2c58 subvendor=0x17aa subdevice=0x3d6f
    vendor     = 'NVIDIA Corporation'
    device     = 'GeForce RTX 5090 Laptop GPU'
    class      = display
    subclass   = VGA
"""

# FreeBSD 12 and earlier wrote the ids as one "chip" word.
OLD_AMD = """\
vgapci0@pci0:1:0:0:	class=0x030000 card=0x0b361002 chip=0x67df1002 rev=0xe7 hdr=0x00
    vendor     = 'Advanced Micro Devices, Inc. [AMD/ATI]'
    device     = 'Ellesmere [Radeon RX 470/480/570/580]'
    class      = display
"""

STUBS = {
    "uname": """
        case "$1" in
        -s) echo "${STUB_OS:-FreeBSD}" ;;
        -m) echo "${STUB_ARCH:-amd64}" ;;
        -n) echo testhost ;;
        -r) echo 16.0-CURRENT ;;
        esac""",
    "pciconf": 'cat "$STUB_PCICONF"',
    "kldstat": """
        echo "Id Refs Address                Size Name"
        n=1
        for m in kernel $STUB_MODULES; do
            echo " $n    1 0xffffffff80200000  1f3d4c8 $m.ko"
            n=$((n + 1))
        done""",
    "pkg": 'for p in $STUB_PACKAGES; do echo "$p"; done',
    "ssh": """
        echo "ssh $*" >>"$STUB_LOG"
        head -n 1 >>"$STUB_LOG"
        cat >/dev/null
        exit "${STUB_SSH_STATUS:-0}" """,
}


class GpuProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = os.path.join(self.tmp.name, "bin")
        os.mkdir(self.bin)
        for name, body in STUBS.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + textwrap.dedent(body) + "\n")
            os.chmod(path, 0o755)
        self.root = os.path.join(self.tmp.name, "root")
        os.mkdir(self.root)
        self.log = os.path.join(self.tmp.name, "log")

    def run_probe(self, *args, pciconf="", **env):
        listing = os.path.join(self.tmp.name, "pciconf.txt")
        with open(listing, "w") as f:
            f.write(pciconf)
        full = {
            "PATH": self.bin + ":/usr/bin:/bin",
            "GPU_PROBE_ROOT": self.root,
            "STUB_PCICONF": listing,
            "STUB_LOG": self.log,
        }
        full.update(env)
        return subprocess.run(["sh", PROBE, *args], env=full, text=True,
                              capture_output=True, stdin=subprocess.DEVNULL)

    def pci_device(self, address, vendor, device, driver=None, pci_class="0x030000"):
        d = os.path.join(self.root, "sys", "bus", "pci", "devices", address)
        os.makedirs(d)
        for name, value in (("class", pci_class), ("vendor", vendor), ("device", device)):
            with open(os.path.join(d, name), "w") as f:
                f.write(value + "\n")
        if driver:
            target = os.path.join(self.root, "sys", "bus", "pci", "drivers", driver)
            os.makedirs(target, exist_ok=True)
            os.symlink(target, os.path.join(d, "driver"))

    def test_freebsd_intel_is_a_mesa_machine(self):
        r = self.run_probe(pciconf=INTEL, STUB_MODULES="drm i915kms",
                           STUB_PACKAGES="mesa-libs-24.1.7 drm-66-kmod-6.6.25")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GPU: Intel, Alder Lake-P GT2 [Iris Xe Graphics] (at pci0:0:2:0)", r.stdout)
        self.assertIn("driver in use here: i915kms (Mesa)", r.stdout)
        self.assertIn("Verdict: a Mesa machine.", r.stdout)
        self.assertIn("  mesa-libs-24.1.7", r.stdout)
        self.assertNotIn("Host Bridge", r.stdout)
        self.assertNotIn("Note: this machine is", r.stdout)

    def test_freebsd_with_both_gpus_says_both(self):
        """The owner's laptop: Intel and NVIDIA, the desktop drawing on NVIDIA."""
        r = self.run_probe(pciconf=INTEL + NVIDIA,
                           STUB_MODULES="nvidia nvidia-modeset drm i915kms")
        self.assertIn("GPU: NVIDIA, GeForce RTX 5090 Laptop GPU (at pci0:1:0:0)", r.stdout)
        self.assertIn("driver in use here: nvidia (NVIDIA's own driver, no Mesa)", r.stdout)
        self.assertIn("Verdict: both.", r.stdout)

    def test_freebsd_nvidia_alone_is_not(self):
        r = self.run_probe(pciconf=NVIDIA, STUB_MODULES="nvidia nvidia-modeset")
        self.assertIn("Verdict: not a Mesa machine. FreeBSD would use NVIDIA's own driver.",
                      r.stdout)

    def test_a_gpu_with_no_module_loaded(self):
        r = self.run_probe(pciconf=INTEL, STUB_MODULES="")
        self.assertIn("driver in use here: none (no accelerated driver", r.stdout)
        self.assertIn("Verdict: a Mesa machine.", r.stdout)

    def test_old_pciconf_format(self):
        r = self.run_probe(pciconf=OLD_AMD, STUB_MODULES="drm amdgpu")
        self.assertIn("GPU: AMD, Ellesmere [Radeon RX 470/480/570/580]", r.stdout)
        self.assertIn("driver in use here: amdgpu (Mesa)", r.stdout)
        self.assertIn("Verdict: a Mesa machine.", r.stdout)

    def test_linux_amd_from_sysfs(self):
        self.pci_device("0000:00:1f.3", "0x8086", "0x51c8", pci_class="0x040380")
        self.pci_device("0000:03:00.0", "0x1002", "0x73df", driver="amdgpu")
        os.makedirs(os.path.join(self.root, "dev", "dri"))
        open(os.path.join(self.root, "dev", "dri", "renderD128"), "w").close()
        r = self.run_probe(STUB_OS="Linux", STUB_ARCH="x86_64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GPU: AMD, device 0x73df (at 0000:03:00.0)", r.stdout)
        self.assertIn("driver in use here: amdgpu (Mesa)", r.stdout)
        self.assertIn("Render nodes: /dev/dri/renderD128", r.stdout)
        self.assertIn("Verdict: a Mesa machine.", r.stdout)
        self.assertNotIn("0x51c8", r.stdout)

    def test_linux_nvidia_with_the_closed_driver(self):
        self.pci_device("0000:01:00.0", "0x10de", "0x2c58", driver="nvidia")
        r = self.run_probe(STUB_OS="Linux", STUB_ARCH="x86_64")
        self.assertIn("driver in use here: nvidia (NVIDIA's own driver, no Mesa)", r.stdout)
        self.assertIn("Verdict: not a Mesa machine.", r.stdout)

    def test_riscv_board_with_the_gpu_in_the_chip(self):
        """A VisionFive 2 under its vendor's Linux: no PCI GPU, a closed driver."""
        card = os.path.join(self.root, "sys", "class", "drm", "card0")
        device = os.path.join(self.root, "sys", "devices", "platform", "18000000.gpu")
        driver = os.path.join(self.root, "sys", "bus", "platform", "drivers", "pvrsrvkm")
        os.makedirs(os.path.join(device, "of_node"))
        os.makedirs(driver)
        os.makedirs(os.path.dirname(card))
        os.makedirs(card)
        os.symlink(device, os.path.join(card, "device"))
        os.symlink(driver, os.path.join(device, "driver"))
        with open(os.path.join(device, "of_node", "compatible"), "wb") as f:
            f.write(b"img,img-bxe-4-32\x00img,img-rogue\x00")
        # a connector directory, which is not a card
        os.makedirs(os.path.join(self.root, "sys", "class", "drm", "card0-HDMI-A-1"))
        r = self.run_probe(STUB_OS="Linux", STUB_ARCH="riscv64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("GPU in the processor chip: img,img-bxe-4-32 img,img-rogue", r.stdout)
        self.assertIn("driver in use here: pvrsrvkm (the chip maker's closed driver, no Mesa)",
                      r.stdout)
        self.assertIn("Verdict: not a Mesa machine under FreeBSD", r.stdout)
        self.assertIn("Note: this machine is riscv64. Beryllium is built for amd64 only",
                      r.stdout)

    def test_no_gpu_at_all(self):
        r = self.run_probe(STUB_OS="Linux", STUB_ARCH="x86_64")
        self.assertIn("Verdict: no GPU found on PCI.", r.stdout)

    def test_unknown_system(self):
        r = self.run_probe(STUB_OS="Plan9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Plan9 is not a system this script knows", r.stdout)

    def test_vendor_lookup(self):
        for given, words in (("0x8086", "Intel: under FreeBSD, Mesa, with the i915kms"),
                             ("10DE", "NVIDIA: under FreeBSD, NVIDIA's own driver"),
                             ("0x1002", "AMD: under FreeBSD, Mesa, with the amdgpu"),
                             ("abcd", "vendor 0xabcd: under FreeBSD, not known")):
            r = self.run_probe("--vendor", given)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(words, r.stdout)

    def test_vendor_lookup_refuses_what_is_not_an_id(self):
        for given in ("zz", "0x12345", "", "80 86"):
            r = self.run_probe("--vendor", given)
            self.assertEqual(r.returncode, 2, given)
            self.assertIn("is not a PCI vendor id", r.stderr)

    def test_hosts_are_probed_over_ssh_with_the_script_on_stdin(self):
        r = self.run_probe("alpha", "john@beta")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("=== alpha", r.stdout)
        self.assertIn("=== john@beta", r.stdout)
        with open(self.log) as f:
            log = f.read().splitlines()
        self.assertEqual(log, ["ssh -o ConnectTimeout=10 alpha sh -s", "#!/bin/sh",
                               "ssh -o ConnectTimeout=10 john@beta sh -s", "#!/bin/sh"])

    def test_a_host_that_does_not_answer_is_reported_and_the_rest_still_run(self):
        r = self.run_probe("alpha", "beta", STUB_SSH_STATUS="255")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.count("did not run the probe"), 2)

    def test_a_host_name_cannot_be_an_ssh_option(self):
        r = self.run_probe("alpha", "-oProxyCommand=touch /tmp/x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not a host name", r.stderr)
        self.assertFalse(os.path.exists(self.log), "ssh ran before the arguments were checked")

    def test_unknown_option(self):
        r = self.run_probe("--frobnicate")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown option", r.stderr)

    def test_the_script_runs_from_standard_input(self):
        """As it does on the far side of ssh: sh -s, with the script on stdin."""
        listing = os.path.join(self.tmp.name, "pciconf.txt")
        with open(listing, "w") as f:
            f.write(INTEL)
        env = {"PATH": self.bin + ":/usr/bin:/bin", "GPU_PROBE_ROOT": self.root,
               "STUB_PCICONF": listing, "STUB_MODULES": "i915kms"}
        with open(PROBE) as script:
            r = subprocess.run(["sh", "-s"], stdin=script, env=env, text=True,
                               capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Verdict: a Mesa machine.", r.stdout)


if __name__ == "__main__":
    unittest.main()
