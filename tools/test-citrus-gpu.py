#!/usr/bin/env python3
"""Host tests of firmware bounds and command-dispatch decoding, no hardware."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


gpu = module('build-citrus-gpu')
eagl = module('check-citrus-eagl')


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.source = self.directory / 'source'
        (self.source / 'iokit/Kernel/arm').mkdir(parents=True)
        self.mdt = bytearray(52 + 3 * 32)
        self.mdt[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<I', self.mdt, 28, 52)
        struct.pack_into('<HH', self.mdt, 42, 32, 3)
        struct.pack_into('<8I', self.mdt, 52 + 64, 1, 0, 0, 0x55a15000, 32, 4096, 5, 4096)
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        (self.directory / 'a610_zap.mdt').write_bytes(self.mdt)
        (self.directory / 'a610_zap.b02').write_bytes(bytes(32))
        (self.directory / 'a630_sqe.fw').write_bytes(bytes(8))

    def test_valid_import_and_probe_stub(self):
        records = gpu.firmware(self.directory, self.source)
        self.assertEqual(records['a610_zap.b02']['bytes'], 32)
        text = (self.source / 'iokit/Kernel/arm/TopazAdrenoFw.cpp').read_text()
        self.assertIn('topaz_fw_zap_b02_size = 32', text)
        gpu.firmware(None, self.source)
        self.assertIn('topaz_fw_zap_b02_size = 0', (self.source / 'iokit/Kernel/arm/TopazAdrenoFw.cpp').read_text())

    def test_truncated_program_headers(self):
        (self.directory / 'a610_zap.mdt').write_bytes(self.mdt[:60])
        with self.assertRaises(ValueError):
            gpu.firmware(self.directory, self.source)

    def test_reservation_overflow(self):
        struct.pack_into('<I', self.mdt, 52 + 64 + 20, 0x3000)
        self.write()
        with self.assertRaises(ValueError):
            gpu.firmware(self.directory, self.source)

    def test_segment_size_mismatch(self):
        (self.directory / 'a610_zap.b02').write_bytes(bytes(64))
        with self.assertRaises(ValueError):
            gpu.firmware(self.directory, self.source)

    def test_invalid_sqe(self):
        (self.directory / 'a630_sqe.fw').write_bytes(bytes(5))
        with self.assertRaises(ValueError):
            gpu.firmware(self.directory, self.source)


class DispatchTests(unittest.TestCase):
    def test_real_arm64_wrapper(self):
        # glBindTexture wrapper from 20H392, bounded to its own export range.
        data = bytes.fromhex('68d03bd5087940f9c80000b4e20301aae10300aa032940f9001140f960001fd6c0035fd6')
        class Memory:
            def read(self, address, count):
                return data[:count]
        offset, _ = eagl.dispatch_slot(Memory(), {'_glBindTexture': 0, '_next': len(data)}, 'glBindTexture')
        # Address zero is deliberately not a mapped function.
        self.assertIsNone(offset)
        offset, _ = eagl.dispatch_slot(Memory(), {'_glBindTexture': 4096, '_next': 4096 + len(data)}, 'glBindTexture')
        self.assertEqual(offset, 0x30)

    def test_unknown_code_does_not_claim_a_match(self):
        class Memory:
            def read(self, address, count):
                return bytes(count)
        offset, _ = eagl.dispatch_slot(Memory(), {'_glClear': 4096}, 'glClear')
        self.assertIsNone(offset)


if __name__ == '__main__':
    unittest.main()
