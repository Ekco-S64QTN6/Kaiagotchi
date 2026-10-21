import pytest

import kaiagotchi.network.pcap_parser as parser_module
from kaiagotchi.network.pcap_parser import parse_pcap, parse_pcap_comprehensive


class EmptyPacket:
    def haslayer(self, _layer):
        return False


class FakeReader:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        return iter([EmptyPacket()])

    def close(self):
        self.closed = True


@pytest.mark.parametrize("parse", [parse_pcap, parse_pcap_comprehensive])
def test_large_pcap_uses_reader_iterator_and_closes_reader(tmp_path, monkeypatch, parse):
    path = tmp_path / "large.pcap"
    path.write_bytes(b"x")
    reader = FakeReader()
    monkeypatch.setattr(parser_module, "PcapReader", lambda _path: reader)
    monkeypatch.setattr(parser_module.os.path, "getsize", lambda _path: 50 * 1024 * 1024 + 1)

    result = parse(str(path), use_streaming=True)

    assert reader.closed
    if hasattr(result, "total_packets"):
        assert result.total_packets == 1
    else:
        assert result == []



class FailingReader(FakeReader):
    def __iter__(self):
        yield EmptyPacket()
        raise RuntimeError("simulated reader error")


@pytest.mark.parametrize("parse", [parse_pcap, parse_pcap_comprehensive])
def test_large_pcap_closes_reader_when_iteration_fails(tmp_path, monkeypatch, parse):
    path = tmp_path / "failing.pcap"
    path.write_bytes(b"x")
    reader = FailingReader()
    monkeypatch.setattr(parser_module, "PcapReader", lambda _path: reader)
    monkeypatch.setattr(parser_module.os.path, "getsize", lambda _path: 50 * 1024 * 1024 + 1)

    with pytest.raises(RuntimeError, match="simulated reader error"):
        parse(str(path), use_streaming=True)

    assert reader.closed
