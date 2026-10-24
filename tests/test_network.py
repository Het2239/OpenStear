from host.network import LAN, TETHER, VIRTUAL, Iface, candidates, classify


def test_classify():
    assert classify("Wi-Fi", "192.168.1.20", "Intel(R) Wi-Fi 6 AX201") == LAN
    assert classify("Ethernet 3", "192.168.42.129", "Remote NDIS based Internet Sharing Device") == TETHER
    assert classify("Ethernet 4", "172.20.10.2", "Apple Mobile Device Ethernet") == TETHER
    assert classify("usb0", "10.12.0.5", "rndis_host") == TETHER
    assert classify("vEthernet (WSL)", "172.29.0.1", "Hyper-V Virtual Ethernet Adapter") == VIRTUAL
    assert classify("Tailscale", "100.101.1.2", "Tailscale Tunnel") == VIRTUAL
    assert classify("Loopback Pseudo-Interface 1", "127.0.0.1", "") == VIRTUAL
    assert classify("Ethernet", "169.254.3.4", "Realtek PCIe GbE") == VIRTUAL


def test_candidates():
    ifaces = [
        Iface("docker0", "172.17.0.1", VIRTUAL),
        Iface("eth0", "10.0.0.8", LAN),
        Iface("wlan0", "192.168.1.20", LAN),
        Iface("usb0", "192.168.42.129", TETHER),
    ]
    assert [i.ip for i in candidates("wifi", ifaces)] == ["192.168.1.20", "10.0.0.8"]
    assert [i.ip for i in candidates("tether", ifaces)] == ["192.168.42.129"]
